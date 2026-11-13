# Models

The five models MolochAI serves, what their base model cards state, what the gateway sets for each, and how to choose and test one on your own prompts.

> Catalog (ids, display names, gateway settings) as published at [molochai.dev/models](https://molochai.dev/models?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai), checked on 2026-11-07. Base-model facts were read from each model's own card on 2026-11-13. Both can change: the API is the source of truth for ids, and the cards are the source for base-model facts.

- [Get the current list from the API](#get-the-current-list-from-the-api)
- [The lineup](#the-lineup)
- [Base model facts, per card](#base-model-facts-per-card)
- [What applies to every model](#what-applies-to-every-model)
- [Per-model notes](#per-model-notes)
- [Choosing a model](#choosing-a-model)
- [Testing a model on your own prompts](#testing-a-model-on-your-own-prompts)

## Get the current list from the API

Do not hardcode the list below in code. Ask the API:

```bash
curl "$MOLOCHAI_BASE_URL/models" -H "Authorization: Bearer $MOLOCHAI_API_KEY"
```

```json
{"object": "list", "data": [{"id": "glm-5.3-flash", "object": "model", "created": 0, "owned_by": "molochai", "name": "GLM-5.3-Flash", "available": true}]}
```

`name` (display name) and `available` (a server is serving the model right now) go beyond the OpenAI format; OpenAI clients ignore them. The endpoint is behind the quota check, so an account with no plan and no credit gets `402`.

For the context window your account actually gets per model, call `GET /api/auth/me`. Its path is outside `/api/v1`: derive it from the base URL by replacing the trailing `/v1` with `/auth/me`.

```bash
curl "${MOLOCHAI_BASE_URL%/v1}/auth/me" -H "Authorization: Bearer $MOLOCHAI_API_KEY"
```

Its `models` array has `id`, `name`, `available` and `context_limit` for each model: the smaller of your plan's limit and the serving server's limit, or `null` when no server serves the model.

## The lineup

| API id | Display name | Base model (developer, license) | Reasoning, set by the gateway | Default sampling | Input, per card | Model page |
| --- | --- | --- | --- | --- | --- | --- |
| `glm-5.3-flash` | GLM-5.3-Flash | GLM-5.3-Flash (Z.ai, MIT) | On, high effort | temperature 0.6, top_p 0.95 | Text, images | [page](https://molochai.dev/models/glm-5-3-flash?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) |
| `glm-4.7-flash-uncensored` | GLM-4.7-Flash-Uncensored | GLM-4.7-Flash (Z.ai, MIT) | On, medium effort | temperature 0.6, top_p 0.95 | Text | [page](https://molochai.dev/models/glm-4-7-flash-uncensored?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) |
| `gemma4-26b-a4b-qat` | Gemma4-26B-A4B-QAT | Gemma 4 26B A4B (Google DeepMind, Apache 2.0) | On, medium effort | temperature 0.6, top_p 0.95 | Text, images | [page](https://molochai.dev/models/gemma4-26b-a4b-qat?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) |
| `qwen3.8-27b-uncensored` | Qwen3.8-27B-Uncensored | Qwen3.8-27B (Qwen Team, Apache 2.0) | On, medium effort | temperature 0.6, top_p 0.95 | Text, images, video (see note) | [page](https://molochai.dev/models/qwen3-8-27b-uncensored?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) |
| `llama-3.3-70b-instruct-abliterated` | Llama-3.3-70B-Instruct-abliterated-GGUF | Llama-3.3-70B-Instruct (Meta, Llama 3.3 Community License) | Off | temperature 0.7, top_p 0.8 | Text | [page](https://molochai.dev/models/llama-3-3-70b-instruct-abliterated?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) |

Default sampling applies only when you leave `temperature` or `top_p` out; your own values take precedence. Video input through this API is not documented, so do not plan on it.

## Base model facts, per card

These describe the base models, not the builds served. Each fact links to the card it came from. "Not stated" means the card does not say, not that the answer is no.

| Base model | Parameters | Context, per card | Thinking, per card | Tool use, per card |
| --- | --- | --- | --- | --- |
| [GLM-5.3-Flash](https://huggingface.co/zai-org/GLM-5.3-Flash) | 320B total, 18B active | Not stated as a model limit | Yes; `reasoning_effort` low, high or max | Not stated as a feature |
| [GLM-4.7-Flash](https://huggingface.co/zai-org/GLM-4.7-Flash) | 30B total, about 3B active (MoE) | Not stated | Yes, with a Preserved Thinking mode | Serving examples include a tool-call parser |
| [Gemma 4 26B A4B](https://huggingface.co/google/gemma-4-26B-A4B-it) | 25.2B total, 3.8B active | 256K tokens | Yes, a built-in reasoning mode | Yes, native function calling |
| [Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B) | 27B | 262,144 tokens, extensible to 1,000,000 | Yes, on by default | Not stated for the open weights |
| [Llama-3.3-70B-Instruct](https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct) | 70B | 128K | Not stated | Yes, several tool use formats |

## What applies to every model

- **Refusal-reduced builds.** All five are builds with reduced refusal behavior that the base developers do not publish or endorse. The exact builds are not published, and only the Llama model's name claims a method (abliteration). See [concepts](concepts.md#base-models-and-derived-builds).
- **Reasoning is fixed per model.** Thinking and its effort cannot be changed per request; a `reasoning_effort` you send has no effect. Reasoning tokens count as output and against quota.
- **No version pinning.** The build behind an id can change, and there is no `seed`. Keep your own tests for behavior you depend on.
- **Routing is strict.** A request runs only on a server serving the model it names. If none is, the API answers `503` with `model_unavailable` and does not switch you to another model. An unknown id returns `422`.
- **Context and output are set by plan.** Context is 65,536 to 200,704 tokens by plan (401,408 on Enterprise+), or the serving server's limit if lower, whatever the card says. Output is capped per reply at 9,000 tokens (30,000 on Enterprise+). See [pricing](https://molochai.dev/pricing?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) for plans.
- **Images depend on the server.** Image parts are forwarded unchanged and work only if the model takes images per its card and the serving server has vision enabled. Test before you depend on it.
- **Identity.** The gateway adds a short system line naming the model. Asking a model what it is tells you that name, not which build answered.

## Per-model notes

### `glm-5.3-flash`

- The card describes the first natively multimodal model in the GLM-5 series, with 320B total and 18B active parameters. The card's `reasoning_effort` defaults to max; the gateway sends high.
- The card states no maximum context; limits in its benchmark footnotes describe test setups.
- The card reports tool-using benchmarks but does not list tool calling as a feature. Test your tool loop first.

### `glm-4.7-flash-uncensored`

- A 30B-A3B mixture-of-experts text model. The card recommends Preserved Thinking for multi-turn agentic tasks, and its vLLM and SGLang examples set both a tool-call parser and a reasoning parser.
- To keep reasoning across turns, send `reasoning_content` back on assistant messages ([how](building-applications.md#reasoning-content)).

### `gemma4-26b-a4b-qat`

- The card lists a 256K-token context window, text and image input (video as frames), native function calling and a built-in reasoning mode. The 256K window is not your limit here; your plan's is.
- QAT is quantization-aware training: the effect of quantization is simulated during training rather than applied only afterwards.
- The card lists Apache 2.0. Check the license on the card against your use.

### `qwen3.8-27b-uncensored`

- The card describes a native vision-language model that understands images and video, with 262,144 tokens of native context, extensible to 1,000,000, and thinking on by default.
- The extended context is not available by default here. The card mentions built-in tools only for the hosted version, so test tool calling with your own loop.

### `llama-3.3-70b-instruct-abliterated`

- The only model with reasoning off at the gateway, so text starts without a reasoning pass. GGUF is the file format used by llama.cpp.
- The card lists 70B parameters, a 128K context window, text input and output, a knowledge cutoff of December 2023, several tool use formats, and eight languages: English, German, French, Italian, Portuguese, Hindi, Spanish and Thai.
- The Llama 3.3 Community License has conditions of its own, including naming rules for derived models and an acceptable use policy. Read it on the card.

## Choosing a model

There are no benchmark scores here and no ranking: nothing in this repository measures one. Start from what your application needs, then compare candidates on your own prompts.

| If you need | Candidates | Why |
| --- | --- | --- |
| Image input | `glm-5.3-flash`, `gemma4-26b-a4b-qat`, `qwen3.8-27b-uncensored` | Their cards list image input. It works only on servers with vision enabled. |
| Tool calls in an agent loop | `gemma4-26b-a4b-qat`, `llama-3.3-70b-instruct-abliterated`, `glm-4.7-flash-uncensored` | Their cards state tool use or ship a tool-call parser. The other two cards do not state it; test before relying on them. |
| Text that starts streaming at once | `llama-3.3-70b-instruct-abliterated` | Reasoning is off at the gateway. |
| Planning, multi-step reasoning | The four models with reasoning on | They reason before answering. That costs output tokens and time to first token. |
| Languages other than English | `llama-3.3-70b-instruct-abliterated` | Its card names eight languages. Check other cards for the languages you need. |
| Recent facts | Any, with the facts in your prompt | Models do not know what happened after their training data; the Llama card gives a December 2023 cutoff. |

Pick by what the base model can do and how the gateway runs it, not by which model sounds most permissive.

## Testing a model on your own prompts

Published scores for a base model tell you little about a modified build. A small test of your own tells you more:

1. Build a prompt file with two kinds of lines: requests that are harmless but sound alarming, in the style of [XSTest](https://arxiv.org/abs/2308.01263), and real requests from your product.
2. Run every prompt through each candidate, with the same system message and sampling.
3. Count replies that open like a decline, then read a sample by hand: a string match misclassifies some replies.
4. Judge quality separately, on the same prompts, with the rubric your product uses. A build that declines less but gets the facts wrong is not an improvement.
5. Repeat when you change prompts, and from time to time anyway: builds behind an id can change.

[`tools/compare_models.py`](../tools/README.md) does steps 2 and part of 3: it streams each prompt to each model on any OpenAI-compatible endpoint, paces requests under the rate limit, and writes a Markdown or CSV table with the finish reason, latency, token counts and an excerpt of each answer.
