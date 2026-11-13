# Setup

From no account to a working request, then the same three values in the tools you already use. For running models on your own hardware instead, see [deployment options](deployment-options.md).

- [1. Account, credit and key](#1-account-credit-and-key)
- [2. Environment variables](#2-environment-variables)
- [3. Check the key](#3-check-the-key)
- [4. First request](#4-first-request)
- [5. Streaming](#5-streaming)
- [MolochAI SDKs and CLI](#molochai-sdks-and-cli)
- [Existing tools](#existing-tools)
- [Developing offline against the mock server](#developing-offline-against-the-mock-server)

## 1. Account, credit and key

1. [Register](https://dash.molochai.dev/register?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) and confirm your email address. Until it is confirmed, the API answers `403` with `code: email_unverified`.
2. Add credit or buy a plan in the dashboard under Billing. There is no free tier, so requests return `402` (`no_active_plan`) until a payment confirms. Rates and plans are on the [pricing page](https://molochai.dev/pricing?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai).
3. Create an API key under [Account → API keys](https://dash.molochai.dev/account?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai). It is shown once, so copy it then.

Keys do not expire on a timer and can be revoked at any time. They are **not scoped**: a key can read account details and create invoices, not just run inference. Keep keys on your server, never in a browser or mobile app, and use one key per application or environment so you can revoke one without touching the others.

## 2. Environment variables

| Variable | Required | Default | Used by |
| --- | --- | --- | --- |
| `MOLOCHAI_API_KEY` | Yes | | Every example here, the MolochAI SDKs and CLI, `tools/compare_models.py` |
| `MOLOCHAI_BASE_URL` | No | `https://api.molochai.dev/api/v1` | The same. Point it at the mock server for offline work. |
| `OPENAI_BASE_URL`, `OPENAI_API_KEY` | No | | The official OpenAI SDKs read these, so existing code can switch with configuration plus a model id. |

```bash
export MOLOCHAI_API_KEY=your-api-key
export MOLOCHAI_BASE_URL=https://api.molochai.dev/api/v1
```

In PowerShell, use `$env:MOLOCHAI_API_KEY = "your-api-key"`. The `curl` examples in these docs use POSIX shell quoting; on Windows, run them in Git Bash or WSL, or use the Python example.

## 3. Check the key

```bash
curl "$MOLOCHAI_BASE_URL/models" -H "Authorization: Bearer $MOLOCHAI_API_KEY"
```

A `200` with a list of models means the key works and the account can make requests. `401` means the key is missing, mistyped or revoked; `402` means no active plan and no credit. `GET /api/auth/me` returns the account's plan and each model's context limit ([models](models.md#get-the-current-list-from-the-api)).

## 4. First request

### curl

```bash
curl "$MOLOCHAI_BASE_URL/chat/completions" \
  -H "Authorization: Bearer $MOLOCHAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "glm-5.3-flash",
    "messages": [
      {"role": "user", "content": "Remove duplicates from a Python list, keeping order."}
    ]
  }'
```

### Python (official `openai` package)

```bash
pip install openai
```

```python
import os

from openai import OpenAI

client = OpenAI(
    base_url=os.environ.get("MOLOCHAI_BASE_URL", "https://api.molochai.dev/api/v1"),
    api_key=os.environ["MOLOCHAI_API_KEY"],
)

reply = client.chat.completions.create(
    model="glm-5.3-flash",
    messages=[{"role": "user", "content": "Remove duplicates from a Python list, keeping order."}],
)

print(reply.choices[0].message.content)
print(reply.choices[0].finish_reason, reply.usage.total_tokens if reply.usage else None)
```

### JavaScript (official `openai` package, Node 20 or later)

```bash
npm install openai
```

Save as `quickstart.mjs` and run `node quickstart.mjs`:

```javascript
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: process.env.MOLOCHAI_BASE_URL ?? "https://api.molochai.dev/api/v1",
  apiKey: process.env.MOLOCHAI_API_KEY,
});

const reply = await client.chat.completions.create({
  model: "glm-5.3-flash",
  messages: [{ role: "user", content: "Remove duplicates from a Python list, keeping order." }],
});

console.log(reply.choices[0].message.content);
console.log(reply.choices[0].finish_reason, reply.usage?.total_tokens);
```

The response is a standard `chat.completion`. `model` is always the id you sent. On models with reasoning on, `message.reasoning_content` may also be present; treat it as optional. If the serving server leaves reasoning inline, a non-streamed `content` starts with a `<think>...</think>` block, which [streaming](#5-streaming) removes for you.

## 5. Streaming

Stream anything that might take more than a few seconds. Cloudflare in front of the API gives up on a response after about 100 seconds, so a long non-streamed generation can fail with `524` at the edge. A stream stays alive with keep-alive comments, reports queueing, and delivers reasoning and answer separately.

```bash
curl -N "$MOLOCHAI_BASE_URL/chat/completions" \
  -H "Authorization: Bearer $MOLOCHAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "glm-5.3-flash", "stream": true, "messages": [{"role": "user", "content": "Explain SSE in two sentences."}]}'
```

With the `client` from step 4, in Python and JavaScript:

```python
stream = client.chat.completions.create(
    model="glm-5.3-flash",
    messages=[{"role": "user", "content": "Explain SSE in two sentences."}],
    stream=True,
)

for chunk in stream:
    if not chunk.choices:  # the last chunk has no choices, only usage
        if chunk.usage:
            print(f"\n[{chunk.usage.total_tokens} tokens]")
        continue
    delta = chunk.choices[0].delta
    if delta.content:
        print(delta.content, end="", flush=True)
```

```javascript
const stream = await client.chat.completions.create({
  model: "glm-5.3-flash",
  messages: [{ role: "user", content: "Explain SSE in two sentences." }],
  stream: true,
});

for await (const chunk of stream) {
  const delta = chunk.choices[0]?.delta;
  if (delta?.content) process.stdout.write(delta.content);
  if (chunk.usage) console.log(`\n[${chunk.usage.total_tokens} tokens]`);
}
```

[Building applications](building-applications.md#streaming) covers the event format, reasoning deltas, the cap notice and errors that arrive inside a stream.

## MolochAI SDKs and CLI

The official OpenAI SDKs are a fine choice and everything above uses them. The MolochAI SDKs exist for the parts of this API the OpenAI SDKs leave to you: queue progress from SSE comments, typed errors with `resets_at`, `context_cap` and `bound_by`, `/auth/me` for per-model context limits, and in-stream errors and the cap notice.

| Repository | What it is | Install from GitHub |
| --- | --- | --- |
| [uncensored-ai-python](https://github.com/Moloch-AI/uncensored-ai-python) | Typed Python SDK, sync and async | `pip install "git+https://github.com/Moloch-AI/uncensored-ai-python@v0.1.2"` |
| [uncensored-ai-node](https://github.com/Moloch-AI/uncensored-ai-node) | TypeScript SDK for Node, ESM, no runtime dependencies | `npm install github:Moloch-AI/uncensored-ai-node#v0.1.1` |
| [uncensored-ai-cli](https://github.com/Moloch-AI/uncensored-ai-cli) | Terminal chat client | `pipx install "git+https://github.com/Moloch-AI/uncensored-ai-cli@v0.1.0"` |
| [uncensored-ai-api](https://github.com/Moloch-AI/uncensored-ai-api) | OpenAPI spec, dependency-free reference clients, mock server | Clone the repository |

Registry packages (PyPI, npm) are not published yet; install from GitHub as shown. Each repository's README has its own usage.

## Existing tools

Anything with an "OpenAI compatible" provider setting can use the API with three values:

- **Base URL:** `https://api.molochai.dev/api/v1`. Tools add `/chat/completions` themselves, so paste the base only.
- **API key:** a key from [Account → API keys](https://dash.molochai.dev/account?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai). Give each tool or machine its own key.
- **Model id:** one of the ids from `GET /models`. Tools that fetch a model list fill their dropdown by themselves.

Settings that matter in every tool:

- **Context size.** Set the tool's context or history limit about 10% under the `context_limit` that `/api/auth/me` reports for the model. Tools count tokens with their own tokenizer and the API's check is an estimate. Set it above the limit and long chats start failing with `413` while short ones still work.
- **Response length.** A max-tokens or response-length setting cannot shorten replies: the plan's output cap replaces it. Ask for the length you want in the prompt.
- **Reasoning effort.** A reasoning-effort control has no effect; the gateway fixes reasoning per model.
- **Streaming.** Keep it on. Long non-streamed replies can end in `524`.
- **Shared installs.** A shared install puts other people's prompts on your account and your quota. The [Acceptable Use Policy](https://molochai.dev/acceptable-use?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) applies to what they do. See [responsible use](responsible-use.md).

The full guides on molochai.dev were written from each tool's documentation and checked against the API's request format, not run end to end against production models. Settings screens move between versions; if a label differs, the base URL, key and model id are what matter.

### Open WebUI

1. **Settings → Admin → Connections → Manage OpenAI API Connections → Add Connection**, connection type External.
2. URL `https://api.molochai.dev/api/v1` (no trailing slash), and a key created for this instance.
3. Leave **Model IDs** empty so Open WebUI reads `/models`, and leave **Prefix ID** empty unless names collide. A prefix that reaches the API makes requests fail with `422`.
4. Click **Verify Connection**; saving alone does not test anything.

An admin connection is shared by every user, so they share one quota and one rate limit. Direct Connections, if your instance allows them, let each user bring their own key. Documents and knowledge bases need an embedding model, and this API has none: keep Open WebUI's embedding engine on a local model. Open WebUI can also send its own requests, for example to title chats, and each one counts. Full guide: [molochai.dev/integrations/open-webui](https://molochai.dev/integrations/open-webui?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai). Tool documentation: [OpenAI-compatible providers](https://docs.openwebui.com/getting-started/quick-start/connect-a-provider/starting-with-openai-compatible).

### SillyTavern

1. In API Connections, set the API type to **Chat Completion** and the source to **Custom (OpenAI-compatible)**.
2. Endpoint URL `https://api.molochai.dev/api/v1`, without `/chat/completions`.
3. Paste the key, pick a model (or type an id if the list is empty), connect, and press **Test Message**.

Set the context size about 10% under your limit, as above. When a reply stops at the output cap, the gateway's one-line notice lands inside the character's message; edit it out and ask for shorter replies. Prompts injected mid-chat with the System role can break some models' chat templates and fail as an upstream error; give them the User role or a stricter Prompt Post-Processing level. Full guide: [molochai.dev/integrations/sillytavern](https://molochai.dev/integrations/sillytavern?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai). Tool documentation: [Chat Completions sources](https://docs.sillytavern.app/usage/api_connections/openai.md).

### LibreChat

Add a custom endpoint under `endpoints` in `librechat.yaml`, keeping the file's existing `version` line:

```yaml
endpoints:
  custom:
    - name: "MolochAI"
      apiKey: "${MOLOCHAI_API_KEY}"
      baseURL: "https://api.molochai.dev/api/v1"
      models:
        default:
          - "glm-5.3-flash"
          - "llama-3.3-70b-instruct-abliterated"
        fetch: true
      titleConvo: true
      titleModel: "llama-3.3-70b-instruct-abliterated"
      modelDisplayLabel: "MolochAI"
```

Put `MOLOCHAI_API_KEY=your-api-key` in LibreChat's `.env`, or use `apiKey: "user_provided"` so each user enters their own key. With `fetch: true` LibreChat reads `/models` and falls back to `default` if that fails. `titleModel` points the extra title request at the model with reasoning off. In Docker, `librechat.yaml` is read only once it is mounted into the container (LibreChat's `docker-compose.override.yml` example shows the bind mount), and a schema error anywhere in the file stops the server. Full guide: [molochai.dev/integrations/librechat](https://molochai.dev/integrations/librechat?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai). Tool documentation: [custom endpoints](https://www.librechat.ai/docs/quick_start/custom_endpoints).

### Coding agents

Agents send a list of tools with every request and need structured tool calls back, so pick a model whose card states tool use ([models: choosing](models.md#choosing-a-model)) and test it on a real task in a scratch branch. Every agent step re-sends the conversation, so they reach the 60 requests per minute limit and the context window sooner than a chat does.

- **Cline and Roo Code:** set **API Provider** to **OpenAI Compatible**, then **Base URL**, **API Key** and **Model ID**. In the model configuration, set the context window about 10% under your limit and max output to 9,000 (or your plan's cap). Turn on image support only for a model whose card lists image input. Roo Code's documentation says it uses native tool calling only, so a model that does not return proper tool calls cannot work there.
- **Continue:** a model entry in `config.yaml` with `provider: openai`, `apiBase: https://api.molochai.dev/api/v1`, roles `chat`, `edit` and `apply`, and `capabilities: [tool_use]` for Agent mode. Leave out `autocomplete` (it needs a text-completion endpoint) and `embed` (there are no embeddings).
- **Aider:** set `OPENAI_API_BASE` and `OPENAI_API_KEY`, run `aider --model openai/<model-id>`, and tell Aider the limits in `.aider.model.metadata.json` (`max_input_tokens`, `max_output_tokens`) so it trims its own history instead of hitting `413`. Its whole-file edit format can exceed the 9,000-token reply cap on large files; `--edit-format diff` sends only changed blocks.

Full guide with complete configuration files: [molochai.dev/integrations/coding-agents](https://molochai.dev/integrations/coding-agents?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai). Tool documentation: [Cline](https://docs.cline.bot/provider-config/openai-compatible), [Roo Code](https://roocodeinc.github.io/Roo-Code/providers/openai-compatible), [Continue](https://docs.continue.dev/reference), [Aider](https://aider.chat/docs/llms/openai-compat.html).

## Developing offline against the mock server

[uncensored-ai-api](https://github.com/Moloch-AI/uncensored-ai-api) includes a zero-dependency Node mock server that simulates the documented API behavior: streaming, errors, rate limits and tool calls. Its replies are canned text, not model output. With the repository cloned:

```bash
node mock-server/server.mjs --port 4010
```

Then point any client at it:

```bash
export MOLOCHAI_BASE_URL=http://127.0.0.1:4010/api/v1
export MOLOCHAI_API_KEY=mock-key
```

Every example on this page runs against it unchanged. Markers in the last user message, such as `[mock:context]` or `[mock:rate-limit]`, make the mock return a specific error, which is how this repository's CI tests error handling. The uncensored-ai-api repository documents the full list.
