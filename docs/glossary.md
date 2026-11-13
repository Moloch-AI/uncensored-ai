# Glossary

**Abliteration.** Removing a model's refusal direction from its weights by weight orthogonalization, so it declines less often. The name comes from the open-model community; the method from [Arditi et al. (2024)](https://arxiv.org/abs/2406.11717). See [concepts](concepts.md#refusal-direction-ablation-abliteration).

**Active parameters.** In a mixture-of-experts model, the parameters used for each token. Memory still has to hold all parameters.

**API key.** The bearer token sent in `Authorization: Bearer <key>`. On MolochAI it is shown once, does not expire on a timer, and is not scoped.

**Base model.** The model a refusal-reduced build is derived from, as published by its developer. Card facts describe the base model.

**Base URL.** The prefix a client adds endpoint paths to. For MolochAI, `https://api.molochai.dev/api/v1`; for local runtimes, something like `http://localhost:8080/v1`.

**Cap notice.** The text MolochAI's gateway appends when a reply stops at the plan's output cap without a tool call: two newlines, then `[Response is too large for your current plan. Try a smaller request.]`.

**Chat template.** The format a model expects its conversation in (roles, special tokens, tool-call syntax). Runtimes apply it; a wrong or missing template breaks tool calls and system messages.

**Context window.** The maximum size of everything in one request plus the reply, in tokens. On MolochAI, the smaller of the plan's limit and the serving server's.

**Derived build.** A modified version of a base model, such as an abliterated or fine-tuned variant. Not published or endorsed by the base model's developer.

**Directional ablation.** Removing the component along a direction from a model's activations at inference time: `x' = x - r̂ r̂ᵀ x`.

**Edge timeout.** Cloudflare in front of the API gives up on a response after about 100 seconds and returns `524` with an HTML body. Streaming avoids it.

**Exaggerated safety (over-refusal).** Declining safe requests because they resemble unsafe ones, measured by suites such as [XSTest](https://arxiv.org/abs/2308.01263).

**Fine-tuning.** Further training of a model's weights on new examples, for example conversations where the assistant answers instead of declining.

**`finish_reason`.** Why a reply ended: `stop` (finished), `length` (hit the output cap), or `tool_calls` (the model wants a tool run).

**GGUF.** The model file format used by llama.cpp, usually holding quantized weights.

**Identity line.** The short system text MolochAI's gateway prepends to every request, naming the model and saying it is served through the MolochAI API. Your own first system message is kept below it.

**Jailbreak.** A prompt that gets a model to ignore its training for one request. Not a property of the model, and not a substitute for a refusal-reduced build.

**KV cache.** Memory a runtime keeps for the tokens in context. It grows with context length and concurrent requests, on top of the weights.

**Less-restricted, refusal-reduced.** A model whose refusal behavior has been reduced. The precise terms for what is often searched as "uncensored".

**Mixture of experts (MoE).** An architecture in which each token is processed by a subset of the parameters (experts). Fast for its size, but all experts must be loaded.

**Mock server.** The zero-dependency test double in [uncensored-ai-api](https://github.com/Moloch-AI/uncensored-ai-api) that simulates the documented API behavior with canned replies. Used for offline development and CI.

**`model_unavailable`.** The `503` error type MolochAI returns when no server is serving the requested model. The request is never sent to another model.

**Open-weight.** A model whose weights are published and can be downloaded, run and modified, under its license.

**OpenAI-compatible.** An API that accepts and returns the OpenAI Chat Completions format, so OpenAI SDKs and tools work with a changed base URL. Compatibility covers the shape of requests and replies, not every behavior.

**Quantization.** Storing weights at lower precision (8-bit, 4-bit) to save memory, at some cost in quality.

**Quantization-aware training (QAT).** Training that simulates quantization, so the model holds up better when quantized.

**Reasoning (thinking).** A pass in which a model writes out intermediate steps before its answer. Reasoning tokens are output tokens.

**`reasoning_content`.** The field that carries reasoning separately from the answer: on the message in a non-streamed reply, on the delta while streaming. Optional, and it can be sent back on assistant messages to keep reasoning across turns.

**Refusal direction.** A direction in a model's residual-stream activations that mediates refusal, found as the difference between mean activations on harmful and harmless instructions.

**Residual stream.** The running vector each transformer layer reads from and adds to. Activations studied for refusal directions are taken from it.

**Session cap.** MolochAI's token limit for a fixed 5-hour window starting at the first request. Exceeding it returns `429 session_quota_exceeded` with `resets_at`.

**Server-sent events (SSE).** The streaming format: `data:` lines carrying JSON chunks, comment lines starting with `:`, ending with `data: [DONE]`.

**Token.** The unit models read and write, roughly three quarters of an English word. Usage, quotas, context windows and output caps are counted in tokens.

**Tool calling (function calling).** The model returns a structured request to run one of the tools you defined; your code runs it and sends the result back as a `tool` message.

**Uncensored.** The common search term for a refusal-reduced model. It does not mean the model never declines, that it is more accurate, or that anything is allowed.

**Weight orthogonalization.** Making directional ablation permanent by editing every matrix that writes into the residual stream: `W' = W - r̂ r̂ᵀ W`.
