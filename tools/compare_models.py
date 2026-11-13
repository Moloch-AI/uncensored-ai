#!/usr/bin/env python3
"""Compare models on your own prompts through an OpenAI-compatible endpoint.

Sends every prompt in a text or JSONL file to each model, one streamed request at a
time and paced under the rate limit, then writes a Markdown or CSV table with the
finish reason, latency, token usage and an excerpt of each answer.

Standard library only; Python 3.10 or later. Configuration comes from the environment:

    MOLOCHAI_API_KEY   required (any placeholder for a local server that ignores keys)
    MOLOCHAI_BASE_URL  optional, default https://api.molochai.dev/api/v1

Example:

    python tools/compare_models.py tools/prompts.example.txt \
        --models glm-5.3-flash,llama-3.3-70b-instruct-abliterated --output results.md

Replies are model output. Read them before drawing conclusions, and judge quality
with your own rubric. Documentation: https://github.com/Moloch-AI/uncensored-ai
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import email.utils
import enum
import http.client
import io
import json
import os
import random
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, TextIO

__version__ = "0.1.0"

DEFAULT_BASE_URL = "https://api.molochai.dev/api/v1"
USER_AGENT = f"uncensored-ai-compare-models/{__version__}"

# Appended by the MolochAI gateway when a reply stops at the plan's output cap.
CAP_NOTICE = "\n\n[Response is too large for your current plan. Try a smaller request.]"
# A reasoning block some servers leave inline at the start of the answer.
INLINE_THINK = re.compile(r"\A\s*<think>(.*?)</think>\s*", re.DOTALL)

DEFAULT_RPM = 50  # the API allows 60 requests a minute per account; leave headroom
MAX_RPM = 60
MAX_RATE_LIMIT_WAIT = 60.0  # seconds: the longest Retry-After this tool will honor
MAX_RATE_LIMIT_WAITS = 5  # rate-limit waits per request before recording an error
BACKOFF_CAP = 30.0  # seconds
PREEMPTED_DELAY = 60.0  # `preempted`: the API's advice is to retry in a minute

RETRY_IN_STREAM = frozenset({"server_busy", "upstream_unreachable", "upstream_timeout", "preempted"})
QUOTA_TYPES = frozenset({"quota_exceeded", "session_quota_exceeded"})
RETRY_STATUSES = frozenset({502, 503, 504, 524})
VALID_ROLES = frozenset({"system", "user", "assistant", "tool"})

Json = dict[str, Any]


# --------------------------------------------------------------------------- errors


class InputError(ValueError):
    """A prompt file or option that cannot be used."""


class ApiError(Exception):
    """An HTTP error response, an error event inside a stream, or a transport failure."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        error_type: str | None = None,
        body: Mapping[str, Any] | None = None,
        retry_after: float | None = None,
        in_stream: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.error_type = error_type
        self.body: Json = dict(body or {})
        self.retry_after = retry_after
        self.in_stream = in_stream

    def describe(self) -> str:
        """One line for a report: status, type, message and a reset time if there is one."""
        head = " ".join(
            part
            for part in (
                "in-stream" if self.in_stream else (str(self.status) if self.status else ""),
                self.error_type or "",
            )
            if part
        )
        text = f"{head}: {self.message}" if head else self.message
        resets_at = self.body.get("resets_at")
        if isinstance(resets_at, str) and resets_at:
            text += f" (resets at {resets_at})"
        return text


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _dict(value: Any) -> Json:
    return value if isinstance(value, dict) else {}


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def parse_retry_after(value: str | None, now: float | None = None) -> float | None:
    """Seconds to wait from a Retry-After header: delta-seconds or an HTTP date."""
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    current = time.time() if now is None else now
    return max(0.0, when.timestamp() - current)


def parse_error_body(status: int, raw: bytes, retry_after: str | None = None) -> ApiError:
    """Turn an error response into an ApiError, whichever body shape it has.

    The API uses three JSON shapes, and some errors (a Cloudflare 524) are not JSON:
      A. {"error": {"type": "...", "message": "...", ...extra fields}}
      B. {"message": "...", "errors": {"field": ["..."]}}            (422)
      C. {"message": "..."} with an optional "code"                    (401, 403, 429)
    """
    wait = parse_retry_after(retry_after)
    text = raw.decode("utf-8", errors="replace").strip()
    try:
        data: Any = json.loads(text) if text else None
    except ValueError:
        data = None
    if isinstance(data, dict):
        inner = data.get("error")
        if isinstance(inner, dict):
            return ApiError(
                str(inner.get("message") or f"HTTP {status}"),
                status=status,
                error_type=_str_or_none(inner.get("type")),
                body=inner,
                retry_after=wait,
            )
        if isinstance(data.get("errors"), dict):
            return ApiError(
                str(data.get("message") or "The request is invalid."),
                status=status,
                error_type="validation_error",
                body=data,
                retry_after=wait,
            )
        if "message" in data:
            return ApiError(
                str(data["message"]),
                status=status,
                error_type=_str_or_none(data.get("code")),
                body=data,
                retry_after=wait,
            )
    snippet = " ".join(re.sub(r"<[^>]*>", " ", text).split())[:120]
    message = f"HTTP {status} with a non-JSON body" + (f": {snippet}" if snippet else "")
    return ApiError(message, status=status, retry_after=wait)


