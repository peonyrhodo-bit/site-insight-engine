-- Additive Director run lifecycle fields; preserve all historical rows.
ALTER TABLE public.director_runs
    ADD COLUMN IF NOT EXISTS project_id text,
    ADD COLUMN IF NOT EXISTS status text,
    ADD COLUMN IF NOT EXISTS started_at timestamptz,
    ADD COLUMN IF NOT EXISTS finished_at timestamptz,
    ADD COLUMN IF NOT EXISTS current_step text,
    ADD COLUMN IF NOT EXISTS error_message text,
    ADD COLUMN IF NOT EXISTS updated_at timestamptz;

UPDATE public.director_runs
SET project_id = data_json ->> 'project_id'
WHERE project_id IS NULL
  AND jsonb_typeof(data_json) = 'object'
  AND data_json ? 'project_id';

CREATE INDEX IF NOT EXISTS director_runs_status_updated_at_idx
    ON public.director_runs (status, updated_at DESC);

-- Cross-process exclusion: a project may have at most one active run.
CREATE UNIQUE INDEX IF NOT EXISTS director_runs_one_active_per_project_idx
    ON public.director_runs (project_id)
    WHERE status IN ('requested', 'running');
