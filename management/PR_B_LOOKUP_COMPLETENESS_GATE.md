# PR-B — complete idempotency lookup: data contract and decision gate

Status: **design only; no production query-path switch or schema migration approved**.

## Verified from repository code
- `server._find_completed_idempotent_run` currently reads the run history via `_recent_for_project(..., limit=None)` and checks `row.idempotency_key or row.data_json.idempotency_key` in Python.
- `memory.supabase.SupabaseMemoryBackend.save_run` stores the run payload in `data_json` and promotes only a defined subset of fields to columns; `idempotency_key` is **not** among the promoted fields in this adapter.
- The experimental `get_idempotency_run_candidates` filters JSON objects by key and then validates project IDs, including nested legacy project IDs. It is not wired to the Director.
- The existence, types, nullability, historical population and indexes of any dedicated `director_runs.idempotency_key` column are **not established** by this repository inspection.

## Completeness requirement
For a given normalized project ID and idempotency key, the lookup must find **every** persisted run that the current full-history scan would consider. An empty candidate list must not be treated as permission to execute if any legacy representation could be missed. Preserve fail-closed behavior on database errors.

## Safe target design (subject to schema and data review)
1. Inventory real table columns, JSON shapes, project ID representations, duplicate keys and historical row counts through **read-only, owner-approved** inspection. Do not infer schema from application field names.
2. Define a canonical persisted project/key pair for all future runs and a migration/compatibility plan for historical records. Assess whether a composite unique constraint can represent the desired retry semantics.
3. Implement a targeted database-side lookup that covers both canonical columns and approved legacy JSON forms. Validate query semantics and indexes with an isolated PostgreSQL fixture before changing the runtime.
4. Compare targeted lookup against the existing full-history algorithm on representative fixtures, including mixed projects, completed/failed/in-progress runs, duplicate keys, nulls, legacy nested fields, and read failures.
5. Only after equivalence is demonstrated, wire the new lookup behind a separately reviewed rollout gate; keep the current fail-closed behavior until then.

## No-go conditions
- Unknown legacy key locations or unmatched historical records.
- Missing proof that the candidate query is complete.
- Silent fallback to `[]` after query failure.
- Change that could start a duplicate cycle when a matching prior run exists.
- Production migrations, live SQL, deploy or merge without explicit owner authorization.

## Current decision
Keep `get_idempotency_run_candidates` isolated and do not replace `_find_completed_idempotent_run`. This is a correctness prerequisite, not just a performance optimization.
