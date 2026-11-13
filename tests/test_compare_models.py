"""Unit tests for tools/compare_models.py. No network access beyond an in-process server."""

from __future__ import annotations

import csv
import email.utils
import io
import json
import socket
import tempfile
import threading
import unittest
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import compare_models as cm

# A stream in the documented shape: a queue comment, reasoning, a keep-alive, answer
# deltas, the finish chunk, the usage chunk with empty choices, then [DONE].
SAMPLE_STREAM = """\
: queued · position 2 of 3 · waiting 4s

data: {"id":"c1","object":"chat.completion.chunk","model":"m","choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}]}

data: {"id":"c1","object":"chat.completion.chunk","model":"m","choices":[{"index":0,"delta":{"reasoning_content":"Think. "},"finish_reason":null}]}

: ka

data: {"id":"c1","object":"chat.completion.chunk","model":"m","choices":[{"index":0,"delta":{"content":"Hello "},"finish_reason":null}]}

data: {"id":"c1","object":"chat.completion.chunk","model":"m","choices":[{"index":0,"delta":{"content":"world"},"finish_reason":null}]}

data: {"id":"c1","object":"chat.completion.chunk","model":"m","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: {"id":"c1","object":"chat.completion.chunk","model":"m","choices":[],"usage":{"prompt_tokens":7,"completion_tokens":5,"total_tokens":12}}

data: [DONE]

"""


def chunk(delta: dict[str, Any], finish: str | None = None) -> str:
    event = {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    return f"data: {json.dumps(event)}\n\n"


def parse(text: str, **kwargs: Any) -> cm.StreamResult:
    return cm.StreamParser(**kwargs).feed(text.splitlines(keepends=True))


class FakeClock:
    def __init__(self, start: float = 100.0) -> None:
        self.now = start
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


class ParsePromptsTest(unittest.TestCase):
    def test_text_skips_blank_and_comment_lines(self) -> None:
        prompts = cm.parse_prompts(["# header", "", "first", "  second  ", "#note"], "text")
        self.assertEqual([p.id for p in prompts], ["1", "2"])
        self.assertEqual(prompts[1].messages, [{"role": "user", "content": "second"}])

    def test_text_adds_the_system_message(self) -> None:
        (prompt,) = cm.parse_prompts(["hi"], "text", system="Be brief.")
        self.assertEqual(prompt.messages[0], {"role": "system", "content": "Be brief."})
        self.assertEqual(prompt.text, "hi")

    def test_jsonl_prompt_messages_ids_and_system(self) -> None:
        lines = [
            '{"id": "a", "prompt": "one"}',
            '{"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "r"},'
            ' {"role": "user", "content": "two"}]}',
            '{"id": 7, "system": "Own rules.", "prompt": "three"}',
        ]
        prompts = cm.parse_prompts(lines, "jsonl", system="Default rules.")
        self.assertEqual([p.id for p in prompts], ["a", "2", "7"])
        self.assertEqual(prompts[0].messages[0]["content"], "Default rules.")
        self.assertEqual(prompts[1].text, "two")
        self.assertEqual(len(prompts[1].messages), 4)
        self.assertEqual(prompts[2].messages[0]["content"], "Own rules.")

    def test_jsonl_keeps_an_existing_system_message(self) -> None:
        line = '{"messages": [{"role": "system", "content": "Mine."}, {"role": "user", "content": "x"}]}'
        (prompt,) = cm.parse_prompts([line], "jsonl", system="Default.")
        self.assertEqual(prompt.messages[0]["content"], "Mine.")
        self.assertEqual(len(prompt.messages), 2)

    def test_text_of_array_content_uses_text_parts(self) -> None:
        line = json.dumps(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Describe"},
                            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                        ],
                    }
                ]
            }
        )
        (prompt,) = cm.parse_prompts([line], "jsonl")
        self.assertEqual(prompt.text, "Describe")

    def test_jsonl_errors_name_the_line(self) -> None:
        cases = {
            "not json": "not valid JSON",
            "[1, 2]": "JSON object",
            '{"id": "x"}': "'prompt'",
            '{"prompt": "   "}': "'prompt'",
            '{"messages": []}': "non-empty list",
            '{"messages": [{"role": "robot", "content": "x"}]}': "role",
            '{"prompt": "x", "id": true}': "'id'",
            '{"prompt": "x", "system": 5}': "'system'",
        }
        for line, expected in cases.items():
            with self.subTest(line=line), self.assertRaises(cm.InputError) as caught:
                cm.parse_prompts(["", line], "jsonl", source="p.jsonl")
            self.assertIn("p.jsonl:2", str(caught.exception))
            self.assertIn(expected, str(caught.exception))

    def test_load_prompts_follows_the_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            text = Path(tmp, "p.txt")
            text.write_text('{"prompt": "literal line"}\n', encoding="utf-8")
            jsonl = Path(tmp, "p.jsonl")
            jsonl.write_text('{"prompt": "parsed"}\n', encoding="utf-8")
            empty = Path(tmp, "empty.txt")
            empty.write_text("# nothing\n\n", encoding="utf-8")
            self.assertEqual(cm.load_prompts(text)[0].text, '{"prompt": "literal line"}')
            self.assertEqual(cm.load_prompts(jsonl)[0].text, "parsed")
            self.assertEqual(cm.load_prompts(text, fmt="jsonl")[0].text, "literal line")
            with self.assertRaises(cm.InputError):
                cm.load_prompts(empty)
            with self.assertRaises(cm.InputError):
                cm.load_prompts(Path(tmp, "missing.txt"))


