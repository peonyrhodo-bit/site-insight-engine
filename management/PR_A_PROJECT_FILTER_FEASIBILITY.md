# PR-A — server-side project filtering feasibility (offline)

Status: design-only. No production queries, schema changes, migrations, deploys or new database privileges are authorized.

## Verified current behavior
- `SupabaseMemoryBackend._recent_for_project` requests pages of `select("*")`, orders by creation timestamp (and `id` as tie-breaker), and filters each row in Python.
- `_project_id_from_row` prioritizes the top-level `project_id`, then recursively searches legacy `data_json`. This matters for recommendations and system events.
- Consequently a project-specific limit does **not** bound the number of rows read across projects. A direct `.eq("project_id", project_id)` replacement may omit legacy rows and may fail if the column is missing on a table.
- Existing tests demonstrate compatibility and fail-closed errors; they do not measure live Supabase request volume or prove a safe migration.

## Options and decision
1. **Keep current paginated Python filter** (safe compatibility baseline, potentially expensive). Use until schema/data distribution is established.
2. **Server-side filter on top-level `project_id`** only after verifying the column exists and legacy rows are either backfilled or intentionally supported by a separate path. Not safe as a blind replacement.
3. **Dual-path read** (top-level column + legacy JSON): requires an explicit, documented legacy predicate, a deterministic combined sort/dedup, and proof that recursive Python project extraction semantics can be matched. A simple JSON path predicate may miss nested historical formats. Two independently limited queries cannot guarantee globally newest N without a correct merge and pagination strategy.
4. **Schema-backed canonical project field**: potential long-term solution, but requires a separate migration and owner authorization; not part of PR-A.

## Offline acceptance cases for any future implementation
- Mixed rows: current project in top-level column; legacy JSON-only project; unrelated project; conflicting top-level vs nested value (top-level wins).
- Pagination: sparse matching rows across many pages; same timestamp with distinct IDs; more than one page of matches; limit 1; no matching rows.
- Failure: page 2 errors, 402 quota, missing column, malformed JSON and partial response must not be silently returned as complete.
- Stable API response shapes and recommendation normalization; project isolation with no cross-project rows.
- Record read counts and bytes on synthetic fixtures before claiming any performance improvement.

## Required evidence before choosing option 2/3
- Review versioned schema for `recommendations` and `system_events`, including actual column existence and indexes; do not infer from Python payloads.
- Count and classify legacy `data_json` nesting **only in an explicitly authorized disposable environment** or via already-approved, non-sensitive offline fixtures.
- Show correctness equivalence for newest-N ordering across both formats.
- Explicit owner approval for any real database access or migration.

## Decision
**No code switch yet.** PR-A remains draft. Preserve current behavior until a server-side predicate can be proven equivalent without losing legacy data. Continue separately with PR-C only after this readiness gate is recorded.
