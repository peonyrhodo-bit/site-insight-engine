-- PR-B disposable-only SQL prototype. REVIEW ONLY; NEVER RUN ON PRODUCTION.
-- Execution requires separate explicit owner approval and a verified local
-- pr_b_test_* database with a restricted test-only role.
-- This prototype is not wired into Director or any application path.

CREATE OR REPLACE FUNCTION pr_b_test_finalize(
    p_project_id text,
    p_idempotency_key text,
    p_generation bigint,
    p_result jsonb
) RETURNS boolean
LANGUAGE plpgsql
SECURITY INVOKER
AS $function$
DECLARE
    v_updated bigint;
BEGIN
    IF p_result IS NULL
       OR jsonb_typeof(p_result) <> 'object'
       OR p_result = '{}'::jsonb THEN
        RAISE EXCEPTION 'nonempty JSON object result required'
            USING ERRCODE = '22023';
    END IF;

    UPDATE pr_b_reservations
       SET status = 'completed',
           result_json = p_result,
           updated_at = clock_timestamp()
     WHERE project_id = p_project_id
       AND idempotency_key = p_idempotency_key
       AND fencing_generation = p_generation
       AND status IN ('requested', 'running');

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END;
$function$;

-- Caller owns the surrounding transaction and must verify authorization.
-- False means stale generation, missing reservation, or already terminal.
-- No side effects outside this disposable table.