class StreamParserTest(unittest.TestCase):
    def test_documented_stream(self) -> None:
        comments: list[str] = []
        result = parse(SAMPLE_STREAM, on_comment=comments.append)
        self.assertEqual(result.content, "Hello world")
        self.assertEqual(result.reasoning, "Think. ")
        self.assertEqual(result.finish_reason, "stop")
        self.assertEqual(result.usage, {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12})
        self.assertTrue(result.done)
        self.assertEqual(comments, ["queued · position 2 of 3 · waiting 4s", "ka"])

    def test_crlf_lines_and_data_without_a_space(self) -> None:
        text = 'data:{"choices":[{"index":0,"delta":{"content":"x"},"finish_reason":"stop"}]}\r\n\r\ndata: [DONE]\r\n\r\n'
        result = parse(text)
        self.assertEqual(result.content, "x")
        self.assertTrue(result.done)

    def test_multi_line_data_is_joined(self) -> None:
        text = 'data: {"choices": [{"index": 0,\ndata: "delta": {"content": "joined"}}]}\n\n'
        self.assertEqual(parse(text).content, "joined")

    def test_tool_call_fragments_accumulate_by_index(self) -> None:
        text = (
            chunk(
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "f", "arguments": '{"a"'},
                        }
                    ]
                }
            )
            + chunk({"tool_calls": [{"index": 0, "function": {"arguments": ": 1}"}}]})
            + chunk(
                {"tool_calls": [{"index": 1, "id": "call_2", "function": {"name": "g", "arguments": "{}"}}]}
            )
            + chunk({}, "tool_calls")
            + "data: [DONE]\n\n"
        )
        result = parse(text)
        self.assertEqual(result.finish_reason, "tool_calls")
        self.assertEqual([c["function"]["name"] for c in result.tool_calls], ["f", "g"])
        self.assertEqual(json.loads(result.tool_calls[0]["function"]["arguments"]), {"a": 1})
        self.assertEqual(result.tool_calls[1]["id"], "call_2")

    def test_whole_tool_call_in_one_chunk(self) -> None:
        call = {
            "index": 0,
            "id": "call_mock_1",
            "type": "function",
            "function": {"name": "f", "arguments": '{"x": 1}'},
        }
        result = parse(chunk({"tool_calls": [call]}, "tool_calls") + "data: [DONE]\n\n")
        self.assertEqual(result.tool_calls[0]["function"]["arguments"], '{"x": 1}')

    def test_error_event_raises_in_stream_error(self) -> None:
        text = (
            chunk({"content": "partial"})
            + 'data: {"error":{"type":"upstream_timeout","message":"Server busy or request took too long.","elapsed_s":181.2}}\n\n'
            + "data: [DONE]\n\n"
        )
        with self.assertRaises(cm.ApiError) as caught:
            parse(text)
        err = caught.exception
        self.assertTrue(err.in_stream)
        self.assertEqual(err.error_type, "upstream_timeout")
        self.assertEqual(err.body["elapsed_s"], 181.2)
        self.assertIs(cm.classify(err), cm.Action.RETRY)

    def test_non_json_data_raises(self) -> None:
        with self.assertRaises(cm.ApiError) as caught:
            parse("data: not json\n\n")
        self.assertEqual(caught.exception.error_type, "invalid_stream")
        self.assertIs(cm.classify(caught.exception), cm.Action.FAIL)

    def test_events_after_done_are_ignored(self) -> None:
        parser = cm.StreamParser()
        for line in ["data: [DONE]", "", 'data: {"error": {"type": "late"}}', ""]:
            parser.feed_line(line)
        self.assertTrue(parser.close().done)

    def test_timings_come_from_the_clock(self) -> None:
        clock = FakeClock()
        parser = cm.StreamParser(clock=clock)
        clock.now += 2.0
        parser.feed_line(": ka")
        clock.now += 1.5
        for line in chunk({"reasoning_content": "r"}).splitlines():
            parser.feed_line(line)
        clock.now += 4.0
        result = parser.close()
        self.assertEqual(result.first_output_s, 3.5)
        self.assertEqual(result.latency_s, 7.5)


