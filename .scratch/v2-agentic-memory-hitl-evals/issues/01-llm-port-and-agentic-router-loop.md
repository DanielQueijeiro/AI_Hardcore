# 01: LLM port and the model-driven Router loop

**What to build:** Replace flag-based routing with a Router that makes one typed call per step from what it has observed, specialists that run bounded tool loops, and a Critic that can send the answer back. Put every model call behind one port with an OpenAI Responses adapter, an offline policy and a scripted double.

**Blocked by:** none

**Status:** resolved

- [x] The Router re-plans from a specialist's observation (a telemetry code leads to a knowledge lookup for that code).
- [x] A Critic rejection sends the Router back, and it can gather more evidence before rewriting.
- [x] A draft that is still ungrounded after the allowed rounds is never sent.
- [x] A Router that never finishes is stopped by the step budget; identical delegations are refused.
- [x] A provider outage degrades to the offline policy and opens the breaker; the response says `degraded`.
