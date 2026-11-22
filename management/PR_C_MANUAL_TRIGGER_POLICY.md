# PR-C — autonomous mode and manual trigger policy

Status: draft security/operations contract. No deploy, merge or production authorization.

## Observed behavior
- `AUTONOMOUS_ENABLED` defaults to false.
- PR-C gates creation of the background wakeup worker on this flag.
- `POST /director/autonomous/run` calls `_execute_autonomous_cycle` without checking `AUTONOMOUS_ENABLED`.
- The endpoint therefore remains a separate explicit trigger. This is intentional scope separation, **not proof of authorization or exposure safety**.

## Proposed policy
1. `AUTONOMOUS_ENABLED` controls only periodic unattended scheduling.
2. Explicit manual execution should remain possible **only if** request authentication and authorization are verified against the deployment's intended operators. Do not assume an upstream gateway exists.
3. If no adequate manual-run authorization is present, fail closed at the endpoint or deployment ingress before exposing the service. A separate `MANUAL_DIRECTOR_RUN_ENABLED` flag may be appropriate, but do not add a permissive flag without reviewing existing auth and tests.
4. Manual and background triggers must share concurrency/idempotency guards. A manual request must never bypass the active-project lock.
5. Record who/what initiated a run and whether it was manual or scheduled without logging secrets.

## Before implementation
- Inventory API authentication middleware, gateway and route permissions for `/director/autonomous/run`, including whether the endpoint is publicly reachable.
- Write offline tests for unauthorized caller, authorized caller, flag-off background behavior, active-run conflict, and backend failure.
- Confirm owner-approved policy for manual runs, then implement a narrowly scoped fail-closed gate in a separate reviewed commit.
- Never test against production or invoke a real Director cycle as part of this draft.

## Decision
PR-C #73 fixes background startup only. **Manual HTTP trigger security remains an open release blocker until verified.**
