# FAQ

Short answers, with links to the page that has the detail.

## About uncensored models

### What is an uncensored LLM?

A language model whose learned refusal behavior has been reduced, by editing its weights (abliteration) or by further fine-tuning. It declines less often than the model it was derived from. See [concepts](concepts.md).

### Is it more accurate or more capable than the original?

No. Reducing refusals changes what a model is willing to attempt, not what it knows. The abliteration paper measured general benchmarks close to the originals and a consistent drop on TruthfulQA, and a model that declines less can also hedge less when it should ([concepts](concepts.md#what-changes-and-what-does-not)).

### Will it answer anything?

No. It still declines sometimes, depending on phrasing, the system message and sampling. And a model being willing to write something does not make it legal or allowed: the [Acceptable Use Policy](https://molochai.dev/acceptable-use?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) applies to every request on MolochAI.

### Is abliteration a kind of jailbreak?

No. A jailbreak is a prompt that gets a model to ignore its training for one request. Abliteration removes a direction associated with refusal from the weights, so the change applies to every request with no special wording ([concepts](concepts.md#how-a-model-becomes-less-restricted)).

### Why is every uncensored model an open-weight model?

Because the change is made to the weights, and only published weights can be modified by third parties. The base developer does not publish or endorse the modified build.

### Do I need a jailbreak prompt or "you are uncensored" in the system message?

No. On a refusal-reduced model it adds nothing and tends to make output more lurid than the task needs. Describe the job, the audience and your rules, the way you would brief a person.

## Using MolochAI

### Which model should I use?

There is no ranking here, because nothing in this repository measures one. Start from what you need (images, tool calls, reasoning on or off, languages), then compare candidates on your own prompts ([models](models.md#choosing-a-model), [`tools/compare_models.py`](../tools/README.md)).

### Does it work with the official OpenAI SDKs?

Yes, for chat completions and the model list: set the base URL to `https://api.molochai.dev/api/v1` and use a MolochAI key. The differences that matter are listed in [building applications](building-applications.md): no JSON mode, ignored parameters, a plan output cap, strict model routing, in-stream errors and the cap notice.

### Then why are there MolochAI SDKs?

The OpenAI SDKs drop SSE comment lines (no queue progress), do not parse the three error shapes into typed errors with `resets_at`, `context_cap` and `bound_by`, have no `/auth/me` for per-model context limits, and leave in-stream errors and the cap notice to you. The [Python](https://github.com/Moloch-AI/uncensored-ai-python) and [Node](https://github.com/Moloch-AI/uncensored-ai-node) SDKs handle those. The OpenAI SDKs remain a fine choice.

### Is there a free tier or a test key?

No. Requests return `402` until the account has credit or a plan. For development without an account, use the [mock server](setup.md#developing-offline-against-the-mock-server); for real outputs, the smallest credit top-up on the [pricing page](https://molochai.dev/pricing?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) works on every model.

### Why did I get `503 model_unavailable` instead of an answer from another model?

A request runs only on a server serving the model it names. If none is, the API says so rather than running your prompt on a different model. Choosing a fallback is up to you ([example](building-applications.md#choosing-a-fallback-model)).

### Can I pin a model version or set a seed?

No. The build behind an id can change, and `seed` is ignored. Keep your own tests for behavior you depend on. This also makes the API a poor fit for reproducible benchmarks.

### Can I turn reasoning on or off, or change its effort?

No. The gateway fixes reasoning per model. `llama-3.3-70b-instruct-abliterated` is the one with reasoning off ([models](models.md#the-lineup)).

### Why does `max_tokens` not shorten replies?

It is accepted but has no effect: each plan caps replies at 9,000 tokens (30,000 on Enterprise+). Ask for the length you want in the prompt.

### How do I get JSON?

Ask for it in the prompt, then parse and validate it. `response_format` is ignored ([example](building-applications.md#structured-output-without-a-json-mode)).

### What are the limits?

60 requests per minute per account, a token cap per 5-hour session, a monthly quota on plans, a context window of 65,536 to 200,704 tokens by plan (401,408 on Enterprise+), and an output cap per reply. See [pricing](https://molochai.dev/pricing?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) for plans and [troubleshooting](troubleshooting.md#limits-and-quotas) for the errors.

### Is there an embeddings endpoint, image generation or audio?

No. Only `POST /chat/completions` and `GET /models` (plus `GET /api/auth/me` for account details). Use a local runtime or another provider for embeddings ([deployment options](deployment-options.md)).

### Can I send images or video?

Images, as `image_url` content parts, to models whose card lists image input, when the serving server has vision enabled. Video input is not documented ([building applications](building-applications.md#images)).

### Can I call the API from a browser or mobile app?

No. Keys are not scoped and can read account details and create invoices. Call the API from your server ([architecture](building-applications.md#architecture-keep-the-key-on-your-server)).

### What happens to my prompts?

The [Privacy Policy](https://molochai.dev/privacy?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) is the authority. In summary, as the site states it: for ordinary accounts, the text of API prompts and replies is not stored in the database, while usage counts and request metadata are recorded and operational logs can contain short fragments, such as a tool's target. Enterprise team seats keep excerpts so the account owner can review them. Keep secrets and credentials out of prompts regardless.

### Can I use it in a commercial product?

The [Terms](https://molochai.dev/terms?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) do not restrict commercial use of your own application, but reselling raw access to the capacity as your own API is not allowed, and your application has to follow the Acceptable Use Policy. Anything facing end users needs its own rules and moderation ([responsible use](responsible-use.md)).

## Self-hosting

### Can I run these models myself?

The base models, yes: they are open-weight, and [deployment options](deployment-options.md) works through the memory they need. Refusal-reduced builds of them are published by third parties; MolochAI's exact builds are not published.

### What hardware do I need?

For the weights alone, roughly the parameter count times 2 bytes at 16-bit, 1 at 8-bit and about 0.5 at 4-bit, plus room for the KV cache and the runtime. Mixture-of-experts models need memory for all their parameters, not just the active ones ([memory table](deployment-options.md#memory-for-the-weights)).

## This repository

### How do I report a mistake?

Open an issue or a pull request with a source link ([contributing](../CONTRIBUTING.md)). Problems with the hosted API go to [molochai.dev/contact](https://molochai.dev/contact?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai).
