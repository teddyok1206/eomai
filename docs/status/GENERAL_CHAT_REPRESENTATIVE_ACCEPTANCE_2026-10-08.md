# EOM representative chat operating acceptance

Observed: 2026-10-08 UTC. `REPRESENTATIVE_CHAT_LIVE=PASS`.
Scope: existing `일반 → ChatGPT`, dedicated resident Codex capacity, authorized
read-only sources and EOM workflow guidance. No external LLM API or worker tool.

## Compatible installed set

| Component | Immutable source pin |
| --- | --- |
| API, Catalog, Orchestrator chat owner/worker | `276f31ea710a09e2074e5fc5829695d80a522266` |
| Web | `6c765820d21f91dd1ef277219a894f25ddabac57` |
| Chat protected runtime pin | `276f31ea710a09e2074e5fc5829695d80a522266` |
| DB migration | `20261008_0049` (unchanged) |

The Web successor changes only presentation; backend/contract bytes remain
compatible. Supported wheel install/RECORD, API runtime isolation, ready health,
Catalog roles and chat activation passed. Web installed inventory: 40 files.
API rollback record: `/var/lib/eom-api/deployments/276f31ea710a09e2074e5fc5829695d80a522266.json`.
Model/enrollment remain unchanged; original slots01–06 are not reassigned.
API, Web, Catalog application runner, workflow runner and both chat units are
active. Chat owner/worker restart counters were zero at postflight.

## What the assistant can do

- Explain EOM item authoring, transformation, review, preview, HWPX and permitted
  account/workflow operations, then guide the user through the existing UI.
- Resolve up to three explicitly selected immutable Items from internal search.
  Preserve revision, manifest/component hashes, approval and Graph snapshot pins.
- Use the exact approved Item text and accepted solution/design summaries linked
  to its pinned Graph base. Graph absence/report absence is a limitation, not an
  invented citation or implicit latest-version fallback.
- Distinguish source support, model inference, general knowledge, insufficient
  evidence and timestamped system observations. Verified citation buttons open
  the existing exact-revision Preview.
- Keep owner-private history and follow-up; reauthorize source access when
  preparing, continuing and exposing history. Same intent replays the same turn.

Observations are bounded counts and the actor's own workflow-state projection,
not a continuous monitor or proof of executing leases. No other user's operation
or conversation is exposed. No autonomous corpus-wide tool search, image/PDF
inspection, chat mutation, hidden reasoning export or new textbook privilege.
An integrity receipt proves input/output/citation binding, not scientific quality.

## Verification

| Gate | Result |
| --- | --- |
| Final backend/protocol/API/Web/dependency source gate | 593 PASS |
| Last Web-only presentation/navigation gate | 15 PASS |
| Disposable PostgreSQL persistence, including V2 replay/revocation | 48 PASS |
| Fresh limited chat DB-role suite | 12 PASS |
| Guarded search/query-plan/API role suite | 23 PASS |
| Ruff / formatter / changed production mypy / JS syntax | PASS |
| Exact existing production Item + report read-only resolution | PASS; 0 model calls, 0 mutations |
| Stopped-host owner/worker sandbox probes | PASS; 0 model calls |
| HTTPS login, attached-source answer and follow-up | PASS |
| Verified Item/report citations and original Preview navigation | PASS |
| Exact HTTP submission replay | PASS; no duplicate turn |
| History reread and original terminal history digest | PASS |
| Final PC/mobile read-only screen | PASS; 0 model submissions |
| Newly created disposable test DB cleanup | PASS; production DB unchanged |

Source gates are overlapping suites, not additive counts. The existing
Starlette/httpx test-client deprecation warning remains; no dependency was added.
Desktop search-open message height was 212.625px; mobile closed-search message
height was 309.625px, with document width equal to the 390px viewport. Attached
Items remain visible outside the search panel. Successful submission collapses
search; uncertain/failed submission keeps input and selected intent unchanged.
Delayed startup reads cannot replace a newer user-selected route.

