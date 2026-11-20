# PR-B — durable idempotency lookup: implementation gate

Status: **design-only / no runtime changes**. Owner approval required for schema migration and production deployment.

## Verified baseline
- `server.py::_find_completed_idempotent_run` calls `backend._recent_for_project(TABLE_RUNS, limit=None, ...)`. This reads all historical run rows and `data_json`, then scans in Python.
- `memory/supabase.py::save_run` stores `idempotency_key` and `idempotency_status` inside `data_json`, not promoted to indexed top-level fields.
- `update_run` reads and rewrites `data_json` to update status/result.
- The existing semantics are: same project+key and `completed` with dictionary result -> replay; `failed`/`in_progress` -> HTTP 409; read failure -> HTTP 503 (fail closed). Older keys must remain discoverable.

## Proposed implementation (after schema review and approval)
1. Inspect current `director_runs` schema, row-level security, existing indexes, duplicate historical keys and query plans **read-only**.
2. Design a durable keyed lookup on `(project_id, idempotency_key)` with a unique constraint / atomic reservation where feasible. Account for legacy keys nested in `data_json`, and do not silently ignore them.
3. Separate small metadata lookup (key, project, status, run ID) from fetching a **single** matched run's `result`; avoid downloading `data_json` for unrelated runs.
4. Use a dedicated method in `memory/` and thin call from `server.py`. Keep all error/409/503 behavior and legacy replay compatibility.
5. Ensure cross-process atomicity; local in-memory request lock is insufficient. No new YouTube calls during lookup.
6. Only after reviewing migration/backfill and rollout plan, request explicit owner authorization for schema changes and implementation.

## Required offline regression gates
- Same key + project completed returns exactly the original result, including after restart.
- Same key in different projects remains independent; historical rows with nested-only keys remain searchable.
- Failed/in-progress statuses reject with 409; database outage/partial read rejects with 503.
- Concurrent identical requests cannot both reserve work (DB-level atomicity).
- Query uses indexed key lookup; no unbounded `select(*)`/full-history downloads.
- Existing PR #67 protected-memory fail-closed behavior and PR #69 run refs remain independent.
- Performance check: compare query plan and transferred bytes against old full-history path, without claiming production savings before measurement.

## No-go conditions
Do not implement an arbitrary last-100/last-N scan, rely only on process-local cache, create a new column without backfill/compatibility, or introduce a migration without owner approval.
