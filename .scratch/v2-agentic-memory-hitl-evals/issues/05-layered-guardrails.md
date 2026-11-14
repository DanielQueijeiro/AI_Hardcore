# 05: Layered guardrails and untrusted data

**What to build:** Normalized/decoded lexical screen, LLM classifier that fails open, sanitization of retrieved/web/operator text, output leak checks.

**Blocked by:** 01

**Status:** resolved

- [x] Base64, leetspeak, zero-width and separator obfuscation are blocked in EN/PT/ES.
- [x] Instructions embedded in a retrieved document or a web result do not reach the answer.
- [x] The real corpus passes through the sanitizer unchanged.
- [x] A leaked prompt canary or another tenant's identifier is stopped at the output.
