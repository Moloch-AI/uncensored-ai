# compare_models.py

Send the same prompts to several models on any OpenAI-compatible endpoint and get one table back: finish reason, latency, time to first output, token usage and an excerpt of each answer. It exists for the advice the [models guide](../docs/models.md#testing-a-model-on-your-own-prompts) gives: compare models on your own prompts, not on someone else's scores.

- Standard library only, Python 3.10 or later. Nothing to install.
- Streams every request, so long replies do not hit the edge timeout of about 100 seconds that non-streamed requests can.
- Sends one request at a time, paced under the API's 60 requests per minute (50 by default, leaving room for anything else on the account).
- Handles the API's error shapes: retries transient errors with backoff and jitter, waits `Retry-After` on the per-minute rate limit, skips a model that answers `model_unavailable` or is unknown, records a `413` for that prompt, and stops the run on errors that affect every request (`401`, `402`, `403`, quota `429`), writing the partial report with `resets_at`.
- Removes the output-cap notice from answers and flags the row, moves an inline `<think>` block out of the answer, and counts reasoning separately.

## Usage

```bash
export MOLOCHAI_API_KEY=your-api-key
python tools/compare_models.py --list-models
python tools/compare_models.py tools/prompts.example.txt --output results.md
python tools/compare_models.py tools/prompts.example.jsonl \
  --models glm-5.3-flash,llama-3.3-70b-instruct-abliterated --output results.csv
```

Without `--models`, the tool asks `GET /models` and compares every model listed as available. Progress goes to stderr; the report goes to `--output` or stdout. The format follows the output extension (`.csv` for CSV, Markdown otherwise) unless `--format` says otherwise.

To try it without an account, run the [mock server](../docs/setup.md#developing-offline-against-the-mock-server) and set `MOLOCHAI_BASE_URL=http://127.0.0.1:4010/api/v1` and `MOLOCHAI_API_KEY=mock-key`. The mock's replies are canned text, so this shows the tool working, not how models compare.

For a local runtime, set `MOLOCHAI_BASE_URL` (or `--base-url`) to its base, such as `http://localhost:8080/v1`, and the key to any placeholder. The tool sends `stream_options.include_usage`, which servers that follow OpenAI need before they report usage in a stream; MolochAI always reports it and ignores the option.

## Prompt files

**Text (`.txt`):** one prompt per line. Blank lines and lines starting with `#` are skipped. See [prompts.example.txt](prompts.example.txt).

**JSONL (`.jsonl`):** one JSON object per line, with either `prompt` (a string) or `messages` (a list in Chat Completions format, for multi-turn prompts), and optionally `id` and `system`. See [prompts.example.jsonl](prompts.example.jsonl).

```json
{"id": "kill-process", "prompt": "How do I kill a Python process that ignores Ctrl+C?"}
{"id": "scene", "system": "You are a drafting partner for an adult crime novel.", "prompt": "Write the scene."}
```

`--system` adds a system message to every prompt that does not already start with one. A useful file mixes two kinds of prompts: requests that are harmless but sound alarming (the kind [XSTest](https://arxiv.org/abs/2308.01263) collects), and real requests from your product.

## Options

| Option | Default | Meaning |
| --- | --- | --- |
| `prompts` | | The prompt file. |
| `-m`, `--models` | every available model | Model ids, comma-separated or repeated. |
| `-o`, `--output` | stdout | Where to write the report. |
| `-f`, `--format` | from the output extension | `markdown` or `csv`. |
| `--input-format` | from the input extension | `text` or `jsonl`. |
| `--system` | | System message for prompts that do not start with one. |
| `--temperature`, `--top-p` | the model's defaults | Sampling, 0 to 2 and 0 to 1. |
| `--rpm` | 50 | Requests per minute to stay under, at most 60. |
| `--retries` | 2 | Retries per request for transient errors. |
| `--backoff` | 1 | Base backoff in seconds. `preempted` waits 60 times this. |
| `--timeout` | 120 | Seconds without data before a connection is given up. |
| `--excerpt-chars` | 160 | Answer characters per row; 0 keeps the whole answer. |
| `--base-url` | `MOLOCHAI_BASE_URL` | API base URL. |
| `--list-models` | | Print the endpoint's models and exit. |
| `-q`, `--quiet` | | No progress on stderr. |

| Environment variable | Required | Default |
| --- | --- | --- |
| `MOLOCHAI_API_KEY` | Yes | |
| `MOLOCHAI_BASE_URL` | No | `https://api.molochai.dev/api/v1` |

Exit status: 0 when every request was attempted (rows can still hold errors), 1 when the run stopped on an error that affects every request, 2 for a usage or input error, 130 when interrupted (the partial report is still written).

## Reading the report

The Markdown report has a summary per model (replies, errors, median latency, median time to first output, total tokens, finish reasons) and a table per prompt. The CSV has one row per prompt and model, with the full error and, with `--excerpt-chars 0`, the full answer.

- Every number is a single sample on a shared service. Latency includes queueing, and reasoning models spend time and tokens before the answer starts. Do not read small differences as rankings.
- `length` with "output cap reached" means the reply hit the plan's cap; the notice text was removed from the answer.
- Token figures come from the API's `usage`; the total includes reasoning.
- A string match does not tell you whether a reply declined, and excerpts do not tell you whether it was right. Read the replies, then judge quality with your own rubric.

## Tests

```bash
python -m pytest
MOLOCHAI_MOCK_BASE_URL=http://127.0.0.1:4010/api/v1 python -m pytest tests/test_integration_mock.py
```

The unit tests use an in-process HTTP server. The integration tests run against the mock server and are skipped unless `MOLOCHAI_MOCK_BASE_URL` is set.