class Action(enum.Enum):
    """What the runner does after an error."""

    RETRY = "retry"  # transient: back off and try again
    WAIT = "wait"  # per-minute rate limit: wait for Retry-After, then try again
    SKIP_MODEL = "skip_model"  # this model cannot answer now: skip its remaining prompts
    ABORT = "abort"  # nothing else will succeed (auth, billing, quota): stop the run
    FAIL = "fail"  # record the error for this prompt and carry on


def classify(err: ApiError) -> Action:
    """Map an error to an action, following the API's retry guidance."""
    if err.in_stream:
        if err.error_type in RETRY_IN_STREAM:
            return Action.RETRY
        upstream = _int_or_none(err.body.get("status"))
        if err.error_type == "upstream_error" and upstream is not None and upstream >= 500:
            return Action.RETRY
        return Action.FAIL
    status = err.status
    if status is None:
        return Action.RETRY  # connection error, timeout or a stream cut short
    if status in (401, 402, 403):
        return Action.ABORT
    if status == 429:
        # Quota errors carry a type and do not pass before resets_at; the rate limit does not.
        return Action.ABORT if err.error_type in QUOTA_TYPES else Action.WAIT
    if status == 503 and err.error_type == "model_unavailable":
        return Action.SKIP_MODEL
    if status == 404:
        return Action.SKIP_MODEL  # unknown model on some servers, or a wrong base URL
    if status == 422 and isinstance(err.body.get("errors"), dict) and "model" in err.body["errors"]:
        return Action.SKIP_MODEL
    if status in RETRY_STATUSES or status >= 500:
        return Action.RETRY
    return Action.FAIL  # 413 and other 4xx: retrying the same request will not help


def backoff_delay(retry: int, err: ApiError, base: float, rng: Callable[[], float] = random.random) -> float:
    """Exponential backoff with jitter. `preempted` waits about a minute (scaled by base)."""
    delay: float = min(BACKOFF_CAP, base * (2**retry)) + rng() * base
    if err.error_type == "preempted":
        delay = max(delay, PREEMPTED_DELAY * base)
    return delay


# --------------------------------------------------------------------------- prompts


@dataclass
class Prompt:
    id: str
    messages: list[Json]

    @property
    def text(self) -> str:
        """The last user message, as shown in the report."""
        for message in reversed(self.messages):
            if message.get("role") == "user":
                return _content_text(message.get("content"))
        return _content_text(self.messages[-1].get("content")) if self.messages else ""


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def _with_system(messages: list[Json], system: str | None) -> list[Json]:
    if system and not (messages and messages[0].get("role") == "system"):
        return [{"role": "system", "content": system}, *messages]
    return messages


def _check_messages(messages: Any, where: str) -> list[Json]:
    if not isinstance(messages, list) or not messages:
        raise InputError(f"{where}: 'messages' must be a non-empty list")
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in VALID_ROLES:
            raise InputError(f"{where}: every message needs a role of {sorted(VALID_ROLES)}")
    return [dict(message) for message in messages]


def parse_prompts(
    lines: Iterable[str], fmt: str, system: str | None = None, source: str = "input"
) -> list[Prompt]:
    """Parse prompts from text lines.

    text:  one prompt per line; blank lines and lines starting with '#' are skipped.
    jsonl: one JSON object per line with "prompt" (a string) or "messages" (a list in
           Chat Completions format), and optionally "id" and "system".
    """
    prompts: list[Prompt] = []
    for number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or (fmt == "text" and line.startswith("#")):
            continue
        where = f"{source}:{number}"
        if fmt == "text":
            prompts.append(
                Prompt(str(len(prompts) + 1), _with_system([{"role": "user", "content": line}], system))
            )
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise InputError(f"{where}: not valid JSON ({exc.msg})") from None
        if not isinstance(item, dict):
            raise InputError(f"{where}: each line must be a JSON object")
        item_system = item.get("system", system)
        if item_system is not None and not isinstance(item_system, str):
            raise InputError(f"{where}: 'system' must be a string")
        if "messages" in item:
            messages = _check_messages(item["messages"], where)
        elif isinstance(item.get("prompt"), str) and item["prompt"].strip():
            messages = [{"role": "user", "content": item["prompt"]}]
        else:
            raise InputError(f"{where}: needs a non-empty 'prompt' string or a 'messages' list")
        prompt_id = item.get("id", len(prompts) + 1)
        if not isinstance(prompt_id, (str, int)) or isinstance(prompt_id, bool):
            raise InputError(f"{where}: 'id' must be a string or an integer")
        prompts.append(Prompt(str(prompt_id), _with_system(messages, item_system)))
    return prompts