class ErrorTest(unittest.TestCase):
    def test_gateway_error_object(self) -> None:
        body = {
            "error": {
                "type": "quota_exceeded",
                "message": "Monthly token cap reached.",
                "plan": "pro",
                "resets_at": "2026-12-06T10:00:00+00:00",
            }
        }
        err = cm.parse_error_body(429, json.dumps(body).encode())
        self.assertEqual(err.error_type, "quota_exceeded")
        self.assertEqual(err.body["plan"], "pro")
        self.assertIn("resets at 2026-12-06T10:00:00+00:00", err.describe())
        self.assertIs(cm.classify(err), cm.Action.ABORT)

    def test_validation_error(self) -> None:
        body = {
            "message": "The selected model is invalid.",
            "errors": {"model": ["The selected model is invalid."]},
        }
        err = cm.parse_error_body(422, json.dumps(body).encode())
        self.assertEqual(err.error_type, "validation_error")
        self.assertIs(cm.classify(err), cm.Action.SKIP_MODEL)
        other = cm.parse_error_body(422, b'{"message": "Bad.", "errors": {"messages": ["Required."]}}')
        self.assertIs(cm.classify(other), cm.Action.FAIL)

    def test_bare_message_shapes(self) -> None:
        unauthenticated = cm.parse_error_body(401, b'{"message":"Unauthenticated."}')
        self.assertIsNone(unauthenticated.error_type)
        self.assertEqual(unauthenticated.message, "Unauthenticated.")
        self.assertIs(cm.classify(unauthenticated), cm.Action.ABORT)
        unverified = cm.parse_error_body(403, b'{"message":"Verify your email.","code":"email_unverified"}')
        self.assertEqual(unverified.error_type, "email_unverified")
        limited = cm.parse_error_body(429, b'{"message":"Too Many Attempts."}', retry_after="3")
        self.assertEqual(limited.retry_after, 3.0)
        self.assertIs(cm.classify(limited), cm.Action.WAIT)

    def test_non_json_body(self) -> None:
        err = cm.parse_error_body(524, b"<html><body><h1>A timeout occurred</h1></body></html>")
        self.assertIsNone(err.error_type)
        self.assertIn("non-JSON", err.message)
        self.assertIn("A timeout occurred", err.message)
        self.assertIs(cm.classify(err), cm.Action.RETRY)

    def test_parse_retry_after(self) -> None:
        self.assertEqual(cm.parse_retry_after("12"), 12.0)
        self.assertEqual(cm.parse_retry_after("-4"), 0.0)
        self.assertIsNone(cm.parse_retry_after(None))
        self.assertIsNone(cm.parse_retry_after("soon"))
        now = 1_794_000_000.0
        date = "Fri, 13 Nov 2026 10:00:30 GMT"
        expected = email.utils.parsedate_to_datetime(date).timestamp() - now
        self.assertAlmostEqual(cm.parse_retry_after(date, now=now) or 0.0, expected)

    def test_classify_table(self) -> None:
        def err(
            status: int | None, kind: str | None = None, body: dict[str, Any] | None = None
        ) -> cm.ApiError:
            return cm.ApiError("x", status=status, error_type=kind, body=body)

        stream = cm.ApiError
        cases = [
            (err(None, "connection_error"), cm.Action.RETRY),
            (err(402, "no_active_plan"), cm.Action.ABORT),
            (err(403, "email_unverified"), cm.Action.ABORT),
            (err(404), cm.Action.SKIP_MODEL),
            (err(413, "context_length_exceeded"), cm.Action.FAIL),
            (err(429, "session_quota_exceeded"), cm.Action.ABORT),
            (err(429), cm.Action.WAIT),
            (err(502, "upstream_unreachable"), cm.Action.RETRY),
            (err(502, "no_usage_accounting"), cm.Action.RETRY),
            (err(503, "server_busy"), cm.Action.RETRY),
            (err(503, "model_unavailable", {"model": "m"}), cm.Action.SKIP_MODEL),
            (err(504, "upstream_timeout"), cm.Action.RETRY),
            (err(500, "upstream_error", {"status": 500}), cm.Action.RETRY),
            (err(400, "upstream_error", {"status": 400}), cm.Action.FAIL),
            (stream("x", status=200, error_type="preempted", in_stream=True), cm.Action.RETRY),
            (stream("x", status=200, error_type="server_busy", in_stream=True), cm.Action.RETRY),
            (
                stream("x", status=200, error_type="upstream_error", body={"status": 502}, in_stream=True),
                cm.Action.RETRY,
            ),
            (
                stream("x", status=200, error_type="upstream_error", body={"status": 400}, in_stream=True),
                cm.Action.FAIL,
            ),
        ]
        for error, action in cases:
            with self.subTest(status=error.status, kind=error.error_type, in_stream=error.in_stream):
                self.assertIs(cm.classify(error), action)

    def test_backoff_grows_is_capped_and_waits_longer_after_preemption(self) -> None:
        plain = cm.ApiError("x", status=502)
        delays = [cm.backoff_delay(n, plain, 1.0, rng=lambda: 0.0) for n in range(7)]
        self.assertEqual(delays[:4], [1.0, 2.0, 4.0, 8.0])
        self.assertEqual(delays[-1], cm.BACKOFF_CAP)
        self.assertEqual(cm.backoff_delay(0, plain, 1.0, rng=lambda: 0.5), 1.5)
        preempted = cm.ApiError("x", status=200, error_type="preempted", in_stream=True)
        self.assertGreaterEqual(cm.backoff_delay(0, preempted, 1.0, rng=lambda: 0.0), 60.0)
        self.assertEqual(cm.backoff_delay(0, preempted, 0.0, rng=lambda: 0.0), 0.0)


