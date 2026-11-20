# PR-B isolated PostgreSQL harness: readiness gate

This draft PR is a **test-only** companion to PR #71. It is not a
production migration or evidence of live PostgreSQL transaction safety.

## Verified CI checkpoint

Commit `6a06342432d065085e4b607833951375a0430021`:
- Reliability audit run 44752476212: **189 passed, 1 skipped** (full suite).
- Explicit fixture/DSN checks: **9 passed, 1 skipped**.
- PR-B characterization: **16 passed**.
- Supabase backend regression run 44752476393: success.

The skipped test is the deliberately disabled integration placeholder.
The static fixture assertions verify SQL text only; they do **not** prove
that the schema or concurrency semantics work in PostgreSQL.

## Before enabling real integration tests

1. Obtain explicit owner approval for a disposable local PostgreSQL
   instance and for executing fixture SQL **only in that instance**.
2. Require a loopback DSN with a `pr_b_test_` database name and separate
   test-only credentials. Verify database identity **after connecting**
   (e.g. `current_database()`) before any DDL. Do not log credentials.
3. Add a narrowly scoped SQL transaction implementation and review
   authorization, project isolation, partial-unique-index behavior,
   request fingerprint handling, fencing, crash recovery and permissions.
4. Run at least two independent connections with deterministic barriers.
   Cover PG-01 through PG-15 in
   `management/PR_B_IDEMPOTENCY_LOOKUP_GATE.md`.
5. Preserve the fail-closed skip until the database and SQL implementation
   are explicitly approved. Do not enable production connections or
   silently retry a potentially side-effecting Director cycle.
6. Record PostgreSQL version, schema hash, CI run, and anonymized query
   plans. Require a separate owner decision for any merge or migration.

## Known limitations

- No SQL executed; no PostgreSQL integration assertions passed yet.
- `pr_b_isolated_schema.sql` is an illustrative fixture, not a deployable
  production migration.
- The local DSN gate is a defense-in-depth preflight, not a replacement
  for verifying the connected database's identity and role.
- PR #72 targets the PR #71 design branch; it must not be merged
  independently into production.
