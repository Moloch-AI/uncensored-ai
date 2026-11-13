# Deployment options: self-hosted or a hosted API

Every refusal-reduced model is an open-weight model, so running one yourself is a real option. This page compares running a model on your own or rented hardware with calling one through a hosted OpenAI-compatible API such as MolochAI, and shows how to keep the choice open.

- [The options](#the-options)
- [Local and self-hosted runtimes](#local-and-self-hosted-runtimes)
- [Memory for the weights](#memory-for-the-weights)
- [Trade-offs](#trade-offs)
- [Cost: what to compare](#cost-what-to-compare)
- [When each one fits](#when-each-one-fits)
- [Finding a refusal-reduced build to self-host](#finding-a-refusal-reduced-build-to-self-host)
- [Using both](#using-both)

## The options

| Option | What you run | What you manage |
| --- | --- | --- |
| Local runtime on your machine | llama.cpp, Ollama, LM Studio and similar, usually with a quantized GGUF file | The machine, the model files, updates |
| Self-hosted server (owned or rented GPUs) | A serving engine such as vLLM or llama.cpp's server | Hardware or rental, drivers, scaling, monitoring, on-call |
| Hosted OpenAI-compatible API | Nothing; you call `https://api.molochai.dev/api/v1` | Your API key, your quota, the API's errors and limits |
| Both | A local or self-hosted model for some work, the API for the rest | Two base URLs in your config |

All of these speak the OpenAI Chat Completions format, so the client code is the same. Only the base URL, the key and the model id change, and the decision can be revisited later without rewriting your application.

## Local and self-hosted runtimes

Each of these exposes an OpenAI-compatible HTTP endpoint. The table lists the base URL as each project's own documentation shows it; the port is configurable in all of them.

| Runtime | What it is | OpenAI-compatible base URL | Documentation |
| --- | --- | --- | --- |
| llama.cpp (`llama-server`) | C/C++ inference that runs GGUF files on CPU and GPU | `http://localhost:<port>/v1`, with the port set by `--port` | [llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) |
| Ollama | Local model runner with its own model library | `http://localhost:11434/v1/` | [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility) |
| LM Studio | Desktop app for running models locally, with a built-in server | `http://localhost:1234/v1` in its examples | [LM Studio OpenAI compatibility](https://lmstudio.ai/docs/developer/openai-compat) |
| vLLM | GPU inference and serving engine | `http://localhost:8000/v1` in its examples | [vLLM OpenAI-compatible server](https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/) |

Notes that apply to all of them:

- Local servers usually do not check the API key, but the OpenAI SDKs require a value. Ollama's documentation uses a placeholder key that it ignores.
- If you expose a server beyond `localhost`, turn on its authentication. `llama-server` and vLLM both take an `--api-key` option; vLLM's documentation notes that it protects only some path prefixes.
- Tool calling depends on the model's chat template and on the runtime's parser for it. The GLM-4.7-Flash card's serving examples, for instance, pass `--tool-call-parser glm47` and `--reasoning-parser glm45` to vLLM and SGLang. Check the card of the model you serve.

## Memory for the weights

Weights take roughly the parameter count times the bytes stored per parameter: 2 at 16-bit, 1 at 8-bit, about 0.5 at 4-bit. Real 4-bit files come out somewhat larger, because quantization formats store scales and keep some layers at higher precision. Arithmetic for the base models MolochAI serves, weights only, with parameter counts from each card (GB = 10⁹ bytes):

| Base model | Parameters (per card) | 16-bit | 8-bit | 4-bit |
| --- | --- | --- | --- | --- |
| [GLM-5.3-Flash](https://huggingface.co/zai-org/GLM-5.3-Flash) | 320B total, 18B active | 640 GB | 320 GB | about 160 GB |
| [GLM-4.7-Flash](https://huggingface.co/zai-org/GLM-4.7-Flash) | 30B total, about 3B active | 60 GB | 30 GB | about 15 GB |
| [Gemma 4 26B A4B](https://huggingface.co/google/gemma-4-26B-A4B-it) | 25.2B total, 3.8B active | 50.4 GB | 25.2 GB | about 12.6 GB |
| [Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B) | 27B | 54 GB | 27 GB | about 13.5 GB |
| [Llama-3.3-70B-Instruct](https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct) | 70B | 140 GB | 70 GB | about 35 GB |

GLM-5.3-Flash, GLM-4.7-Flash and Gemma 4 26B A4B are mixture-of-experts models: only a fraction of their parameters works on each token, which makes them fast for their size. It does not make them small. Every expert still has to be loaded, so memory follows the total, not the active count.

What the table leaves out:

- **The KV cache.** Each token of context held in memory costs space on top of the weights, and the cost grows with context length and with the number of requests served at once. Long contexts are where self-hosted setups most often run out of memory.
- **Runtime overhead.** The serving software, activations and the GPU driver take their own share.
- **Speed.** Fitting is not the same as being pleasant to use. Splitting across GPUs or offloading layers to system memory works, and slows every token.

Measure on your own hardware, at the context length you need, before buying anything. The table tells you which class of machine to test, not which one is fast enough.

## Trade-offs

| | Self-hosted (local or your own servers) | Hosted API (MolochAI) |
| --- | --- | --- |
| Hardware and memory | Memory for weights plus KV cache, per the table above. The largest model needs a multi-GPU server even at 4-bit. | None on your side. |
| Operations | Installing, updating, drivers, monitoring, and someone on call when it stops. | None on your side. Your code handles the API's errors, for example `503 model_unavailable` and `429`. |
| Data control | Prompts stay on hardware you control. | Prompts pass through the gateway and the inference server running the model. The [Privacy Policy](https://molochai.dev/privacy?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) says what is recorded. No data processing agreement is offered. |
| Cost model | Hardware bought or rented by the hour, paid whether it is busy or idle, plus your time. | Prepaid credit charged per request, or a monthly plan with a token quota. Nothing is billed for idle time. See [pricing](https://molochai.dev/pricing?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai). |
| Model choice | Any open-weight build you can find and fit, including which refusal-reduced variant. | The five served ids. Exact builds are not published, and there is no version pinning. |
| Configuration | You choose sampling, reasoning on or off, context length and quantization. | Reasoning and its effort are fixed per model. Output is capped per reply by plan; `max_tokens` has no effect. Context is set by plan and server. Some parameters are ignored. |
| Tool-calling reliability | Depends on the model, its chat template and your runtime's tool-call parser. You can fix what breaks. | `tools` are passed through, and the gateway converts tool calls a model writes as plain text into the standard shape. Quality can still vary by server. While streaming, arguments arrive whole. |
| Features beyond chat | Runtimes can offer embeddings, text completions and constrained output. Check your runtime. | Chat completions and the model list only. No embeddings, no JSON mode. |
| Limits | Your hardware's throughput. | 60 requests a minute per account, a 5-hour session cap, a plan quota, context of 65,536 to 200,704 tokens by plan (401,408 on Enterprise+), and 9,000 output tokens per reply (30,000 on Enterprise+). |
| Comparing models | Download, fit and serve each one. | Change one string. |

Test tool calling end to end either way. Neither a card nor a runtime guarantees that a given build returns well-formed tool calls for your tools.

## Cost: what to compare

There are no GPU or API prices here: they change too often and depend on where you buy. Put these side by side instead:

- **Owning:** the hardware price spread over the months you expect to use it, plus power, plus your hours for setup, updates and incidents.
- **Renting:** the hourly rate times the hours the machine is up. An always-on machine bills about 730 hours a month whether anyone sends a request or not.
- **API credit:** per-token charges for what you send, nothing for idle time.
- **An API plan:** a fixed monthly price for a token quota. Divide one by the other for the cost per million tokens at full use; use less, and each token costs more.

Then estimate the tokens you would actually send in a month, prompts included, since every request re-sends its context. Reasoning tokens count as output.

## When each one fits

**Self-hosting fits** steady, high volume on one model that fits hardware you already have; data that must not leave your network; or a need for something the API does not provide, such as embeddings, constrained output, a pinned build or reasoning switched off on a reasoning model.

**The hosted API fits** uneven or modest volume; the largest model, which few teams can host; comparing several models before committing to one; or a team where nobody should be on call for a GPU server.

## Finding a refusal-reduced build to self-host

The weights on each base model's card are the developer's own, with their usual refusal behavior. A refusal-reduced version is a third-party modification, abliterated, fine-tuned or both, and several can exist for one base model. Before you adopt one:

- Check who published it and whether the method is described.
- Check which base model and license it derives from. The base license applies to what you run.
- Check the file format and quantization against your runtime and memory.
- Test it on your own prompts, for both refusals and quality ([how](models.md#testing-a-model-on-your-own-prompts)).

MolochAI's exact builds are not published, so you cannot download the same weights the API serves.

## Using both

Because both sides speak the same format, many setups mix them: a small local model for drafts or embeddings, and the API for larger models. Only the base URL, key and model id differ. This example assumes `llama-server` was started with `--port 8080`:

```python
import os

from openai import OpenAI

# Same client code for both: only the base URL, key and model id change.
local = OpenAI(base_url="http://localhost:8080/v1", api_key="unused")
hosted = OpenAI(
    base_url=os.environ.get("MOLOCHAI_BASE_URL", "https://api.molochai.dev/api/v1"),
    api_key=os.environ["MOLOCHAI_API_KEY"],
)


def ask(client: OpenAI, model: str, text: str) -> str:
    reply = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": text}],
    )
    return reply.choices[0].message.content or ""


print(ask(hosted, "llama-3.3-70b-instruct-abliterated", "Outline chapter three."))
# ask(local, "<the id your runtime lists at /v1/models>", "Outline chapter three.")
```

The [setup guide](setup.md) covers pointing existing tools at either one, and MolochAI's [self-hosted vs API page](https://molochai.dev/uncensored-ai/self-hosted-vs-api?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) works through the same comparison with plan figures.
