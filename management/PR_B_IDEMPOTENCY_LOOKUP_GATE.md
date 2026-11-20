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

## Live read-only schema audit — 2026-11-20

Project: `site-insight-memory` (`oxbxnswywgpdlcfltmbq`), `public.director_runs`.
- 159 rows; **0** rows with non-empty `data_json->>'idempotency_key'` at audit time. This is a snapshot, not a guarantee that no future or alternate database has legacy keys.
- Columns include `id`, `project_id`, `status`, `created_at`, `updated_at`, `data_json`; **no top-level `idempotency_key` column**.
- Existing indexes:
  - `director_runs_pkey` on `id`;
  - `director_runs_one_active_per_project_idx`: **unique `project_id` WHERE `status IN ('requested','running')`**;
  - `director_runs_status_updated_at_idx` on `(status, updated_at DESC)`;
  - `idx_director_runs_created_at` on `(created_at DESC)`.
- No indexed `(project_id, idempotency_key)` lookup exists. The current one-active-per-project invariant is independent of key-level idempotency and **must remain intact**.
- RLS reported disabled on this table; security/role exposure review is required before any schema or API design changes.
- Only metadata/schema and aggregate counts were queried. **No migrations, updates, deletes, deployment or runtime calls**.

Design implication: prefer a migration-reviewed durable keyed lookup with a careful compatibility path for nested JSON keys; do not assume legacy-key absence outside this observed snapshot.
