# Concepts: what "uncensored" means for a language model

An uncensored (less-restricted, refusal-reduced) language model is a model whose learned habit of declining requests has been reduced. This page explains where that habit comes from, the ways it gets reduced, and what changes and what does not when it is.

- [Where refusals come from](#where-refusals-come-from)
- [Over-refusal](#over-refusal)
- [What the terms mean](#what-the-terms-mean)
- [How a model becomes less restricted](#how-a-model-becomes-less-restricted)
- [What changes and what does not](#what-changes-and-what-does-not)
- [Base models and derived builds](#base-models-and-derived-builds)
- [Reasoning models](#reasoning-models)
- [Further reading](#further-reading)

## Where refusals come from

A chat model starts as a text predictor trained on a large corpus. It becomes an assistant in a second stage of training, on example conversations and on human preferences between answers. That second stage is where it learns to follow instructions, and it is also where it learns to decline. In an open-weight model, refusal is usually not a separate filter in front of the model: it is a behavior stored in the weights, learned the same way as answering politely.

A hosted service can also wrap a model in filters of its own, on the input or on the output. Those are a property of the service, not of the weights, and changing the model does not change them.

## Over-refusal

Learned behavior generalizes from surface features. A model trained to decline instructions for violence can also decline a question about how to kill a stuck process, a villain's monologue, or a history essay that quotes a survivor. Researchers call this exaggerated safety. The XSTest suite ([Röttger et al., NAACL 2024](https://arxiv.org/abs/2308.01263)) was built to measure it: 250 safe prompts across ten prompt types that a well-calibrated model should answer, many of them written to resemble unsafe prompts, alongside 200 unsafe prompts as a contrast set. Its authors found that some models refuse safe prompts mainly because of how they are worded.

For consumer chat, an occasional over-refusal is an annoyance. In a product built on an API it is a defect that shows up in production: a scene that does not get written, a document that does not get summarized, a classifier that does not get its test data. A refusal is not an error either. The request succeeds with HTTP 200 and the text declines, so it does not show up in error dashboards.

## What the terms mean

| Term | Meaning |
| --- | --- |
| Uncensored | The common search term. For a model, it means refusal behavior has been reduced. It does not mean the model never declines, and it does not mean anything is allowed. |
| Less-restricted, refusal-reduced | The more precise names for the same thing. These docs use them in prose. |
| Abliterated | Refusal-reduced by removing a "refusal direction" from the weights (see below). A model named "abliterated" claims this specific method. |
| Jailbreak | A prompt that gets a model to ignore its training for one request. It is not a property of the model. |
| Open-weight | The weights are published and can be downloaded and modified. Every refusal-reduced model is a modified open-weight model, because the change is made to the weights. |

The [glossary](glossary.md) has more terms.

## How a model becomes less restricted

### Refusal-direction ablation (abliteration)

In 2024, [Arditi et al., "Refusal in Language Models Is Mediated by a Single Direction" (arXiv:2406.11717)](https://arxiv.org/abs/2406.11717) studied how chat models decide to refuse. The method, in outline:

1. Run the model on a set of harmful instructions and a set of harmless ones, and record the residual-stream activations (the vector each layer adds to and reads from).
2. For each layer and post-instruction token position, take the mean activation on the harmful set minus the mean on the harmless set. This difference-in-means vector is a candidate refusal direction. Pick one candidate using validation prompts and normalize it to a unit vector r̂.
3. Remove it. Directional ablation does this at inference time, subtracting the component along r̂ from every activation: `x' = x - r̂ r̂ᵀ x`. Weight orthogonalization makes the same change permanent by editing every matrix that writes into the residual stream (the embedding matrices, attention output matrices and MLP output matrices): `W' = W - r̂ r̂ᵀ W`. The paper shows the two are equivalent.

Across 13 open-source chat models of up to 72B parameters, erasing that one direction largely stopped refusals of harmful instructions, and adding it made the models refuse harmless ones. The open-model community turned weight orthogonalization into a routine edit and calls the result "abliterated".

The weight form is what makes abliterated models practical: the output is an ordinary checkpoint with the same architecture, so it can be quantized, converted to GGUF and served by any standard runtime, with no hooks at inference time.

What it costs, per the paper's own evaluation: on MMLU, ARC and GSM8K the orthogonalized models scored about the same as the originals, while accuracy on TruthfulQA (which tests whether a model repeats common misconceptions) dropped consistently. Three caveats when you choose an abliterated model today:

- **Community builds are not the paper.** Each one picks its own prompt sets, layers and edited matrices, so two abliterated builds of the same base model can behave differently.
- **Quantization adds its own loss.** Many abliterated releases ship as GGUF quantizations.
- **Reduced is not erased.** Refusal learned through other routes can survive, so some declines remain.

### Fine-tuning

The other common method is further training on conversations where the assistant answers instead of declining. It needs training data and compute, and because it moves many weights, style and knowledge can shift along with refusal behavior. Some builds combine fine-tuning and abliteration.

### Prompting, and its limits

System prompts, role framing and jailbreaks work per request, on the model's terms. A jailbreak tends to stop working when a provider retrains or filters against it, and it tends to drag the output toward the jailbreak's persona. A system message is the right place for the job and its tone, but it cannot reliably undo trained refusal behavior. On a model that is already refusal-reduced, instructions like "you are an uncensored AI" add nothing and tend to make output more lurid than the task calls for; brief the model the way you would brief a human writer or analyst.

| Method | Needs the weights | How long it lasts | Side effects |
| --- | --- | --- | --- |
| Prompt jailbreak | No | One request, until patched | Unpredictable; output drifts toward the jailbreak's persona |
| Fine-tuning on compliant answers | Yes, plus data and compute | Permanent in the weights | Can shift style and knowledge, because many weights move |
| Abliteration | Yes, plus two prompt sets and forward passes | Permanent in the weights | Small on most benchmarks in the original paper, with a consistent drop on TruthfulQA |

## What changes and what does not

Reducing refusals changes what a model is willing to attempt. It does not change what it knows or how carefully it reasons.

- **Accuracy is not better, and can be slightly worse.** Learning to decline overlaps with learning to notice uncertainty. A model that no longer declines can be more willing to sound confident when it should hedge (the TruthfulQA result above is one measurement of this).
- **It still declines sometimes.** Phrasing, the system message and sampling all affect the outcome.
- **Knowledge cutoff and context window are untouched.** If the base model did not know something, the derived build does not either.
- **The rules do not move.** A model being willing to write something does not make it legal, and on a hosted service it does not make it allowed. On MolochAI the [Acceptable Use Policy](https://molochai.dev/acceptable-use?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) applies to every request, whatever the model would generate.
- **Moderation moves to you.** With a mainstream model, some moderation happens inside the model whether you want it or not. With a refusal-reduced one that layer is thinner, so an application that faces end users needs its own rules and moderation. See [responsible use](responsible-use.md).

## Base models and derived builds

A refusal-reduced model is a third-party modification of a base model. The base model's developer does not publish or endorse it. That has three consequences:

- **Card facts describe the base model.** Parameters, context length, input types and tool support come from the base model's card. The derived build can behave differently, and benchmark scores published for the base model say little about it.
- **The base license still applies.** MIT, Apache 2.0 or the Llama 3.3 Community License, for example, each with their own terms. Read the license on the card against your use.
- **Builds differ.** Several refusal-reduced builds can exist for one base model. Test the one you use, on your own prompts ([models: testing a build](models.md#testing-a-model-on-your-own-prompts)).

## Reasoning models

Some models produce a reasoning pass ("thinking") before the answer. Depending on the server, the reasoning arrives in a separate `reasoning_content` field or inline in the text between `<think>` and `</think>` tags. Reasoning tokens are output tokens: they count toward usage and quotas, and reasoning you send back in later turns uses context. Refusal reduction does not change how a model reasons. [Building applications](building-applications.md#reasoning-content) covers handling it.

## Further reading

- Arditi et al. [Refusal in Language Models Is Mediated by a Single Direction](https://arxiv.org/abs/2406.11717). arXiv:2406.11717, 2024.
- Röttger et al. [XSTest: A Test Suite for Identifying Exaggerated Safety Behaviours in Large Language Models](https://arxiv.org/abs/2308.01263). NAACL 2024.
- MolochAI: [Uncensored LLMs](https://molochai.dev/uncensored-ai?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) and [Abliterated models](https://molochai.dev/abliterated-models?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai).