## Actual model execution and immutable evidence

This task used five explicit model submissions: one native-format failure and
four completed answers. The direct-only completed answer honestly reported the
then-missing report; it is not retroactively relabeled as report-grounded.
The last two new submissions included both `REGISTRY_DIRECT` and
`SOLUTION_REPORT`, used both S1/S2 citations and passed canonical receipt checks.
One HTTP replay made no additional model execution. Last UI check submitted none.

Conversation: `chat_63b1c596111413b171e3bf3bf76a1d17`.

| Purpose | Turn | Output Artifact / Revision |
| --- | --- | --- |
| Representative guidance/state | `chatturn_1f26abd35986fa820590a7abec31b007` | `artifact_b57d8719b6ae435ebf38651efa49cfad` / `rev_d650e02d85f9405d869b0720dda361e0` |
| Direct Item with honest report limitation | `chatturn_0ecdd4e8da600f6f3d77a58100ea0d3e` | `artifact_068bc5e4c99a461da30ca70e2c18251a` / `rev_307b087c03f445dcbf194cb5b60d02d0` |
| Item + accepted report explanation | `chatturn_3137ae205b293848cd97c1b095d06719` | `artifact_652c98e1c7b64250a56116d8ac801ef7` / `rev_d9f0151e68374ab1960b07f2a1a5067e` |
| Follow-up: source / proposal / observation distinction | `chatturn_cf8db0faa5629089b7e0503cb7e688a8` | `artifact_acc18d4734b34537acddc37e3e16f7f8` / `rev_b5943941b4764643806348844be0f04f` |

Latest result SHA: `sha256:598a3e9cbcf9fd039196019831d31d41e8c499168a2202f8212e1f4f5729f687`.
Exact request/result revisions are retained by the existing Orchestrator Artifact
publication and conversation receipts; this document does not copy their text.
Postflight at `2026-10-08T16:58:00.275260Z`: original 13 terminal-turn digest
unchanged; active chat turns=0; first failed canary still FAILED with input/output.

## Repairs discovered through actual use

The first installed structured turn returned `CODEX_TURN_FAILED`. Adapter shape
projection now excludes unsupported uniqueness/conditional semantics; full
canonical Schema/Pydantic checks still enforce them after generation. No upstream
raw error body was retained, so a specific upstream rejection reason is not
claimed. No automatic model retry or failure rewrite occurred.

Real Graph metadata contains the original V9 analyses, with accepted V10 reports
as additive successors outside the snapshot. Chat initially incorrectly required
V10 Graph membership, omitting reports. It now reuses existing retrieval semantics
and checks the accepted report source/base pointers against the exact selected
Item and snapshot-local base. No Graph republish or 520-report reprocessing.
Regression reproduction: 10 failed/2 passed before the rule correction; 78 focused
tests passed afterward, including wrong source/revision/base/hash rejection.

The temporary evidence directory is `/tmp/eom-chat-representative.gAR5rIRV` (private
workspace, not canonical storage). Generated answer artifacts remain on NAS.
The Orchestrator archived 16 bounded sanitized report/log members as
`artifact_00c74e8880f64eeba56b85c85ff7acc5` /
`rev_f45d4b2cf17d4a63be595fc67501faad`, manifest
`sha256:f60d480ef3d3e8334ebb50e3bfd9a3a8123b5b2c3995a78481c4265de6c4e89c`.
This opaque operator-log archive uses the existing operations file-set contract,
not a new runtime/worker protocol. The initial archive admission refused writable
log metadata before publication; only the exact task-created local file modes
were corrected. No permission gate or failed history was weakened.
Secrets, transcript text, binaries and long logs are not committed to Git or Slack.
The preexisting shared test database is untouched; only this task's fresh
`/tmp/eom-api-testdb-20261008161005_2f0b2316` and guarded disposable roles were removed.

Manual user confirmation of this successor's conversational quality is not yet
recorded. Technical/source attribution acceptance is not educational approval.
