-- REVIEW ONLY. Disposable local pr_b_test_* PostgreSQL ONLY, after owner approval.
-- Requires pr_b_isolated_schema.sql; not wired to application or production.
-- Caller must authorize project_id and verify DB identity before executing.
CREATE OR REPLACE FUNCTION pr_b_test_reserve(
    p_project_id text,
    p_idempotency_key text,
    p_fingerprint text
) RETURNS TABLE(outcome text, reservation_id bigint, generation bigint, replay_result jsonb)
LANGUAGE plpgsql
SECURITY INVOKER
AS $function$
DECLARE
    v_id bigint;
    v_generation bigint;
    v_fingerprint text;
    v_status text;
    v_result jsonb;
BEGIN
    IF nullif(btrim(p_project_id), '') IS NULL
       OR nullif(btrim(p_idempotency_key), '') IS NULL
       OR nullif(btrim(p_fingerprint), '') IS NULL THEN
        RAISE EXCEPTION 'project, key, and fingerprint required'
            USING ERRCODE = '22023';
    END IF;

    -- ON CONFLICT covers both the project/key unique constraint and the
    -- one-active-per-project partial unique index. The follow-up SELECT is
    -- a separate internal SQL statement, but visibility under concurrent\n    -- commits must be verified by a subsequent caller-side statement.
    INSERT INTO pr_b_reservations (
        project_id, idempotency_key, request_fingerprint, status
    ) VALUES (p_project_id, p_idempotency_key, p_fingerprint, 'requested')
    ON CONFLICT DO NOTHING
    RETURNING id, fencing_generation INTO v_id, v_generation;

    IF FOUND THEN
        RETURN QUERY SELECT 'reserved'::text, v_id, v_generation, NULL::jsonb;
        RETURN;
    END IF;

    SELECT r.id, r.fencing_generation, r.request_fingerprint,
           r.status, r.result_json
      INTO v_id, v_generation, v_fingerprint, v_status, v_result
      FROM pr_b_reservations r
     WHERE r.project_id = p_project_id
       AND r.idempotency_key = p_idempotency_key;

    IF NOT FOUND THEN
        -- Different key already holds active-project slot, or a concurrent
        -- deletion/transition. Never execute work on this outcome.
        RETURN QUERY SELECT 'active_project_conflict'::text,
                            NULL::bigint, NULL::bigint, NULL::jsonb;
    ELSIF v_fingerprint IS DISTINCT FROM p_fingerprint THEN
        RETURN QUERY SELECT 'fingerprint_conflict'::text,
                            v_id, v_generation, NULL::jsonb;
    ELSIF v_status = 'completed' THEN
        IF v_result IS NULL OR jsonb_typeof(v_result) <> 'object'
           OR v_result = '{}'::jsonb THEN
            RETURN QUERY SELECT 'storage_error'::text,
                                v_id, v_generation, NULL::jsonb;
        ELSE
            RETURN QUERY SELECT 'replay'::text,
                                v_id, v_generation, v_result;
        END IF;
    ELSE
        RETURN QUERY SELECT 'in_progress_conflict'::text,
                            v_id, v_generation, NULL::jsonb;
    END IF;
END;
$function$;

-- Transaction boundaries and uncertain-commit reconciliation are caller
-- responsibilities. No retry or Director execution is performed here.
