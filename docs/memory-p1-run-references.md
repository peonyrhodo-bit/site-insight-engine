# Memory 2.0 P1 — projected run references

[Issue #68](https://github.com/peonyrhodo-bit/site-insight-engine/issues/68) and its
clarification define this patch's scope. The source requirements and Memory 2.0
documents are in the
[director audit branch](https://github.com/peonyrhodo-bit/youtube-mcp/tree/ced1f0237018c34931ad7edf3840955dd02902cd)
of the project-management repository. The relevant requirements are ТЗ §12–14,
the bounded context contract, the implementation blueprint §§9–12 and the first
patch changeset.

## Read paths

Director inspection calls `ServerMemory.get_context`, which calls
`Memory.get_context` and then the selected backend. Supabase reads recent rows
per table through `_recent_for_project`; it selects full rows, orders by
`created_at DESC, id DESC` (or `id DESC` where requested), and filters project
after each page. A direct non-null project ID takes precedence over the first
project ID found recursively in legacy JSON. The context is reused by
`Memory.snapshot` and feeds the Director's memory summary and work-plan logs.
The history endpoint is also a full-context consumer. Existing run lifecycle
and idempotency readers have their own full-history requirements.

The experimental `SupabaseMemoryBackend.get_recent_run_refs` requires an
explicit project ID. It has no runtime caller. It selects source IDs, direct
project ID and lifecycle timestamps from `director_runs`. It scans in the same
descending order as the full reader. A populated direct owner proves project
parity even if embedded JSON has a different value. For a missing owner the
reader stops before that row with `MemoryTableReadError`. The error retains
only the proven newer references and integrates with the existing per-table
partial/error convention if a caller chooses to translate it. A subsequent
failure, missing or inconsistent count, repeated ID, or exceeded budget also
produces an explicit error. A server page smaller than the requested range does
not signal exhaustion when the exact visible count says more rows exist.
The count is for visible rows. Independent requests do not share a snapshot.
Concurrent updates can still move records even if the total is unchanged.

The test parameters are at most 20 output refs, five requests of up to ten rows,
and 64 KiB serialized UTF-8 output. The projection excludes `data_json`, free
text and error details. The output budget is checked after the SDK decodes the
page. It does not bound transport bytes or peak RSS. The existing full run
list, run lifecycle and storage are unchanged. References identify source
rows by table and ID. This patch adds no detail endpoint.

## Contract checks and open questions

| Contract | Evidence or remaining condition |
| --- | --- |
| BC-01, BC-02 | Synthetic nested run payloads with a 2,336,825-byte field never enter the projected response. Results and the operational context have no new projection. |
| BC-03, BC-10 | Full run reads return the same source ID and SHA-256 for the synthetic payload. First-page failure is distinct from a confirmed empty list. No new full result retrieval path was verified. |
| BC-04 | The new method never reads or trims decisions, recommendations, constraints, feedback, or unfinished actions. Full protected-state completeness and fail-closed behavior must be established before connecting any compact model to the autonomous cycle. |
| BC-05, BC-06 | Offline coverage includes malformed count, empty reads, page failure, row and byte budgets, mixed projects, and explicit incomplete status for a legacy row. The old full path still resolves nested ownership. |
| BC-07, BC-08 | Snapshot export, Director summarization and work-plan logging still use existing paths. Their payload limits and logging policy are outside this patch. |
| BC-09 | In separate fixture processes with 20, 40 and 100 stored rows, the same 20 refs required two pages. Mock page JSON totaled 2,590 bytes and output was 4,220 bytes in each process. Single-run read times were 0.31, 2.07 and 0.33 ms. Process peaks were 100,396, 99,460 and 100,036 KiB, including imports and synthetic source allocation. These are fixture measurements only. |

| Open question | Why it matters |
| --- | --- |
| Result ownership | A parent run does not prove the legacy embedded owner. Orphans, conflicting and nested IDs need an attribution contract before a projected result list can replace the full reader. |
| Protected scope and active state | The observed columns and historical snapshot do not prove attribution or open-state completeness for decisions, recommendations, constraints, feedback or unfinished tasks. ТЗ §12–14 requires explicit user action for consent. A chat reply confers no approval. |
| P0 error handling | [PR #67](https://github.com/peonyrhodo-bit/site-insight-engine/pull/67) is outside this branch. This run reader has no merge or code dependency on P0. Autonomous integration requires separate verification of fail-closed protection, including beyond the status propagation in #67. |
| Operational budgets | Transport, production RSS, latency, project sparsity, concurrent pagination and output thresholds need separate profiling before rollout. |
