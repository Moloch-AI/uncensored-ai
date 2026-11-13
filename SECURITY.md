# Security policy

## Reporting a vulnerability in this repository

This repository holds documentation and a small command-line tool, `tools/compare_models.py`. To report a vulnerability in either, use GitHub private vulnerability reporting: open the repository's **Security** tab and choose **Report a vulnerability**. Please do not open a public issue for a security problem.

Include what you found, how to reproduce it, and what an attacker could do with it. We will acknowledge the report and keep you informed while we work on a fix.

## Problems with the hosted API

Security problems with the MolochAI service itself (the API, the dashboard or an account) are not handled in this repository. Report them through [molochai.dev/contact](https://molochai.dev/contact?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) and ask for a private conversation.

## API keys

Never post an API key in an issue, a pull request, a discussion or a log you share. MolochAI keys are not scoped: anyone who holds one can spend the account's quota, read account details and create invoices. If a key may have leaked, revoke it right away under [Account → API keys](https://dash.molochai.dev/account?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) and create a new one.

## Supported versions

Fixes are made on the `main` branch.
