# Responsible use

A model with reduced refusal behavior will attempt more than a mainstream assistant. That is a statement about the model, not permission to do anything with it. This page explains what the MolochAI Acceptable Use Policy is for, the legitimate work these models are used for, and what an application that faces other people needs to add.

- [Model behavior and platform rules are separate](#model-behavior-and-platform-rules-are-separate)
- [What the Acceptable Use Policy covers](#what-the-acceptable-use-policy-covers)
- [Legitimate uses](#legitimate-uses)
- [If other people use your application](#if-other-people-use-your-application)
- [Security work needs authorization](#security-work-needs-authorization)
- [Data you send](#data-you-send)
- [Reporting misuse](#reporting-misuse)

## Model behavior and platform rules are separate

Most people who look for an uncensored model are not trying to do harm. They have a legitimate job that sits close to something a mainstream model was trained to avoid: a crime novel, a moderation queue, an incident report, a court file. Refusal-reduced models make that work possible, and they do it by declining less, not by judging better.

So the rules live outside the model:

- **The law** where you and your users are.
- **The platform's policy.** On MolochAI, the [Acceptable Use Policy](https://molochai.dev/acceptable-use?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) applies to every request, whatever the model would generate. A model complying with a request does not mean the request is allowed.
- **Your application's rules**, which you write and enforce, because the model will not reliably enforce them for you.

## What the Acceptable Use Policy covers

The policy text is the authority; read it before you build, particularly if your application faces the public. In outline, it prohibits using the service to create, or help create or carry out:

- Child sexual abuse material, or any sexual content involving minors, with no exception for fiction.
- Weapons capable of mass casualties, including chemical, biological, radiological and nuclear weapons.
- Attacks on systems you are not authorized to test, including malware for deployment against others and attacks on critical infrastructure.
- Credible threats, incitement, or planning violence against people.
- Fraud and deception: phishing, scams, impersonating real people or organizations to mislead, fake reviews, fraudulent documents.
- Harassment, stalking, doxxing, and non-consensual sexual content about real people.
- Anything else illegal where you or your users are, or that infringes other people's rights.

It also covers platform abuse, such as reselling raw access as your own API, sharing credentials outside your organization, and getting around quotas, rate limits or billing. If there is evidence that an account broke the policy, MolochAI may warn, suspend or close it, and may report activity to the authorities where the law requires it or where there is a serious risk to people.

## Legitimate uses

These are the kinds of work refusal-reduced models are used for, each with the limits that stay. MolochAI's site has a guide for each.

| Use | What the model makes possible | What stays with you |
| --- | --- | --- |
| [Fiction and creative writing](https://molochai.dev/uncensored-ai/creative-writing?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) | Villains who stay villains, violence on the page, period-accurate dialogue, without scenes softened or cut away. | Three lines hold in fiction too: no sexual content involving minors, no sexual content about real people, no text meant to harass or deceive a real person dressed up as a story. |
| [Roleplay and character apps](https://molochai.dev/uncensored-ai/roleplay?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) | Personas that hold, antagonists that antagonize, mature themes for adults. | Platform rules first in every request, age assurance, no minors ever (including characters described as such), no real people, reporting and review. |
| [Trust and safety](https://molochai.dev/uncensored-ai/trust-and-safety?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) | Labeling reports with exact quotes, generating hard test cases for classifiers, red-teaming your own assistant. | People decide removals, appeals and anything involving minors; red-team only systems you own or may test; check a model judge against people. |
| [Security research](https://molochai.dev/uncensored-ai/security-research?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) | Explaining recovered scripts, CVE root causes, detection drafts, pentest write-ups, teaching. | Authorization for any testing; verifying CVE details, tool flags and attributions; reading generated code before running it, and only in scope. |
| [Sensitive documents](https://molochai.dev/uncensored-ai/sensitive-documents?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) | Summaries and extractions of testimony, case files, propaganda archives and drug-forum research data without silent sanitizing. | Verbatim-quote checks, a person accountable for every fact, confidentiality. Output is working material, not legal or medical advice or evidence. |
| Research on model behavior | Running prompt sets through several refusal-reduced models and reading reasoning traces, without a GPU stack. | Not suited to reproducible benchmarks: no version pinning, no seed, builds can change. |

## If other people use your application

With a mainstream model, some moderation happens inside the model whether you want it or not. With a refusal-reduced one that layer is thinner, and the responsibility moves to you. The policy applies to what your users send through your account, and you answer for it. A starting checklist:

- [ ] **Rules in the system message.** Scope, audience and what is never allowed, sent first in every request. Do not rely on the model to decline.
- [ ] **Input checks.** Screen what users submit against your rules before it reaches the model.
- [ ] **Output checks.** Screen what comes back before you show it, publish it or act on it.
- [ ] **Age assurance** where your product allows adult content, as the law where your users are requires.
- [ ] **AI disclosure** where it is required, and no presenting output as professional medical, legal or financial advice.
- [ ] **Reporting.** A way for users to flag output, and someone who reads the flags.
- [ ] **Your own records.** Evidence of abuse on your platform has to come from your systems.
- [ ] **Per-user limits.** All your users share one account's rate limit and quota; meter them yourself.
- [ ] **A privacy notice** that says user content is sent to a third-party API.
- [ ] **The key on your server**, never in a browser or app ([architecture](building-applications.md#architecture-keep-the-key-on-your-server)).

The same applies to a shared install of a front-end such as Open WebUI, SillyTavern or LibreChat: other people's chats run on your account.

## Security work needs authorization

Defensive security, education and research are welcome under the policy, and so is testing you are authorized to do: a signed engagement, a bug bounty scope, your own systems, a capture-the-flag event. Authorization is yours to have and to prove; without it, offensive work falls under the prohibitions above. A model writing an exploit proof of concept is not permission to use it.

## Data you send

Prompts often contain other people's data: report text, case files, customer messages. Before you send any of it:

- Strip direct identifiers when the task does not depend on them, and keep credentials and secrets out of prompts and tool arguments.
- Know where it goes. Requests pass through the gateway to inference servers; the [Privacy Policy](https://molochai.dev/privacy?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) lists what is recorded and which services are involved.
- No data processing agreement is offered, and the service is not set up for regulated health records. If your obligations require either, they decide the question; [self-hosting](deployment-options.md) keeps prompts on hardware you control.

## Reporting misuse

To report misuse of the service, use the channels on the [contact page](https://molochai.dev/contact?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai) and ask for a private conversation. Do not post evidence, prompts or keys in public issues.
