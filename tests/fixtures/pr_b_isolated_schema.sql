-- PR-B disposable PostgreSQL fixture DRAFT. DO NOT APPLY TO PRODUCTION.
-- Requires separate owner approval before execution, even on a test DB.
-- This file defines only isolated test tables; not a production migration.
BEGIN;

CREATE TABLE pr_b_reservations (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id text NOT NULL CHECK (length(trim(project_id)) > 0),
    idempotency_key text NOT NULL CHECK (length(trim(idempotency_key)) > 0),
    request_fingerprint text NOT NULL,
    status text NOT NULL DEFAULT 'requested'
        CHECK (status IN ('requested', 'running', 'completed', 'failed')),
    result_json jsonb,
    fencing_generation bigint NOT NULL DEFAULT 1
        CHECK (fencing_generation > 0),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pr_b_project_key_unique UNIQUE (project_id, idempotency_key),
    CONSTRAINT pr_b_terminal_result_consistency CHECK (
        status <> 'completed' OR (
            result_json IS NOT NULL
            AND jsonb_typeof(result_json) = 'object'
            AND result_json <> '{}'::jsonb
        )
    )
);

CREATE UNIQUE INDEX pr_b_one_active_per_project
    ON pr_b_reservations (project_id)
    WHERE status IN ('requested', 'running');

-- No SECURITY DEFINER, no RPC, no grants, no triggers in this draft.
-- Actual reservation and completion transactions remain to be designed
-- and reviewed against project authorization, fencing and crash recovery.
COMMIT;
