# YouTube Director 3.0 — acceptance test plan

This plan is for validating the autonomous research cycle without touching production. Run automated tests in CI first; run live acceptance checks only against a disposable/staging environment with explicit quota limits.

## 1. Researcher behavior

- [ ] Start with existing cached data and an objective; confirm the Director analyzes available evidence even when new YouTube research is unavailable.
- [ ] Keep evidence sufficiency false when a research task or per-cycle budget is exhausted; record the remaining evidence gaps and a useful next step.
- [ ] Confirm a recommendation cites the observations that support it and distinguishes facts, hypotheses, and unknowns.
- [ ] Confirm contradictory evidence can lower confidence or change the hypothesis rather than being ignored.
- [ ] Confirm the next cycle chooses a distinct useful task instead of repeating completed task keys or the same failed query indefinitely.

## 2. Research execution and persistence

- [ ] Verify every planned operation is either executed or explicitly marked blocked/skipped/failed with a reason.
- [ ] Verify malformed MCP responses fail visibly and are not recorded as successful research.
- [ ] Verify zero-result searches are persisted as zero-result outcomes, not treated as evidence of absence.
- [ ] Verify successful search results, query records, research-set records, snapshots, and data relations are persisted and retrievable.
- [ ] Verify a partial write or dependency failure produces an honest partial/failed status and can be retried without duplicating completed work.
- [ ] Verify stale-video refresh uses each video's latest successful snapshot and does not perform unnecessary search calls.

## 3. Timeouts, quotas, and degraded mode

- [ ] A handler that never returns times out within the configured bound and records an actionable failure.
- [ ] When the quota ledger is unavailable, outbound YouTube calls fail closed before reaching the MCP; cached-data analysis remains possible.
- [ ] When the quota ledger is available, authorization, completion/failure accounting, and quota reconciliation work for success, error, timeout, and cancellation paths.
- [ ] Exhausted quota leads to a useful analysis/wait state, not an infinite retry loop or a false claim that evidence is sufficient.
- [ ] Retryable upstream failures use bounded retries/backoff; permanent errors do not loop.

## 4. Memory and long-running reliability

- [ ] Measure peak RSS for a representative cached dataset and for a full autonomous wake; record baseline and post-change values.
- [ ] Test a large dataset and confirm reads/analysis are bounded or chunked instead of materializing unbounded duplicate copies.
- [ ] Confirm the process handles cancellation/shutdown cleanly and does not leave a cycle permanently marked running.
- [ ] Run repeated cycles and verify memory does not grow monotonically and old cycle state does not leak into the next wake.

## 5. Release gate

Do not call the release validated until:
1. CI is green on the exact candidate commit.
2. The service starts in staging with valid configuration.
3. Cached-data-only mode passes with quota storage intentionally unavailable.
4. A quota-enabled, tightly capped live test completes at least one search and verifies persisted results.
5. One end-to-end objective reaches analysis/recommendation with traceable evidence and a recorded next action.
6. Logs show no repeated task loop, unhandled timeout, or out-of-memory termination during the test window.

Record candidate commit, environment, test timestamp, quota spend, result IDs, and failures. Never paste credentials or connection strings into logs, issues, or chat.