def load_prompts(path: Path, fmt: str | None = None, system: str | None = None) -> list[Prompt]:
    """Read prompts from a file; the format follows the extension unless given."""
    if fmt is None:
        fmt = "jsonl" if path.suffix.lower() in (".jsonl", ".ndjson") else "text"
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise InputError(f"cannot read {path}: {exc.strerror or exc}") from None
    prompts = parse_prompts(text.splitlines(), fmt, system, source=path.name)
    if not prompts:
        raise InputError(f"{path} contains no prompts")
    return prompts


# --------------------------------------------------------------------------- streaming


@dataclass
class StreamResult:
    content: str = ""
    reasoning: str = ""
    finish_reason: str | None = None
    usage: Json | None = None
    tool_calls: list[Json] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)
    done: bool = False
    first_output_s: float | None = None
    latency_s: float | None = None


class StreamParser:
    """Incremental parser for a Chat Completions server-sent event stream.

    Feed it one line at a time. Comment lines (starting with ':') are collected and
    otherwise ignored, `data:` lines are joined per event, the stream ends at
    `data: [DONE]`, and an `{"error": ...}` event raises ApiError. Tool-call fragments
    are accumulated by index, which also handles arguments that arrive whole.
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        on_comment: Callable[[str], None] | None = None,
    ) -> None:
        self.result = StreamResult()
        self._clock = clock
        self._start = clock()
        self._on_comment = on_comment
        self._data: list[str] = []
        self._content: list[str] = []
        self._reasoning: list[str] = []
        self._tools: dict[int, Json] = {}

    def feed_line(self, line: str) -> None:
        line = line.rstrip("\r\n")
        if not line:
            self._dispatch()
            return
        if line.startswith(":"):
            comment = line[1:].strip()
            self.result.comments.append(comment)
            if self._on_comment is not None:
                self._on_comment(comment)
            return
        name, sep, value = line.partition(":")
        if sep and value.startswith(" "):
            value = value[1:]
        if name == "data":
            self._data.append(value)
        # Other fields (event, id, retry) carry nothing this API uses.

    def feed(self, lines: Iterable[str]) -> StreamResult:
        for line in lines:
            self.feed_line(line)
            if self.result.done:
                break
        return self.close()

    def close(self) -> StreamResult:
        self._dispatch()
        result = self.result
        result.content = "".join(self._content)
        result.reasoning = "".join(self._reasoning)
        result.tool_calls = [self._tools[index] for index in sorted(self._tools)]
        result.latency_s = self.elapsed()
        return result

    def elapsed(self) -> float:
        """Seconds since the parser was created, which is just before the request."""
        return self._clock() - self._start

    def _mark_output(self) -> None:
        if self.result.first_output_s is None:
            self.result.first_output_s = self.elapsed()

    def _dispatch(self) -> None:
        if not self._data:
            return
        data = "\n".join(self._data)
        self._data = []
        if self.result.done:
            return
        if data.strip() == "[DONE]":
            self.result.done = True
            return
        try:
            event: Any = json.loads(data)
        except ValueError:
            event = None
        if not isinstance(event, dict):
            raise ApiError(
                "the stream carried an event that is not a JSON object",
                status=200,
                error_type="invalid_stream",
                in_stream=True,
            )
        if "error" in event:
            err = event["error"] if isinstance(event["error"], dict) else {"message": str(event["error"])}
            raise ApiError(
                str(err.get("message") or "error event in the stream"),
                status=200,
                error_type=_str_or_none(err.get("type")),
                body=err,
                in_stream=True,
            )
        usage = event.get("usage")
        if isinstance(usage, dict):
            self.result.usage = usage
        choices = event.get("choices")
        if not isinstance(choices, list) or not choices:
            return  # the final usage chunk has no choices
        choice = next(
            (c for c in choices if isinstance(c, dict) and c.get("index", 0) == 0),
            None,
        )
        if choice is None:
            return
        delta = _dict(choice.get("delta"))
        text = delta.get("content")
        if isinstance(text, str) and text:
            self._mark_output()
            self._content.append(text)
        thought = delta.get("reasoning_content")
        if isinstance(thought, str) and thought:
            self._mark_output()
            self._reasoning.append(thought)
        fragments = delta.get("tool_calls")
        if isinstance(fragments, list):
            self._mark_output()
            for position, fragment in enumerate(fragments):
                if isinstance(fragment, dict):
                    self._add_tool_fragment(position, fragment)
        finish = choice.get("finish_reason")
        if isinstance(finish, str) and finish:
            self.result.finish_reason = finish

    def _add_tool_fragment(self, position: int, fragment: Json) -> None:
        index = fragment.get("index")
        if not isinstance(index, int):
            index = position
        slot = self._tools.setdefault(
            index, {"id": None, "type": "function", "function": {"name": "", "arguments": ""}}
        )
        if isinstance(fragment.get("id"), str):
            slot["id"] = fragment["id"]
        if isinstance(fragment.get("type"), str):
            slot["type"] = fragment["type"]
        function = fragment.get("function")
        if isinstance(function, dict):
            if isinstance(function.get("name"), str) and function["name"]:
                slot["function"]["name"] = function["name"]
            if isinstance(function.get("arguments"), str):
                slot["function"]["arguments"] += function["arguments"]


def result_from_completion(payload: Any, latency_s: float) -> StreamResult:
    """Build a result from a non-streamed `chat.completion`, for servers that ignore `stream`."""
    if not isinstance(payload, dict) or not isinstance(payload.get("choices"), list):
        raise ApiError(
            "unexpected response: not a chat completion", status=200, error_type="invalid_response"
        )
    result = StreamResult(done=True, latency_s=latency_s, first_output_s=latency_s)
    usage = payload.get("usage")
    result.usage = usage if isinstance(usage, dict) else None
    choice = payload["choices"][0] if payload["choices"] else {}
    if isinstance(choice, dict):
        message = _dict(choice.get("message"))
        content = message.get("content")
        result.content = content if isinstance(content, str) else ""
        reasoning = message.get("reasoning_content")
        result.reasoning = reasoning if isinstance(reasoning, str) else ""
        calls = message.get("tool_calls")
        result.tool_calls = [c for c in calls if isinstance(c, dict)] if isinstance(calls, list) else []
        finish = choice.get("finish_reason")
        result.finish_reason = finish if isinstance(finish, str) else None
    return result


# --------------------------------------------------------------------------- HTTP client


class Client:
    """A minimal client for the two endpoints this tool needs."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 120.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.clock = clock

    def _open(self, method: str, path: str, body: Json | None, accept: str) -> http.client.HTTPResponse:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": accept,
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            response: http.client.HTTPResponse = urllib.request.urlopen(request, timeout=self.timeout)
            return response
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read()
            except (OSError, http.client.HTTPException):
                raw = b""
            finally:
                exc.close()
            raise parse_error_body(exc.code, raw, exc.headers.get("Retry-After")) from None
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            reason = getattr(exc, "reason", None) or exc
            raise ApiError(f"connection failed: {reason}", error_type="connection_error") from None

    def list_models(self) -> list[Json]:
        """GET /models, as a list of model objects with at least an `id`."""
        try:
            with self._open("GET", "/models", None, "application/json") as response:
                payload: Any = json.loads(response.read().decode("utf-8"))
        except ValueError:
            raise ApiError(
                "GET /models did not return JSON", status=200, error_type="invalid_response"
            ) from None
        except (OSError, http.client.HTTPException) as exc:
            raise ApiError(f"connection failed: {exc}", error_type="connection_error") from None
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise ApiError("GET /models returned no 'data' list", status=200, error_type="invalid_response")
        return [m for m in data if isinstance(m, dict) and isinstance(m.get("id"), str)]

    def stream_chat(
        self,
        model: str,
        messages: list[Json],
        *,
        temperature: float | None = None,
        top_p: float | None = None,
        on_comment: Callable[[str], None] | None = None,
    ) -> StreamResult:
        """POST /chat/completions with stream=true and collect the whole reply."""
        body: Json = {
            "model": model,
            "messages": messages,
            "stream": True,
            # MolochAI always sends usage and ignores this; other servers need it.
            "stream_options": {"include_usage": True},
        }
        if temperature is not None:
            body["temperature"] = temperature
        if top_p is not None:
            body["top_p"] = top_p
        parser = StreamParser(clock=self.clock, on_comment=on_comment)
        try:
            with self._open("POST", "/chat/completions", body, "text/event-stream") as response:
                content_type = response.headers.get("Content-Type", "")
                if "text/event-stream" not in content_type:
                    payload: Any = json.loads(response.read().decode("utf-8"))
                    return result_from_completion(payload, parser.elapsed())
                result = parser.feed(raw.decode("utf-8", errors="replace") for raw in response)
        except ValueError:
            raise ApiError(
                "the response was not valid JSON", status=200, error_type="invalid_response"
            ) from None
        except (OSError, http.client.HTTPException) as exc:
            raise ApiError(f"connection lost while streaming: {exc}", error_type="connection_error") from None
        if not result.done and result.finish_reason is None:
            raise ApiError("the stream ended before the reply finished", error_type="incomplete_stream")
        return result


