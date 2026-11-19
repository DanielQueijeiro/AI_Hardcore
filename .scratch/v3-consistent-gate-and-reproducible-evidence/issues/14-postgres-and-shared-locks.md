# 14: Postgres checkpointer and shared locks (optional)

**What to build:** Lift the single-worker limit: LangGraph Postgres checkpointer, Postgres for the ops store, Redis
for the login limiter and per-thread locks, behind a docker-compose profile. CI runs the memory and HITL tests
against both backends with two workers.

**Blocked by:** none

**Status:** needs-info (in scope or not)

- [ ] `docker compose --profile scale up` runs two API workers behind one port.
- [ ] Memory, restart and HITL lease tests pass against SQLite and Postgres.
- [ ] A conversation started on one worker continues on the other; one ticket claim wins across workers.
