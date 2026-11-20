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

## Proposed SQL design — review only, NOT authorized for execution

Preferred approach: add nullable `idempotency_key text` to `public.director_runs`, maintain a partial unique btree index on `(project_id, idempotency_key)` where both are non-null, and populate the column atomically when reserving a keyed run. Preserve `director_runs_one_active_per_project_idx` unchanged.

**Migration prerequisites:**
1. Inspect null/blank project IDs, duplicate `(project_id, data_json->>'idempotency_key')` combinations, and active rows. The 2026-11-20 audit found zero keyed legacy rows, but validate again immediately before migration.
2. Define explicit normalization: request keys are trimmed at the HTTP boundary; empty strings do not reserve. Project IDs must be non-null for keyed reservations. Treat existing historical JSON keys with exactly the same semantics as current code.
3. Backfill top-level keys from `data_json` in batches or one transaction only after inspecting duplicates; do not silently drop duplicate historical keys or auto-delete rows. Historical duplicate semantics currently depend on created-at order and need a deterministic conflict policy before a unique index.
4. Establish transaction-safe reservation: `INSERT ... ON CONFLICT` alone is insufficient if another per-project active run already exists; map conflicts to existing 409 behavior and avoid a second Director cycle. The existing unique active-per-project index and new unique keyed index enforce distinct invariants.
5. Ensure completion/failure updates persist `idempotency_status` and `result` consistently; use an indexed metadata-only lookup by `project_id` and `idempotency_key`, then fetch only the matched row's `data_json` if replaying.
6. Fail closed if migration/lookup is unavailable; never fall back to an unbounded full-history scan in production. If compatibility is needed during rollout, use a separately approved bounded/indexed legacy strategy.

### Illustrative SQL, **not a migration**

```sql
-- PROPOSAL ONLY. DO NOT RUN WITHOUT OWNER APPROVAL AND PRE-FLIGHT CHECKS.
ALTER TABLE public.director_runs ADD COLUMN idempotency_key text;

-- After validated backfill, duplicates audit and rollout plan:
CREATE UNIQUE INDEX director_runs_project_idempotency_key_uq
  ON public.director_runs (project_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL AND project_id IS NOT NULL;
```

**Security gate:** the audit reported RLS disabled on `public.director_runs`. Verify Data API exposure, service credentials, privileges, and the intended per-project authorization model before rollout; never treat a project filter alone as access control.

**Rollout gate:** agree on rollback (application compatibility with old schema, index removal strategy, handling in-flight runs), staged test environment, query-plan verification and production egress measurement. Migration and deployment remain separately owner-approved.

## Request lifecycle trace and additional correctness gates

Read-only code trace from `server.py` (main branch, 2026-11-20):

- Both GET and POST Director run endpoints call `_run_director`.
- `_run_director` trims a nonempty key, builds `f"{project_id}:{key}"`, uses `_DIRECTOR_REQUEST_LOCKS.setdefault(..., asyncio.Lock())`, then checks `_DIRECTOR_REQUEST_RESULTS` (process-local dict). **Neither cache nor lock is shared between Render processes.**
- A cache miss invokes `_find_completed_idempotent_run` (current unbounded Supabase read), then `_run_director_once`.
- `_run_director_once` reserves a run with nested `idempotency_key` and `idempotency_status="in_progress"`; on success, updates nested status to `completed` and persists full `result`; on failure, attempts to mark it `failed`.
- `_find_completed_idempotent_run` rejects `failed` and `in_progress` with 409, replays `completed` only when `result` is a dict, and raises 503 on a history read failure.

**Correctness risks to resolve before implementation:**

1. **Atomicity:** `lookup -> create_run` is not an atomic transaction. The existing unique partial index on active project status limits simultaneous active runs but does not replace a durable uniqueness guarantee for completed keys. Define how concurrent processes distinguish same-key conflict, different-key active run, and completed replay.
2. **Status ambiguity:** a keyed row marked `completed` with missing/non-dict `result`, or with an unknown status, is currently skipped and may allow another run. New implementation must choose and test fail-closed behavior; do not silently treat malformed historical state as no match.
3. **Cache consistency:** process-local `_DIRECTOR_REQUEST_RESULTS` may replay a cached result without a fresh database check. Define when it is safe, how stale state is handled, and whether unbounded cache/lock growth should be separately addressed.
4. **Update failure:** after successful Director work, a failure to persist `completed` must not be interpreted as successful durable idempotency. Verify `runtime.memory.update_run` return/error semantics and test partial persistence.
5. **Legacy behavior:** project-scoped replay must preserve the exact saved result; compare nested-only keys, missing project IDs, and historical duplicates explicitly.

**Review decision requested:** before any migration, approve a concrete reservation protocol and conflict/status matrix (same key vs different key; active vs completed vs failed vs malformed; same project vs another project), not merely an index.

## Write-path audit — second unbounded read discovered

The `ServerMemory.create_run` method in `memory/director_adapter.py` independently performs another `_recent_for_project(TABLE_RUNS, limit=None, project_id=...)` before inserting a run. **Optimizing only `server.py::_find_completed_idempotent_run` will not remove full-history reads from the Director start path.** This must be accounted for in PR-B scope and egress estimates.

Current `create_run` logic:
- Scans historical runs to identify `requested`/`running` rows.
- Determines staleness from `updated_at`, `started_at`, `created_at` (including nested JSON fallbacks). Missing or malformed timestamps are conservatively considered active.
- Marks an old active row `failed` when its timestamp exceeds `DIRECTOR_RUN_STALE_TIMEOUT_SECONDS` (minimum 60, default 1800), then inserts a new row.
- On insert, converts unique-index errors into `DirectorCycleAlreadyRunning` (HTTP 409 at the caller); other failures propagate.
- **Race risk:** stale cleanup and insertion are separate operations; a long-running process without a heartbeat could be marked failed and overlapped. Keep the current conservative missing-timestamp behavior; evaluate a transactional/conditional stale claim before changing semantics.

Write-result audit:
- `ServerMemory.update_run` propagates backend errors and raises if the result is not exactly `True`.
- `SupabaseMemoryBackend.update_run` first selects the matched row's `data_json`, merges fields client-side, then updates by `id` and selects `id`. This is a **read-modify-write race**: concurrent updates can overwrite JSON changes.
- `ServerMemory.save_run` (non-reservation path) catches exceptions and returns `None`, unlike `create_run`. Do not accidentally use this best-effort path for durable idempotency.
- Successful keyed cycle writes `idempotency_status="completed"` and `result` through `update_run`; failures attempt to persist `failed`, logging if that update fails. This must remain fail-closed for retries.

### Revised implementation gate
PR-B should address **both** full-history readers on the keyed Director start path: (1) lookup by key and (2) active-run detection in `create_run`. Use indexed, narrow active-run metadata queries preserving the existing partial unique active-project index, and a safe transactional stale-resolution protocol. Avoid changing stale timeout semantics without separate review. Add tests for the second read, update races, stale claims, and persistence failures.

No runtime code, migrations, SQL writes or production changes authorized.
