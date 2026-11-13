# Contributing

Thank you for helping keep this guide accurate. Corrections are the most useful contribution: a wrong fact in a reference guide costs every reader time.

## Proposing a correction

1. Open an issue or a pull request that names the page and the statement.
2. Link the source that shows the correct version (see the sourcing rule below).
3. If the problem is with the hosted API rather than this guide, use [molochai.dev/contact](https://molochai.dev/contact?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) instead. Never post API keys, private prompts or account details in an issue.

Small fixes (typos, broken links, a clearer sentence) can go straight to a pull request.

## The sourcing rule

- **Every model fact needs a link to the model's own card**: parameters, context length, input types, thinking, tool use, license, knowledge cutoff, languages. Facts on a card describe the base model; say so when you write about a refusal-reduced build.
- **General claims need a source**: research results link to the paper (for example [arXiv:2406.11717](https://arxiv.org/abs/2406.11717)), runtime behavior links to the runtime's own documentation, and third-party tool settings link to the tool's documentation.
- **MolochAI behavior** follows the public documentation at [molochai.dev/docs](https://molochai.dev/docs?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai). If the docs and this guide disagree, open an issue.
- **If you are not sure something is true, leave it out.** No benchmark numbers of our own, no rankings or superlatives about models, no availability percentages, no invented prices: link [the pricing page](https://molochai.dev/pricing?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) instead.
- **Date what can change.** Model tables carry a "checked on" date; update it when you re-check.

## Writing style

Plain, specific and honest about limits, as one engineer explaining a system to another. Say "less-restricted" or "refusal-reduced", and use "uncensored" where people search for it, explaining that refusal behavior is reduced, that the model still sometimes declines, that it is not more accurate, and that the Acceptable Use Policy still applies. Avoid marketing words. Every code snippet must be correct for the API contract and should run against the mock server.

## Development

Requirements: Python 3.10 or later for `tools/compare_models.py` and its tests, Node 20 or later for Markdown linting, and optionally a checkout of [uncensored-ai-api](https://github.com/Moloch-AI/uncensored-ai-api) for the mock server.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -r requirements-dev.txt

ruff check .
ruff format --check .              # also checks Python code blocks in the docs
mypy
python -m pytest

npx --yes markdownlint-cli2@0.24.1
```

Integration tests against the mock server (from a checkout of `uncensored-ai-api`):

```bash
node mock-server/server.mjs --port 4010 --quiet
MOLOCHAI_MOCK_BASE_URL=http://127.0.0.1:4010/api/v1 python -m pytest tests/test_integration_mock.py
```

CI also runs the [lychee](https://lychee.cli.rs) link checker with `lychee.toml`, so new links must resolve.

## Code of conduct

This project follows the code of conduct in the Moloch-AI organization's [community health files](https://github.com/Moloch-AI/.github).
