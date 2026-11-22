# PR-C #73 — manual trigger compatibility and release gate

Status: **draft; do not merge or deploy without owner approval**.

## Behavior change
- `AUTONOMOUS_ENABLED=false` prevents the background scheduler worker from starting. It does **not** control explicit manual API calls.
- `POST /director/autonomous/run` now requires the `X-Director-Run-Token` request header to match the non-empty server-side `DIRECTOR_MANUAL_RUN_TOKEN` environment variable.
- Missing server configuration, missing header or wrong token returns HTTP 403. Existing unauthenticated clients will break if this change is deployed.
- The token is a secret: provision it through approved secret management, never in Git, browser code, query strings or logs. Use HTTPS and restrict network exposure independently.

## Verified checks
- Commit `3e5ae5751e4da7bae55aad4d546a2f7b3b179e82`: four CI workflows succeeded (Director lifecycle, Reliability audit, Supabase backend regression, history pagination).
- Offline tests cover missing configuration, missing/incorrect header and authorized delegation to a stubbed executor.
- No real autonomous cycle or production credential was used in those tests.

## Open compatibility questions — must be answered before deployment
1. Inventory every caller (scheduled jobs, scripts, dashboards, webhooks and external integrations) of `POST /director/autonomous/run`. GitHub search results alone cannot establish there are no callers.
2. Confirm whether ingress/API gateway already authenticates callers, and whether this route is externally reachable. No application-level authorization was found on this route in the reviewed `server.py`.
3. Agree with the owner on the operator(s) permitted to trigger a cycle and on token rotation/revocation procedures.
4. Update approved server-side clients to send the header; avoid exposing the token in browser-delivered code.
5. Validate unauthorized 403, authorized run, project concurrency 409 and error propagation in a disposable environment; measure and inspect logs for accidental token disclosure.
6. Confirm a rollback revision and that `AUTONOMOUS_ENABLED` and `DIRECTOR_MANUAL_RUN_TOKEN` are correctly set before any authorized release.

## Rollout / rollback
- Owner approves a maintenance window and identifies affected clients; prepare the token and client changes **before** application rollout.
- Deploy only to an authorized isolated environment first; verify manual and background behavior separately.
- Halt if a legitimate client unexpectedly receives 403, an unauthorized request succeeds, or a background cycle starts while disabled.
- Roll back to the previously approved application revision and revoke/rotate the new token if compromised. Reassess the security exposure of the previous revision before restoring public access.

## Decision
**No-go for automatic production release.** CI is green; caller inventory, external exposure assessment, secret provisioning and owner sign-off remain outstanding.