class PacerTest(unittest.TestCase):
    def test_spaces_request_starts(self) -> None:
        clock = FakeClock()
        pacer = cm.Pacer(60, clock=clock, sleep=clock.sleep)
        pacer.wait()
        pacer.wait()
        clock.now += 0.25
        pacer.wait()
        clock.now += 5.0
        pacer.wait()
        self.assertEqual(clock.slept, [1.0, 0.75])

    def test_rejects_a_non_positive_rate(self) -> None:
        with self.assertRaises(ValueError):
            cm.Pacer(0)


PROMPT = cm.Prompt("1", [{"role": "user", "content": "Say hi | now"}])


class RowAndOutputTest(unittest.TestCase):
    def test_cap_notice_is_removed_and_flagged(self) -> None:
        result = cm.StreamResult(content="Partial answer" + cm.CAP_NOTICE, finish_reason="length")
        row = cm.row_from_result(PROMPT, "m", result, attempts=1)
        self.assertTrue(row.capped)
        self.assertEqual(row.answer, "Partial answer")

    def test_inline_reasoning_is_moved_out_of_the_answer(self) -> None:
        result = cm.StreamResult(content="<think>plan</think>\n\nAnswer", usage={"total_tokens": 9})
        row = cm.row_from_result(PROMPT, "m", result, attempts=1)
        self.assertEqual(row.answer, "Answer")
        self.assertEqual(row.reasoning_chars, 4)
        self.assertEqual(row.total_tokens, 9)

    def test_excerpt(self) -> None:
        self.assertEqual(cm.excerpt("a\n\n  b\tc", 0), "a b c")
        self.assertEqual(cm.excerpt("abcdefghij", 8), "abcde...")
        self.assertEqual(cm.excerpt("short", 8), "short")

    def test_md_cell_escapes(self) -> None:
        self.assertEqual(cm.md_cell("a|b\n<think> & c\\d"), "a\\|b &lt;think&gt; &amp; c\\\\d")

    def _run(self) -> cm.RunResult:
        good = cm.row_from_result(
            PROMPT,
            "model-a",
            cm.StreamResult(
                content="Hi | there",
                reasoning="r" * 10,
                finish_reason="stop",
                usage={"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
                latency_s=1.234,
                first_output_s=0.5,
            ),
            attempts=2,
        )
        bad = cm.error_row(
            PROMPT, "model-b", cm.ApiError("No server.", status=503, error_type="model_unavailable"), 1
        )
        return cm.RunResult([good, bad])

    def test_render_markdown(self) -> None:
        info = cm.RunInfo(
            base_url="http://127.0.0.1:4010/api/v1",
            models=["model-a", "model-b"],
            source="tools\\prompts.txt",
            prompt_count=1,
            started=datetime(2026, 11, 13, 9, 30, tzinfo=timezone.utc),
        )
        text = cm.render_markdown(self._run(), info)
        self.assertIn("- Started: 2026-11-13 09:30 UTC", text)
        self.assertIn("from `tools/prompts.txt`", text)
        self.assertIn("| `model-a` | 1 | 0 | 1.23 | 0.50 | 7 | stop 1 |", text)
        self.assertIn("| `model-b` | 0 | 1 |", text)
        self.assertIn("> Say hi \\| now", text)
        self.assertIn(
            "| `model-a` | stop | 1.23 | 0.50 | 3 | 4 | 7 | reasoning: 10 chars; 2 attempts | Hi \\| there |",
            text,
        )
        self.assertIn("**Error:** 503 model_unavailable: No server.", text)
        self.assertNotIn("stopped early", text)
        aborted = cm.RunResult([], aborted=cm.ApiError("No plan.", status=402, error_type="no_active_plan"))
        self.assertIn(
            "The run stopped early:** 402 no_active_plan: No plan.", cm.render_markdown(aborted, info)
        )

    def test_render_csv(self) -> None:
        rows = list(csv.reader(io.StringIO(cm.render_csv(self._run()))))
        self.assertEqual(rows[0], cm.CSV_COLUMNS)
        first = dict(zip(rows[0], rows[1], strict=True))
        self.assertEqual(first["answer"], "Hi | there")
        self.assertEqual(first["total_tokens"], "7")
        self.assertEqual(first["latency_s"], "1.234")
        second = dict(zip(rows[0], rows[2], strict=True))
        self.assertEqual(second["error_status"], "503")
        self.assertEqual(second["error_type"], "model_unavailable")


class FakeStreamer:
    """Plays back a list of outcomes per model: a StreamResult or an ApiError to raise."""

    def __init__(self, outcomes: dict[str, list[cm.StreamResult | cm.ApiError]]) -> None:
        self.outcomes = outcomes
        self.calls: list[str] = []

    def stream_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        top_p: float | None = None,
        on_comment: Callable[[str], None] | None = None,
    ) -> cm.StreamResult:
        self.calls.append(model)
        outcome = self.outcomes[model].pop(0)
        if isinstance(outcome, cm.ApiError):
            raise outcome
        return outcome


