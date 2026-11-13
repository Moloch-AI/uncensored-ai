# Troubleshooting

Symptom, likely cause, fix. Start with the HTTP status if you have one: the [status reference](#http-status-reference) at the end maps every status and error type to what to do. Error bodies come in three shapes and are sometimes not JSON at all, so read the status first and the `type` field second ([building applications](building-applications.md#errors-retries-and-rate-limits)).

- [Connecting and authentication](#connecting-and-authentication)
- [Models](#models)
- [Limits and quotas](#limits-and-quotas)
- [Streaming and timeouts](#streaming-and-timeouts)
- [Output](#output)
- [Tool calling](#tool-calling)
- [Retries](#retries)
- [Tools and front-ends](#tools-and-front-ends)
- [Local runtimes](#local-runtimes)
- [HTTP status reference](#http-status-reference)
- [Getting help](#getting-help)

## Connecting and authentication

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `401` `{"message":"Unauthenticated."}` | The key is missing, mistyped or revoked, or the header is not `Authorization: Bearer <key>`. | Check the header and the variable it reads. Create a new key under [Account → API keys](https://dash.molochai.dev/account?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) if needed. |
| `402` `no_active_plan`, on every request including `GET /models` | The key works, but the account has no active plan and no credit: never bought, expired or used up. | Add credit or buy a plan in the dashboard under Billing. A new key does not help. |
| `403` with `"code": "email_unverified"` | The account's email address is not confirmed. | Follow the link in the confirmation email, or resend it from the dashboard. |
| The OpenAI SDK fails before sending anything, asking for an API key | `MOLOCHAI_API_KEY` is empty or not exported in the shell that runs the code. | `echo` the variable in the same shell; on Windows, set it with `$env:` in PowerShell or `setx` and a new terminal. |
| `404` | The path is wrong: `/chat/completions` added twice, or `/api/v1` missing. | The base URL is exactly `https://api.molochai.dev/api/v1`. Tools and SDKs append `/chat/completions` themselves. |
| `404` on `/api/v1/auth/me` | `/auth/me` is outside `/api/v1`. | Use `https://api.molochai.dev/api/auth/me`: replace the trailing `/v1` of the base URL with `/auth/me`. |

## Models

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `422` "The selected model is invalid." | The model id is not one the API serves: an OpenAI model name, a typo, a tool's default, an old preset, or a prefix a front-end added. | Use an id from `GET /models`. In Open WebUI, clear the connection's Prefix ID. |
| `503` `model_unavailable` for one model while others work | No server is serving that model right now. The request was not sent to another model. | Retry later, or pick another model ([fallback example](building-applications.md#choosing-a-fallback-model)). `GET /models` shows `available` for each id. |
| A front-end's model dropdown stays empty | The model-list request failed (often `402`), or the tool does not fetch lists. | Fix the account, or type an id by hand. |
| An image seems to be ignored | The model does not take images per its card, or the serving server does not have vision enabled. | Use a model whose card lists image input and test once ([models](models.md#choosing-a-model)). |
| Video does not work | Video input through this API is not documented. | Send frames as images, or do not plan on video. |
| Behavior changed with no change on your side | There is no version pinning: the build behind an id can change. | Keep your own tests for behavior you depend on and rerun them. |

## Limits and quotas

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `429` `{"message":"Too Many Attempts."}` with `Retry-After` | More than 60 requests in a minute on the account (all keys count together). | Wait `Retry-After` seconds. Pace below the limit using `X-RateLimit-Remaining`. Agents and shared front-ends reach this first. |
| `429` `session_quota_exceeded` | The token cap for the current 5-hour session is used. The session started at your first request. Credit does not lift it. | Wait until `resets_at`. Spread large batch jobs over several sessions. |
| `429` `quota_exceeded` | The plan's quota is used and the account has no credit. If the body has `weekly_used` and `weekly_cap`, a whole quota was used within one calendar week. | Wait until `resets_at`, add credit, or move to a larger plan. Do not auto-retry. |
| `413` `context_length_exceeded` | The prompt is larger than your context window. `bound_by: plan` means a larger plan would help; `server` means the serving server is the limit. | Trim or summarize older turns and resend. Keep a budget under `context_limit` from `/api/auth/me`. |
| Long chats start failing all at once while short ones still work | The conversation outgrew the context window, often because a tool's context setting is above your limit. | Lower the tool's context size to about 10% under your limit, or start a new conversation. |
| Kept reasoning makes `413` arrive sooner | `reasoning_content` you send back uses context. | Drop it from older turns, or when switching to a model with reasoning off. |

## Streaming and timeouts

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `524` with an HTML body | A non-streamed request ran past Cloudflare's limit of about 100 seconds. | Stream. Do not parse error bodies as JSON without checking. |
| `504` `upstream_timeout` | The upstream request hit its time limit. | Retry with backoff, and stream. |
| A long pause before the first token | The model is reasoning, or the request is queued for a slot. | Stream: you get `: queued · ...` comments and `: ka` keep-alives during the wait. A model with reasoning off starts sooner. |
| Your own SSE parser fails on lines like `: ka` | Lines starting with `:` are comments. | Ignore them, and parse only `data:` lines ([format](building-applications.md#event-format)). |
| `IndexError` or `undefined` on `choices[0]` at the end of a stream | The final event carries `usage` and an empty `choices` array. | Check for empty `choices` before indexing. |
| An exception mid-stream after some text arrived | An error event inside the stream (`server_busy`, `upstream_unreachable`, `upstream_timeout`, `upstream_error`, `preempted`). The HTTP status was already 200. | Discard the partial text and retry with backoff; for `preempted`, retry in a minute. The SDKs raise these as `APIError`. |
| `<think>...</think>` at the start of `content` | A non-streamed reply from a server that leaves reasoning inline. | Stream (the gateway strips inline blocks while streaming), or strip the block yourself ([how](building-applications.md#reasoning-content)). |
| No `reasoning_content` | The model has reasoning off, or the serving server does not separate reasoning. | Treat the field as optional. |

## Output

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Replies are longer than `max_tokens` | `max_tokens` has no effect; the plan's output cap applies. | Ask for the length you want in the prompt. |
| A reply ends with "[Response is too large for your current plan. Try a smaller request.]" and `finish_reason` is `length` | The reply hit the plan's output cap (9,000 tokens; 30,000 on Enterprise+). Reasoning shares that budget. | Strip the notice, and ask for less per request: a section at a time, or a diff instead of a whole file. |
| Stop sequences do not stop anything; `n` returns one choice; `seed` does not reproduce | `stop`, `n` and `seed` are dropped without an error. | Trim in code, send one request per sample, and do not rely on reproducibility. |
| Invalid JSON, or text around the JSON | There is no JSON mode; `response_format` is dropped. | Ask for JSON in the prompt, extract and validate it, retry or fall back ([example](building-applications.md#structured-output-without-a-json-mode)). |
| The model names itself when asked what it is, breaking a persona | The gateway's identity line names the model. | Tell the character how to answer that question in your system message, and test it. |
| The model still declines some requests | Refusal behavior is reduced, not removed. | Rephrase, give the task and its context in the system message, or try another model. Do not use jailbreak-style prompts; they tend to degrade output. |
| Confident answers that are wrong | Refusal reduction does not improve accuracy, and can make a model hedge less. | Verify facts, ask for evidence or verbatim quotes, and keep a person responsible for what you publish. |
| The model does not know recent events | Knowledge cutoffs are unchanged (the Llama 3.3 card gives December 2023). | Put the facts in the prompt. |

## Tool calling

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| The model answers in prose instead of calling a tool | Tool-calling quality varies by model and server, and two of the five cards do not state tool use. | Use a model whose card states tool use, make tool descriptions specific, and test the loop end to end. |
| `arguments` is not valid JSON, or misses required fields | Models can produce malformed arguments. | Validate with `json.loads` and your schema; send the error back as the tool result and let the model correct it. |
| Streamed tool-call arguments arrive all at once | The gateway buffers them and sends one complete chunk. | Nothing to fix. Keep fragment-accumulating code if you also use other providers. |
| `upstream_error` right after adding a system message mid-conversation | Some models' chat templates reject a system message that is not first. | Merge system content into the first message, or use the user role. |
| An agent stalls with `429` | Each agent step is a request; one task can be dozens. | Check that the agent honors `Retry-After`, and slow it down. |

## Retries

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Far more requests than expected after an error | Your retry loop and the SDK's built-in retries multiply. | Set the SDK's `max_retries` to 0 when you retry yourself. |
| Quota `429`s retried a few times before failing | The OpenAI SDKs retry every `429`, including quota errors that will not pass before `resets_at`. | Handle `429` yourself: wait `Retry-After` for the rate limit, surface `resets_at` for quotas. |
| `e.body` has a different structure for different errors | The SDKs unwrap the gateway's `error` object, but validation and bare-message bodies are whole. | Read `type` from either shape ([`error_body`](building-applications.md#context-limits-and-413)). |
| `502` `no_usage_accounting` with a `request_id` | An upstream problem with accounting for the request. | Retry with backoff. Include the `request_id` if you contact support. |

## Tools and front-ends

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Open WebUI's Verify Connection fails | `401`: the key is wrong or revoked. `402`: no plan and no credit. | Fix the key or the account. Saving a connection does not test it; Verify does. |
| Several Open WebUI or LibreChat users hit `429` together | An admin connection or shared key shares one per-minute limit. | Per-user keys (Direct Connections, `apiKey: "user_provided"`) or team seats. |
| SillyTavern works for a while, then every message fails with `413` | The context size setting is above your window. | Set it about 10% under the window. |
| LibreChat: "Missing API Key" for the endpoint | `MOLOCHAI_API_KEY` did not reach the server process. | Check `.env` and restart. In Docker, check that `librechat.yaml` is mounted. |
| Continue: Agent mode is unavailable | Continue cannot tell that the model calls tools. | Add `capabilities: [tool_use]` to the model entry. |
| Aider sessions end in `413` | Aider does not know the model's limits and does not trim. | Set `max_input_tokens` and `max_output_tokens` in `.aider.model.metadata.json`. |
| Document search, autocomplete or image generation fails in a tool | The API has only chat completions and the model list: no embeddings, text completions or image generation. | Use a local engine or another provider for those features. |

More per-tool detail: [setup: existing tools](setup.md#existing-tools) and the [integration guides](https://molochai.dev/integrations?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai).

## Local runtimes

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Connection refused on `localhost` | The server is not running, or listens on another port or interface. | Check the port the runtime reports at startup and use `http://localhost:<port>/v1`. |
| The SDK insists on a key for a local server | The OpenAI SDKs require a value even when the server ignores it. | Pass any placeholder, unless you started the server with `--api-key`. |
| Out of memory at long context | The KV cache grows with context length and concurrent requests. | Lower the context length or parallelism, or use a smaller quantization ([memory](deployment-options.md#memory-for-the-weights)). |
| Tool calls come back as plain text | The runtime is not parsing the model's tool-call format. | Use the chat template and tool-call parser flags the model card or runtime documents. |

## HTTP status reference

| Status | Marker | Meaning | Retry? |
| --- | --- | --- | --- |
| 401 | `message: Unauthenticated.` | Key missing, mistyped or revoked | No |
| 402 | `no_active_plan` | No active plan and no credit | No |
| 403 | `code: email_unverified` | Email not confirmed | No |
| 404 | | Wrong path | No |
| 413 | `context_length_exceeded` (`estimated_tokens`, `context_cap`, `bound_by`, `plan`) | Prompt too big | After trimming |
| 422 | `errors` object | Invalid request: unknown model, empty `messages`, a bad `role`, `temperature` or `top_p` out of range | No |
| 429 | `session_quota_exceeded` (`resets_at`) | 5-hour session cap reached | After `resets_at` |
| 429 | `quota_exceeded` (`resets_at`, `plan`, monthly or weekly used and cap) | Quota used and no credit | After `resets_at` |
| 429 | `message: Too Many Attempts.` and `Retry-After` | Over 60 requests a minute | After `Retry-After` |
| 502 | `upstream_unreachable`, `upstream_timeout`, `no_usage_accounting` (`request_id`) | Upstream problem | Yes, with backoff |
| 503 | `server_busy` | No slot free | Yes, with backoff |
| 503 | `model_unavailable` (`model`) | No server serving that model | A few times at most, then another model |
| 504 | `upstream_timeout` | Upstream time limit | Yes; prefer streaming |
| 524 | Cloudflare, HTML body | Edge timeout on a non-streamed request | Yes; use streaming |
| 4xx/5xx | `upstream_error` (`status`, `body`, `request_id`) | The serving server returned an error | Yes for 5xx; check the request for 4xx |

The same table, with example bodies, is in the [error reference](https://molochai.dev/docs/errors?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai).

## Getting help

- **A problem with the hosted API or your account:** use [molochai.dev/contact](https://molochai.dev/contact?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai). Support runs through Messages in the dashboard. Include the time, the model id, the status, the error `type` and any `request_id`. Never include your API key.
- **A mistake in these docs or a bug in `tools/compare_models.py`:** open an issue in this repository ([contributing](../CONTRIBUTING.md)). Do not paste keys or private prompts into issues.
