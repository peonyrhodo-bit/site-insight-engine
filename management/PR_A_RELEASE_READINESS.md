# PR-A #70 — readiness, validation and rollback gate

Status: **draft / no production authorization**. Scope: targeted read paths for recommendations and events. This checklist is not permission to merge, deploy or access live Supabase.

## Verified offline baseline (2026-11-20)
- Branch `fix/memory-targeted-api-reads-pr-a-20261120`, tip `53ede2bc08f6d4d6834ab23c2d62ebdd0a29d5aa`.
- Compared with `main`: 8 commits ahead, 0 behind; changed files: `server.py`, `memory/director_adapter.py`, `memory/supabase.py`, `tests/test_targeted_memory_reads.py`.
- GitHub Actions at tip: Reliability audit, Supabase backend regression, Supabase history pagination and Director lifecycle succeeded. Reliability suite reported 175 passed.
- No review approvals recorded. These are offline CI results, **not** evidence of lower live Supabase load.

## Scope and non-goals
- Verify that recommendations and events endpoints request only their own collections, preserve project isolation and API response shapes.
- Preserve fail-closed handling of storage failures and partial page reads; never turn a Supabase 402, timeout or incomplete page into a successful empty response.
- **Not fixed here:** `ServerMemory.create_run` active-run history scan, `_find_completed_idempotent_run` historical idempotency lookup, transactional reservation and global Supabase storage quota. These remain separate work.

## Gate 1 — offline (no credentials or network)
- [x] Four relevant workflow families green at the recorded tip.
- [x] Tests cover targeted recommendations/events, API compatibility, project isolation, backend failure and partial page failure.
- [ ] Re-run required checks on the **final** reviewed SHA before any merge proposal.
- [ ] Review fallback paths and pagination limits to ensure no unbounded or silent full-context read was introduced.
- [ ] Record reviewer approval and explicit owner approval before any merge.

## Gate 2 — separately authorized isolated validation
Use only disposable fixtures or a specifically approved non-production environment; do not use live project credentials by default.
- Compare old vs new endpoint response keys, ordering, limits, project filtering, empty projects and legacy rows.
- Inject a 402/quota error, timeout and second-page error. Expect an explicit failure, never `[]` with HTTP success.
- Measure per-request SQL/API calls, rows transferred, bytes and p95 latency for equal synthetic workloads. Record before/after evidence; do not invent improvement percentages.
- Verify that other Memory 2.0 collections and autonomous Director cycle paths are unchanged.

## Gate 3 — production (requires new explicit owner approval)
- Capture a baseline for endpoint error rate, request count, p95 latency, Supabase egress/reads and quota state.
- Plan a reversible release of the reviewed SHA only; define observation window and responsible operator.
- Halt/rollback on any cross-project leak, wrong API shape, missing data, newly hidden storage error, material error-rate increase or resource regression.
- Rollback means redeploying the previously verified application revision; do not reverse or modify database schema as part of PR-A (none is required).
- Re-run smoke checks and compare against baseline after rollback. Escalate persistent Supabase 402 separately; PR-A alone cannot resolve exhausted storage.

## Decision
**No-go for automatic deployment.** Offline CI is green, but reviewer/owner approval and authorized environment validation are outstanding.