# --------------------------------------------------------------------------- running


class Pacer:
    """Keeps request starts at least 60/rpm seconds apart."""

    def __init__(
        self,
        rpm: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if rpm <= 0:
            raise ValueError("rpm must be positive")
        self.interval = 60.0 / rpm
        self._clock = clock
        self._sleep = sleep
        self._next: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._next is not None and now < self._next:
            self._sleep(self._next - now)
            now = self._next
        self._next = now + self.interval


@dataclass
class Row:
    prompt_id: str
    prompt: str
    model: str
    finish_reason: str | None = None
    latency_s: float | None = None
    first_output_s: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    answer: str = ""
    reasoning_chars: int = 0
    capped: bool = False
    tool_calls: list[str] = field(default_factory=list)
    attempts: int = 0
    error: str | None = None
    error_status: int | None = None
    error_type: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def row_from_result(prompt: Prompt, model: str, result: StreamResult, attempts: int) -> Row:
    answer = result.content
    reasoning = result.reasoning
    inline = INLINE_THINK.match(answer)
    if inline:  # a server that left reasoning inline
        reasoning += inline.group(1)
        answer = answer[inline.end() :]
    capped = answer.endswith(CAP_NOTICE)
    if capped:
        answer = answer[: -len(CAP_NOTICE)]
    usage = result.usage or {}
    return Row(
        prompt_id=prompt.id,
        prompt=prompt.text,
        model=model,
        finish_reason=result.finish_reason,
        latency_s=result.latency_s,
        first_output_s=result.first_output_s,
        prompt_tokens=_int_or_none(usage.get("prompt_tokens")),
        completion_tokens=_int_or_none(usage.get("completion_tokens")),
        total_tokens=_int_or_none(usage.get("total_tokens")),
        answer=answer,
        reasoning_chars=len(reasoning),
        capped=capped,
        tool_calls=[str(_dict(call.get("function")).get("name") or "?") for call in result.tool_calls],
        attempts=attempts,
    )


def error_row(prompt: Prompt, model: str, err: ApiError, attempts: int) -> Row:
    return Row(
        prompt_id=prompt.id,
        prompt=prompt.text,
        model=model,
        attempts=attempts,
        error=err.describe(),
        error_status=err.status,
        error_type=err.error_type,
    )


class ChatStreamer(Protocol):
    """What the runner needs from a client. Client implements it; tests use fakes."""

    def stream_chat(
        self,
        model: str,
        messages: list[Json],
        *,
        temperature: float | None = None,
        top_p: float | None = None,
        on_comment: Callable[[str], None] | None = None,
    ) -> StreamResult: ...


@dataclass
class RunResult:
    rows: list[Row]
    aborted: ApiError | None = None
    interrupted: bool = False


def _noop(_message: str) -> None:
    return None


def run_one(
    client: ChatStreamer,
    prompt: Prompt,
    model: str,
    *,
    pacer: Pacer,
    retries: int = 2,
    backoff: float = 1.0,
    temperature: float | None = None,
    top_p: float | None = None,
    sleep: Callable[[float], None] = time.sleep,
    rng: Callable[[], float] = random.random,
    progress: Callable[[str], None] = _noop,
) -> tuple[Row, Action | None, ApiError | None]:
    """Send one prompt to one model, with the retry policy applied."""
    attempts = retried = waited = 0

    def on_comment(comment: str) -> None:
        if comment.startswith("queued"):  # optional progress: "queued · position 2 of 3 · ..."
            progress(f"    {model}: {comment}")

    while True:
        pacer.wait()
        attempts += 1
        try:
            result = client.stream_chat(
                model, prompt.messages, temperature=temperature, top_p=top_p, on_comment=on_comment
            )
        except ApiError as err:
            action = classify(err)
            if action is Action.WAIT and waited < MAX_RATE_LIMIT_WAITS:
                waited += 1
                delay = min(err.retry_after if err.retry_after is not None else 1.0, MAX_RATE_LIMIT_WAIT)
                progress(f"    rate limited; waiting {delay:.0f}s")
                sleep(delay)
                continue
            if action is Action.RETRY and retried < retries:
                delay = backoff_delay(retried, err, backoff, rng)
                retried += 1
                progress(f"    {err.describe()}; retrying in {delay:.1f}s")
                sleep(delay)
                continue
            return error_row(prompt, model, err, attempts), action, err
        return row_from_result(prompt, model, result, attempts), None, None


def run_comparison(
    client: ChatStreamer,
    prompts: Sequence[Prompt],
    models: Sequence[str],
    *,
    pacer: Pacer,
    retries: int = 2,
    backoff: float = 1.0,
    temperature: float | None = None,
    top_p: float | None = None,
    sleep: Callable[[float], None] = time.sleep,
    rng: Callable[[], float] = random.random,
    progress: Callable[[str], None] = _noop,
) -> RunResult:
    """Send every prompt to every model, prompt by prompt, and collect the rows."""
    rows: list[Row] = []
    skipped: dict[str, str] = {}
    total = len(prompts) * len(models)
    count = 0
    try:
        for prompt in prompts:
            for model in models:
                count += 1
                if model in skipped:
                    rows.append(
                        Row(
                            prompt.id,
                            prompt.text,
                            model,
                            error=f"skipped: {skipped[model]}",
                            error_type="skipped",
                        )
                    )
                    continue
                progress(f"[{count}/{total}] prompt {prompt.id} -> {model}")
                row, action, err = run_one(
                    client,
                    prompt,
                    model,
                    pacer=pacer,
                    retries=retries,
                    backoff=backoff,
                    temperature=temperature,
                    top_p=top_p,
                    sleep=sleep,
                    rng=rng,
                    progress=progress,
                )
                rows.append(row)
                if row.ok:
                    progress(f"    {row.finish_reason or 'done'} in {row.latency_s or 0:.1f}s")
                    continue
                progress(f"    error: {row.error}")
                if action is Action.SKIP_MODEL:
                    skipped[model] = row.error_type or f"HTTP {row.error_status}"
                elif action is Action.ABORT:
                    return RunResult(rows, aborted=err)
    except KeyboardInterrupt:
        return RunResult(rows, interrupted=True)
    return RunResult(rows)


# --------------------------------------------------------------------------- output


def excerpt(text: str, limit: int) -> str:
    """Whitespace collapsed to single spaces, cut to `limit` characters (0 = no limit)."""
    flat = " ".join(text.split())
    if limit <= 0 or len(flat) <= limit:
        return flat
    return flat[: max(1, limit - 3)].rstrip() + "..."


def md_cell(text: str) -> str:
    """Make text safe inside a Markdown table cell or a quote line."""
    flat = " ".join(text.split())
    flat = flat.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return flat.replace("\\", "\\\\").replace("|", "\\|")


def _num(value: float | None, digits: int = 1) -> str:
    return "" if value is None else f"{value:.{digits}f}"


def _int(value: int | None) -> str:
    return "" if value is None else str(value)


def _notes(row: Row) -> list[str]:
    notes: list[str] = []
    if row.capped:
        notes.append("output cap reached")
    if row.tool_calls:
        notes.append("tool call: " + ", ".join(row.tool_calls))
    if row.reasoning_chars:
        notes.append(f"reasoning: {row.reasoning_chars} chars")
    if row.attempts > 1:
        notes.append(f"{row.attempts} attempts")
    return notes


@dataclass
class RunInfo:
    base_url: str
    models: list[str]
    source: str
    prompt_count: int
    started: datetime
    temperature: float | None = None
    top_p: float | None = None


def render_markdown(run: RunResult, info: RunInfo, excerpt_chars: int = 160) -> str:
    out = io.StringIO()
    w = out.write
    w("# Model comparison\n\n")
    w(f"- Started: {info.started.strftime('%Y-%m-%d %H:%M UTC')}\n")
    w(f"- Endpoint: `{info.base_url}`\n")
    source = info.source.replace("\\", "/").replace("`", "'")
    w(f"- Prompts: {info.prompt_count} from `{source}`\n")
    w(f"- Models: {', '.join(f'`{m}`' for m in info.models)}\n")
    temperature = "default" if info.temperature is None else str(info.temperature)
    top_p = "default" if info.top_p is None else str(info.top_p)
    w(f"- Sampling: temperature {temperature}, top_p {top_p}; every request streamed\n\n")
    if run.aborted is not None:
        w(f"> **The run stopped early:** {md_cell(run.aborted.describe())}. Results below are partial.\n\n")
    if run.interrupted:
        w("> **The run was interrupted.** Results below are partial.\n\n")
    w(
        "Latency is the time to the end of the streamed reply; first output is the time to "
        "the first reasoning or answer token. Tokens are the API's `usage` figures "
        "(the total includes reasoning). Excerpts are the start of each answer, with "
        "whitespace collapsed. These are single samples: read the replies before you "
        "draw conclusions.\n\n"
    )

    w("## Summary\n\n")
    w(
        "| Model | Replies | Errors | Median latency (s) | Median first output (s) | Total tokens | Finish reasons |\n"
    )
    w("|---|---|---|---|---|---|---|\n")
    for model in info.models:
        mine = [r for r in run.rows if r.model == model]
        ok = [r for r in mine if r.ok]
        latencies = [r.latency_s for r in ok if r.latency_s is not None]
        firsts = [r.first_output_s for r in ok if r.first_output_s is not None]
        tokens = [r.total_tokens for r in ok if r.total_tokens is not None]
        reasons: dict[str, int] = {}
        for r in ok:
            key = r.finish_reason or "none"
            reasons[key] = reasons.get(key, 0) + 1
        w(
            f"| `{model}` | {len(ok)} | {len(mine) - len(ok)} "
            f"| {_num(statistics.median(latencies), 2) if latencies else ''} "
            f"| {_num(statistics.median(firsts), 2) if firsts else ''} "
            f"| {sum(tokens) if tokens else ''} "
            f"| {', '.join(f'{k} {v}' for k, v in sorted(reasons.items()))} |\n"
        )
    w("\n## Replies\n")

    prompt_ids: list[str] = []
    for row in run.rows:
        if row.prompt_id not in prompt_ids:
            prompt_ids.append(row.prompt_id)
    for prompt_id in prompt_ids:
        rows = [r for r in run.rows if r.prompt_id == prompt_id]
        w(f"\n### Prompt {md_cell(prompt_id)}\n\n")
        w(f"> {md_cell(excerpt(rows[0].prompt, 500))}\n\n")
        w(
            "| Model | Finish | Latency (s) | First output (s) | Prompt tokens | Completion tokens | Total tokens | Notes | Answer |\n"
        )
        w("|---|---|---|---|---|---|---|---|---|\n")
        for r in rows:
            if r.ok:
                answer = md_cell(excerpt(r.answer, excerpt_chars))
            else:
                answer = f"**Error:** {md_cell(r.error or '')}"
            w(
                f"| `{r.model}` | {r.finish_reason or ''} | {_num(r.latency_s, 2)} | {_num(r.first_output_s, 2)} "
                f"| {_int(r.prompt_tokens)} | {_int(r.completion_tokens)} | {_int(r.total_tokens)} "
                f"| {md_cell('; '.join(_notes(r)))} | {answer} |\n"
            )
    return out.getvalue()


CSV_COLUMNS = [
    "prompt_id",
    "prompt",
    "model",
    "finish_reason",
    "latency_s",
    "first_output_s",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "reasoning_chars",
    "capped",
    "tool_calls",
    "attempts",
    "answer",
    "error_status",
    "error_type",
    "error",
]


def render_csv(run: RunResult, excerpt_chars: int = 160) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for r in run.rows:
        writer.writerow(
            [
                r.prompt_id,
                r.prompt,
                r.model,
                r.finish_reason or "",
                _num(r.latency_s, 3),
                _num(r.first_output_s, 3),
                _int(r.prompt_tokens),
                _int(r.completion_tokens),
                _int(r.total_tokens),
                r.reasoning_chars,
                "yes" if r.capped else "",
                " ".join(r.tool_calls),
                r.attempts,
                excerpt(r.answer, excerpt_chars) if excerpt_chars else r.answer,
                _int(r.error_status),
                r.error_type or "",
                r.error or "",
            ]
        )
    return out.getvalue()


# --------------------------------------------------------------------------- command line


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compare_models.py",
        description=(
            "Send each prompt in a file to several models on an OpenAI-compatible endpoint "
            "and write a Markdown or CSV comparison. Reads MOLOCHAI_API_KEY (required) and "
            f"MOLOCHAI_BASE_URL (default {DEFAULT_BASE_URL})."
        ),
        epilog=(
            "Prompt files: .txt has one prompt per line (blank lines and lines starting with # "
            "are skipped); .jsonl has one object per line with 'prompt' or 'messages', and "
            "optional 'id' and 'system'. Exit status: 0 when every request was attempted "
            "(rows may still hold errors), 1 when the run stopped on an error that affects "
            "every request (key, billing, quota), 2 for a usage or input error, 130 when "
            "interrupted."
        ),
    )
    parser.add_argument("prompts", nargs="?", type=Path, help="prompt file (.txt or .jsonl)")
    parser.add_argument(
        "-m",
        "--models",
        action="append",
        metavar="IDS",
        help="model ids, comma-separated or repeated; default: every model GET /models lists as available",
    )
    parser.add_argument("-o", "--output", type=Path, help="write the report here instead of to stdout")
    parser.add_argument(
        "-f",
        "--format",
        choices=("markdown", "csv"),
        help="report format; default: csv for a .csv output path, otherwise markdown",
    )
    parser.add_argument(
        "--input-format", choices=("text", "jsonl"), help="override the format the extension implies"
    )
    parser.add_argument("--system", help="system message for prompts that do not start with one")
    parser.add_argument("--temperature", type=float, help="0 to 2; default: the model's default")
    parser.add_argument("--top-p", type=float, help="0 to 1; default: the model's default")
    parser.add_argument(
        "--rpm",
        type=float,
        default=DEFAULT_RPM,
        help=f"requests per minute to stay under, at most {MAX_RPM} (default {DEFAULT_RPM})",
    )
    parser.add_argument(
        "--retries", type=int, default=2, help="retries per request for transient errors (default 2)"
    )
    parser.add_argument(
        "--backoff", type=float, default=1.0, help="base backoff delay in seconds (default 1)"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="seconds to wait for data before giving up on a connection (default 120)",
    )
    parser.add_argument(
        "--excerpt-chars",
        type=int,
        default=160,
        help="answer characters to keep per row; 0 keeps the whole answer (default 160)",
    )
    parser.add_argument("--base-url", help="API base URL; overrides MOLOCHAI_BASE_URL")
    parser.add_argument("--list-models", action="store_true", help="list the endpoint's models and exit")
    parser.add_argument("-q", "--quiet", action="store_true", help="no progress on stderr")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _split_models(values: list[str] | None) -> list[str]:
    models: list[str] = []
    for value in values or []:
        for part in value.split(","):
            model = part.strip()
            if model and model not in models:
                models.append(model)
    return models


