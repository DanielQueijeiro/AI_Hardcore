# 0012. Layered guardrails; retrieved and tool text is data

Status: accepted (amends 0002)

Regex alone was the first version's defence and the review noted how easily it is bypassed. The layers now are:

1. Deterministic input screen over normalized views of the message (NFKC, zero-width removal, leetspeak, separator stripping, decoded base64) in English, Portuguese and Spanish. Cheap, always on, catches the bulk.
2. LLM classifier with a typed verdict, given the message as tagged data. It catches paraphrase the patterns miss. It fails open to layer 1: a classifier outage must not take support down, and layer 4 holds regardless.
3. Untrusted-data handling. Retrieved passages, web results and operator notes are sanitized (instruction-like sentences removed, delimiter tags neutralized) and placed inside tagged blocks that every prompt declares to be data. The patterns for embedded instructions are stricter than for user input because a document has no reason to address the assistant.
4. Structural controls: per-agent tool allow-lists, principal-scoped tools, human-gated writes (0009, 0011).
5. Output checks, fail-closed: a canary present in every system prompt, other tenants' identifiers, credential-shaped strings.

Layer 4 carries the security argument. The adversarial suite measures all of them together, including poisoned documents and tool output, and includes benign controls so that tightening a pattern shows up as a false positive.
