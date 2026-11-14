# 04: Human review: interrupt, lease, decide, resume

**What to build:** Escalation interrupts the turn; operators claim with a lease and approve, reject or answer; the same turn resumes with the decision; approved writes execute once, in code.

**Blocked by:** 01, 02, 03

**Status:** resolved

- [x] Approve resumes the turn and creates exactly one service order; reject and answer resume without writing.
- [x] A second operator cannot claim or decide during a live lease, and can after it lapses.
- [x] An unanswered ticket times out and the conversation continues (sweeper and lazy check).
- [x] A paused review survives a restart.
- [x] The Router cannot attach an action the Support Agent did not propose; anonymous callers cannot open tickets.
