# Memory 2.0 P1 — projected run references

Scope comes from [Issue #68](https://github.com/peonyrhodo-bit/site-insight-engine/issues/68)
and its clarification. The immutable Russian specification, requirements map,
bounded-context contract, implementation blueprint and first patch changeset
are in the [director audit branch at ced1f02](https://github.com/peonyrhodo-bit/youtube-mcp/tree/ced1f0237018c34931ad7edf3840955dd02902cd).
ТЗ §12–14 requires an explicit user accept/reject action. A chat reply provides
no consent. Acceptance permits creating a linked preparation task.

## Findings

| Severity | Evidence at 2dbeff9 | Resolution |
| --- | --- | --- |
| High | `memory/supabase.py::get_recent_run_refs` combined offsets from independent queries. Equal exact counts and unique returned IDs could coexist with skipped records after an insertion plus deletion, or a sort-key update. | One projected query at offset zero. If the window cannot establish the requested prefix or visible exhaustion, return an explicit incomplete error. |
| Medium | The reader could return the requested prefix before inspecting the rest of its response, including repeated IDs, incorrect order or malformed fields. | Validate the window before exposing references. Compare timestamps chronologically with the same descending ID tie-breaker and PostgreSQL NULL ordering. |
| Limitation | The 64 KiB budget operates on serialized references after the SDK decodes the response. | The response projects only IDs, direct project and timestamps. HTTP bytes, database work and peak process RSS still require separate evidence. |
| Limitation | A verified recent run window provides no evidence of complete protected state. | The new method remains opt-in with no runtime caller. PR #67 is outside this branch. |

## Read contract

Director inspection calls `ServerMemory.get_context`, which calls
`Memory.get_context` and the selected backend. Supabase's existing
`_recent_for_project` selects full rows, orders by `created_at DESC, id DESC`
(or `id DESC` where requested) and filters after fetching each page. A direct
non-null project ID takes precedence over recursively embedded legacy IDs.
Context feeds snapshots, Director summaries and work-plan logs. The history
endpoint, run lifecycle and idempotency checks retain their existing readers.

`SupabaseMemoryBackend.get_recent_run_refs` selects only `id`, `project_id`
and the four timestamps from `director_runs`. It requests one window of up
to 50 records with an exact count and the full reader's ordering. Upstream
PostgREST builds the projected rows and exact count in one SQL statement.
The checked SDK request uses an offline mock. This contract relies on the
service supplying a contiguous ordered window and an exact count from that
statement. A gap in numerical IDs can be valid. Client validation cannot
prove the database did not omit an arbitrary row inside an otherwise valid
response. The deployed service version, RLS visibility and response behavior
were not verified against production.
[PostgREST v14.0 mainRead](https://github.com/PostgREST/postgrest/blob/v14.0/src/PostgREST/Query/Statements.hs#L65-L89)

A well-formed window succeeds when it contains the requested number of proven
project references or when its row count equals the exact visible count. A
server cap can shorten the window. If too few project rows are found and more
visible rows could exist, the reader raises `MemoryTableReadError` and
includes the proven prefix. It makes no follow-up request. A NULL direct
owner before the prefix is established stops the scan for the same reason.
Malformed metadata, duplicate IDs, bad order and request errors are explicit
errors. The full reader still handles nested legacy ownership as before.

Experimental limits are 20 output references, 50 rows returned by one
request and 64 KiB serialized as UTF-8 JSON. The row limit is a client-side
scan bound, not a bound on database work for sorting or exact count. In a
single request the maximum decoded row count is higher than before. The
direct project field is text, so even a projection can carry a large value.
The reader does not impose an input HTTP byte cap. No production OOM claim
follows from this change.

## BC-01–BC-10 evidence

| Contract | Verified offline or deferred |
| --- | --- |
| BC-01 | The projected run response omits synthetic 2,336,825-byte nested payloads. The existing results and operational context remain outside this patch. |
| BC-02 | Nested work-plan memory does not enter the run references. Operational context growth remains unverified. |
| BC-03 | Full run reads still return the original source ID and matching SHA-256 for the synthetic payload. The SDK test issues a GET only. |
| BC-04 | Decisions, recommendations, constraints, feedback, legacy approvals and unfinished actions have no changed paths. Protected count/ID completeness and the autonomous fail-closed gate remain unverified. |
| BC-05 | Empty, incomplete and error outcomes are distinct. Tests cover missing and impossible counts, duplicate IDs, malformed fields, first-request failure, short windows and exhausted scan/output budgets. |
| BC-06 | Mixed projects and conflicting embedded IDs match direct-owner precedence. NULL owner stops the compact reader; nested ownership continues to work in the full reader. |
| BC-07 | Snapshot and Director summary remain on existing paths. Their payload limits were not verified. |
| BC-08 | Work-plan and assessment logging remain on existing paths. Log sanitization was not verified. |
| BC-09 | For 20/40/100 fixture rows, one request returned 20/40/50 projected rows. Mock page JSON was 2,590/5,201/6,511 bytes. The same 20 refs occupied 4,220 bytes. Single-run elapsed times were 0.37/0.40/0.52 ms and process peaks were 99,636/99,868/99,732 KiB, including imports and fixture allocation. These measurements do not cover live HTTP, database cost or production RSS. |
| BC-10 | The unchanged full reader still retrieves the synthetic source. Failures and ambiguous ownership on the projected path do not synthesize a replacement. Explicit full-result retrieval and authorization were not verified. |

## Open questions

| Open question | Blocked work |
| --- | --- |
| Result ownership | Parent run ownership cannot establish the legacy embedded owner. Compact result reads require evidence for orphan, conflicting and nested ownership. |
| Protected scope and active state | Legacy feedback, approvals, decisions, constraints and unfinished tasks need verifiable attribution and completeness before any compact context reaches autonomous research. |
| P0 error handling | [PR #67](https://github.com/peonyrhodo-bit/site-insight-engine/pull/67) is not a dependency of this unused method. Any runtime integration requires separate end-to-end fail-closed evidence. |
| Service behavior and resource limits | Exact-count visibility, sparse history, latency, HTTP size and peak RSS need separate profiling and acceptance before rollout. |

## Offline run

Python 3.12 with service credentials removed and a temporary
`sitecustomize.py` rejecting `socket.getaddrinfo`, `socket.socket.connect`
and `socket.socket.connect_ex`:

```bash
env -i PATH="$PATH" PYTHONPATH="$offline_dir" FREE_MODE=true AUTONOMOUS_ENABLED=false \
  YOUTUBE_QUOTA_DB_PATH="$offline_dir/quota.sqlite3" \
  .venv/bin/python -m pytest -q -o "cache_dir=$offline_dir/pytest-cache"
```

192 passed, 11 subtests passed. Four FastAPI `on_event` deprecation warnings
and one separate pytest-asyncio fixture loop scope configuration warning.