def ok(text: str = "fine") -> cm.StreamResult:
    return cm.StreamResult(content=text, finish_reason="stop", usage={"total_tokens": 3}, done=True)


class RunnerTest(unittest.TestCase):
    def run_with(
        self, streamer: FakeStreamer, models: list[str], prompts: int = 1, retries: int = 2
    ) -> tuple[cm.RunResult, FakeClock]:
        clock = FakeClock()
        run = cm.run_comparison(
            streamer,
            [cm.Prompt(str(n), [{"role": "user", "content": f"p{n}"}]) for n in range(1, prompts + 1)],
            models,
            pacer=cm.Pacer(60, clock=clock, sleep=lambda _s: None),
            retries=retries,
            sleep=clock.sleep,
            rng=lambda: 0.0,
        )
        return run, clock

    def test_transient_error_is_retried(self) -> None:
        streamer = FakeStreamer({"a": [cm.ApiError("busy", status=503, error_type="server_busy"), ok()]})
        run, clock = self.run_with(streamer, ["a"])
        self.assertTrue(run.rows[0].ok)
        self.assertEqual(run.rows[0].attempts, 2)
        self.assertEqual(clock.slept, [1.0])

    def test_retries_run_out(self) -> None:
        timeout = cm.ApiError("slow", status=200, error_type="upstream_timeout", in_stream=True)
        streamer = FakeStreamer({"a": [timeout, timeout]})
        run, _ = self.run_with(streamer, ["a"], retries=1)
        self.assertEqual(run.rows[0].error_type, "upstream_timeout")
        self.assertEqual(run.rows[0].attempts, 2)
        self.assertIsNone(run.aborted)

    def test_rate_limit_waits_for_retry_after_with_a_cap(self) -> None:
        limited = cm.ApiError("Too Many Attempts.", status=429, retry_after=500.0)
        streamer = FakeStreamer({"a": [limited, cm.ApiError("x", status=429, retry_after=2.0), ok()]})
        run, clock = self.run_with(streamer, ["a"], retries=0)
        self.assertTrue(run.rows[0].ok)
        self.assertEqual(clock.slept, [cm.MAX_RATE_LIMIT_WAIT, 2.0])

    def test_context_error_is_recorded_without_retry(self) -> None:
        too_big = cm.ApiError("Too big.", status=413, error_type="context_length_exceeded")
        streamer = FakeStreamer({"a": [too_big, ok()]})
        run, _ = self.run_with(streamer, ["a"], prompts=2)
        self.assertEqual(run.rows[0].error_type, "context_length_exceeded")
        self.assertTrue(run.rows[1].ok)
        self.assertEqual(streamer.calls, ["a", "a"])

    def test_unavailable_model_is_skipped_for_later_prompts(self) -> None:
        missing = cm.ApiError("No server.", status=503, error_type="model_unavailable")
        streamer = FakeStreamer({"a": [missing], "b": [ok(), ok()]})
        run, _ = self.run_with(streamer, ["a", "b"], prompts=2)
        self.assertEqual(streamer.calls, ["a", "b", "b"])
        self.assertEqual([r.error_type for r in run.rows], ["model_unavailable", None, "skipped", None])
        self.assertEqual(run.rows[2].error, "skipped: model_unavailable")

    def test_quota_error_stops_the_run(self) -> None:
        quota = cm.ApiError(
            "Cap reached.",
            status=429,
            error_type="quota_exceeded",
            body={"resets_at": "2026-12-01T00:00:00Z"},
        )
        streamer = FakeStreamer({"a": [quota], "b": [ok()]})
        run, _ = self.run_with(streamer, ["a", "b"], prompts=2)
        self.assertEqual(streamer.calls, ["a"])
        self.assertIsNotNone(run.aborted)
        assert run.aborted is not None
        self.assertIn("resets at 2026-12-01T00:00:00Z", run.aborted.describe())


