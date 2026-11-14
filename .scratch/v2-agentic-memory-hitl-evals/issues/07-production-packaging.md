# 07: Non-root image, CI, migrations, readiness

**What to build:** Multi-stage non-root read-only image, CI pipeline, numbered migrations, separate liveness and readiness, online backup.

**Blocked by:** none

**Status:** resolved

- [x] The container runs as uid 10001 with a read-only root filesystem and serves the challenge payload.
- [x] CI runs lint, tests, the offline eval gate and a container smoke test.
- [x] Schema changes are applied by numbered migrations at startup.
- [x] `/ready` reports database, migration, index and breaker state.