def _validate(args: argparse.Namespace) -> None:
    if args.temperature is not None and not 0 <= args.temperature <= 2:
        raise InputError("--temperature must be between 0 and 2")
    if args.top_p is not None and not 0 <= args.top_p <= 1:
        raise InputError("--top-p must be between 0 and 1")
    if not 0 < args.rpm <= MAX_RPM:
        raise InputError(f"--rpm must be above 0 and at most {MAX_RPM} (the API's per-minute limit)")
    if args.retries < 0:
        raise InputError("--retries cannot be negative")
    if args.backoff < 0:
        raise InputError("--backoff cannot be negative")
    if args.timeout <= 0:
        raise InputError("--timeout must be positive")


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    env = os.environ if env is None else env
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    parser = build_parser()
    args = parser.parse_args(argv)

    def say(message: str) -> None:
        if not args.quiet:
            print(message, file=stderr, flush=True)

    def fail(message: str, code: int = 2) -> int:
        print(f"compare_models: {message}", file=stderr)
        return code

    try:
        _validate(args)
    except InputError as exc:
        return fail(str(exc))
    api_key = env.get("MOLOCHAI_API_KEY", "").strip()
    if not api_key:
        return fail("MOLOCHAI_API_KEY is not set (a placeholder works for a local server that ignores keys)")
    base_url = (args.base_url or env.get("MOLOCHAI_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        return fail(f"the base URL must start with http:// or https:// (got {base_url!r})")
    client = Client(base_url, api_key, timeout=args.timeout)

    if args.list_models:
        try:
            listed = client.list_models()
        except ApiError as err:
            return fail(f"GET /models failed: {err.describe()}", 1)
        for model in listed:
            available = model.get("available")
            state = "" if available is None else ("available" if available else "unavailable")
            print(f"{model['id']}\t{state}\t{model.get('name', '')}".rstrip(), file=stdout)
        return 0

    if args.prompts is None:
        return fail("a prompt file is required (or use --list-models)")
    try:
        prompts = load_prompts(args.prompts, args.input_format, args.system)
    except InputError as exc:
        return fail(str(exc))

    models = _split_models(args.models)
    if not models:
        try:
            listed = client.list_models()
        except ApiError as err:
            return fail(f"GET /models failed: {err.describe()}", 1)
        models = [m["id"] for m in listed if m.get("available", True) is not False]
        if not models:
            return fail("GET /models lists no available model; pass --models", 1)
        say(f"models from GET /models: {', '.join(models)}")

    fmt = args.format or ("csv" if args.output and args.output.suffix.lower() == ".csv" else "markdown")
    started = datetime.now(timezone.utc)
    run = run_comparison(
        client,
        prompts,
        models,
        pacer=Pacer(args.rpm, sleep=sleep),
        retries=args.retries,
        backoff=args.backoff,
        temperature=args.temperature,
        top_p=args.top_p,
        sleep=sleep,
        progress=say,
    )
    info = RunInfo(
        base_url=base_url,
        models=models,
        source=str(args.prompts),
        prompt_count=len(prompts),
        started=started,
        temperature=args.temperature,
        top_p=args.top_p,
    )
    report = (
        render_csv(run, args.excerpt_chars)
        if fmt == "csv"
        else render_markdown(run, info, args.excerpt_chars)
    )
    if args.output:
        try:
            args.output.write_text(report, encoding="utf-8", newline="\n")
        except OSError as exc:
            return fail(f"cannot write {args.output}: {exc.strerror or exc}")
        say(f"wrote {len(run.rows)} rows to {args.output}")
    else:
        if stdout is sys.stdout and isinstance(stdout, io.TextIOWrapper):
            # Model output is UTF-8; a Windows console or pipe may default to another code page.
            with contextlib.suppress(ValueError, OSError):
                stdout.reconfigure(encoding="utf-8")
        stdout.write(report)
        stdout.flush()

    if run.aborted is not None:
        return fail(f"stopped early: {run.aborted.describe()}", 1)
    if run.interrupted:
        return fail("interrupted; the report is partial", 130)
    return 0


if __name__ == "__main__":
    sys.exit(main())
