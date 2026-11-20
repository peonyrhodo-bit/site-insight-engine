# Manual Director API — client migration guide (PR-C draft)

**Not deployed.** This guide describes proposed behavior in draft PR #73; existing production behavior has not been changed.

## Background versus manual execution
- `AUTONOMOUS_ENABLED=false` (default) disables the background wakeup worker in this PR.
- Explicit `POST /director/autonomous/run` is a separate privileged operation, permitted only when `DIRECTOR_MANUAL_RUN_TOKEN` is configured server-side and the request supplies a matching `X-Director-Run-Token` header.
- Without configuration or with a missing/invalid header the endpoint responds **403**. A valid token does not override the existing per-project concurrency guard (409) or backend failures (500).

## Operator setup — only after approval
1. Inventory and approve **server-side** callers. Confirm whether the endpoint is reachable from outside the trusted network and apply ingress restrictions.
2. Provision a high-entropy `DIRECTOR_MANUAL_RUN_TOKEN` through the deployment's approved secret manager. Never commit it to Git, send it in query parameters, put it in client-side JavaScript or print it in logs.
3. Update approved clients to send the `X-Director-Run-Token` header over HTTPS. Keep the token in server-side secret storage and establish rotation/revocation ownership.
4. Test with a disposable isolated deployment and stubbed Director; do **not** trigger a live cycle as a connectivity check.

Example request **for an approved isolated environment only** (placeholder values, not an executable production command):

```http
POST /director/autonomous/run?project_id=fixture-project HTTP/1.1
Host: isolated.example.invalid
X-Director-Run-Token: <secret-from-approved-secret-manager>
```

## Verification
- Missing server secret: 403.
- Missing/wrong header: 403; no cycle executes.
- Authorized request: normal cycle path and existing concurrency/idempotency protection.
- No background worker when `AUTONOMOUS_ENABLED=false`; worker only starts when true.
- Confirm no secret leaks in HTTP access logs, error responses or telemetry.

## CI coverage
- The repository's `.github/workflows/reliability-audit.yml` runs `python -m pytest -q`, so it discovers `tests/test_manual_director_http_contract.py` and `tests/test_manual_director_auth.py` by default.
- At commit `a83586ad088606b357857b6ea3ee45f407c6c42d`, four GitHub Actions workflows completed successfully. This does not validate external callers or deployed ingress configuration.

## Release decision
**No-go until** owner sign-off, caller inventory, ingress review, secret provisioning, isolated validation and rollback planning. Keep PR #73 draft and unmerged.