@contextmanager
def fake_api(
    handle: Callable[[str, str, dict[str, Any] | None], tuple[int, dict[str, str], bytes]],
) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """Serve `handle(method, path, json_body) -> (status, headers, body)` on a free local port."""
    seen: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def _serve(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            body = json.loads(raw) if raw else None
            seen.append(
                {
                    "method": self.command,
                    "path": self.path,
                    "body": body,
                    "auth": self.headers.get("Authorization"),
                }
            )
            status, headers, payload = handle(self.command, self.path, body)
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = _serve
        do_POST = _serve

        def log_message(self, format: str, *args: Any) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/api/v1", seen
    finally:
        server.shutdown()
        server.server_close()


SSE = {"Content-Type": "text/event-stream"}
JSON = {"Content-Type": "application/json"}
MODELS = {
    "object": "list",
    "data": [
        {"id": "model-a", "object": "model", "available": True, "name": "Model A"},
        {"id": "model-b", "object": "model", "available": False, "name": "Model B"},
        {"id": "model-c", "object": "model"},
    ],
}


def standard_api(method: str, path: str, body: dict[str, Any] | None) -> tuple[int, dict[str, str], bytes]:
    if path.endswith("/models"):
        return 200, JSON, json.dumps(MODELS).encode()
    assert body is not None
    if "limit me" in json.dumps(body):
        return 429, {**JSON, "Retry-After": "7"}, b'{"message":"Too Many Attempts."}'
    if "plain json" in json.dumps(body):
        completion = {
            "choices": [
                {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "whole"}}
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        return 200, JSON, json.dumps(completion).encode()
    if "cut short" in json.dumps(body):
        return 200, SSE, chunk({"content": "half"}).encode()
    return 200, SSE, SAMPLE_STREAM.encode()


class ClientTest(unittest.TestCase):
    def test_streams_and_sends_the_expected_request(self) -> None:
        with fake_api(standard_api) as (base, seen):
            client = cm.Client(base, "test-key", timeout=5)
            result = client.stream_chat("model-a", [{"role": "user", "content": "hi"}], temperature=0.2)
        self.assertEqual(result.content, "Hello world")
        self.assertEqual(result.usage, {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12})
        request = seen[0]
        self.assertEqual(request["path"], "/api/v1/chat/completions")
        self.assertEqual(request["auth"], "Bearer test-key")
        self.assertEqual(request["body"]["stream"], True)
        self.assertEqual(request["body"]["temperature"], 0.2)
        self.assertNotIn("top_p", request["body"])

    def test_http_error_carries_retry_after(self) -> None:
        with fake_api(standard_api) as (base, _), self.assertRaises(cm.ApiError) as caught:
            cm.Client(base, "k", timeout=5).stream_chat("model-a", [{"role": "user", "content": "limit me"}])
        self.assertEqual(caught.exception.status, 429)
        self.assertEqual(caught.exception.retry_after, 7.0)

    def test_a_server_that_ignores_stream_still_works(self) -> None:
        with fake_api(standard_api) as (base, _):
            result = cm.Client(base, "k", timeout=5).stream_chat(
                "model-a", [{"role": "user", "content": "plain json"}]
            )
        self.assertEqual(result.content, "whole")
        self.assertEqual(result.usage, {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})

    def test_a_stream_cut_short_is_retryable(self) -> None:
        with fake_api(standard_api) as (base, _), self.assertRaises(cm.ApiError) as caught:
            cm.Client(base, "k", timeout=5).stream_chat("model-a", [{"role": "user", "content": "cut short"}])
        self.assertEqual(caught.exception.error_type, "incomplete_stream")
        self.assertIs(cm.classify(caught.exception), cm.Action.RETRY)

    def test_connection_refused(self) -> None:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        with self.assertRaises(cm.ApiError) as caught:
            cm.Client(f"http://127.0.0.1:{port}/api/v1", "k", timeout=5).list_models()
        self.assertIsNone(caught.exception.status)
        self.assertEqual(caught.exception.error_type, "connection_error")

    def test_list_models(self) -> None:
        with fake_api(standard_api) as (base, seen):
            models = cm.Client(base + "/", "k", timeout=5).list_models()
        self.assertEqual([m["id"] for m in models], ["model-a", "model-b", "model-c"])
        self.assertEqual(seen[0]["path"], "/api/v1/models")


class MainTest(unittest.TestCase):
    def main(self, argv: list[str], base: str, key: str = "test-key") -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        code = cm.main(
            argv,
            env={"MOLOCHAI_API_KEY": key, "MOLOCHAI_BASE_URL": base},
            stdout=stdout,
            stderr=stderr,
            sleep=lambda _s: None,
        )
        return code, stdout.getvalue(), stderr.getvalue()

    def test_markdown_report_for_available_models(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, fake_api(standard_api) as (base, seen):
            prompts = Path(tmp, "p.txt")
            prompts.write_text("first\nsecond\n", encoding="utf-8")
            code, out, err = self.main([str(prompts)], base)
        self.assertEqual(code, 0, err)
        self.assertIn("models from GET /models: model-a, model-c", err)
        posted = [r["body"]["model"] for r in seen if r["method"] == "POST"]
        self.assertEqual(posted, ["model-a", "model-c", "model-a", "model-c"])
        self.assertIn("# Model comparison", out)
        self.assertIn("| `model-a` | 2 | 0 |", out)
        self.assertIn("Hello world", out)

    def test_csv_report_to_a_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, fake_api(standard_api) as (base, _):
            prompts = Path(tmp, "p.jsonl")
            prompts.write_text('{"id": "x", "prompt": "hi"}\n', encoding="utf-8")
            output = Path(tmp, "out.csv")
            code, out, err = self.main([str(prompts), "-m", "model-a,model-b", "-o", str(output), "-q"], base)
            rows = list(csv.DictReader(output.open(encoding="utf-8")))
        self.assertEqual((code, out, err), (0, "", ""))
        self.assertEqual(
            [(r["prompt_id"], r["model"], r["answer"]) for r in rows],
            [("x", "model-a", "Hello world"), ("x", "model-b", "Hello world")],
        )

    def test_list_models(self) -> None:
        with fake_api(standard_api) as (base, _):
            code, out, _ = self.main(["--list-models"], base)
        self.assertEqual(code, 0)
        self.assertEqual(
            out.splitlines(), ["model-a\tavailable\tModel A", "model-b\tunavailable\tModel B", "model-c"]
        )

    def test_billing_error_stops_with_status_1(self) -> None:
        def no_plan(method: str, path: str, body: dict[str, Any] | None) -> tuple[int, dict[str, str], bytes]:
            payload = {"error": {"type": "no_active_plan", "message": "No active plan.", "plan": None}}
            return 402, JSON, json.dumps(payload).encode()

        with tempfile.TemporaryDirectory() as tmp, fake_api(no_plan) as (base, seen):
            prompts = Path(tmp, "p.txt")
            prompts.write_text("a\nb\n", encoding="utf-8")
            code, out, err = self.main([str(prompts), "-m", "model-a"], base)
            listing, _, list_err = self.main([str(prompts)], base)
        self.assertEqual(code, 1)
        self.assertEqual(len([r for r in seen if r["method"] == "POST"]), 1)
        self.assertIn("The run stopped early:** 402 no_active_plan", out)
        self.assertIn("stopped early: 402 no_active_plan", err)
        self.assertEqual(listing, 1)
        self.assertIn("GET /models failed: 402 no_active_plan", list_err)

    def test_usage_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prompts = Path(tmp, "p.txt")
            prompts.write_text("a\n", encoding="utf-8")
            cases = [
                ([str(prompts)], "", "MOLOCHAI_API_KEY is not set"),
                ([str(prompts), "--rpm", "120"], "k", "--rpm"),
                ([str(prompts), "--temperature", "3"], "k", "--temperature"),
                ([str(Path(tmp, "missing.txt"))], "k", "cannot read"),
                ([], "k", "prompt file is required"),
            ]
            for argv, key, message in cases:
                with self.subTest(argv=argv):
                    code, _, err = self.main(argv, "http://127.0.0.1:9/api/v1", key=key)
                    self.assertEqual(code, 2)
                    self.assertIn(message, err)
        code, _, err = self.main(["x.txt"], "ftp://example", key="k")
        self.assertEqual(code, 2)
        self.assertIn("http:// or https://", err)


if __name__ == "__main__":
    unittest.main()
