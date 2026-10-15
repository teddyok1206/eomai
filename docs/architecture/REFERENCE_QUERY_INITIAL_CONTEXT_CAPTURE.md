# Initial reference QUERY context capture

2026-10-15 UTC. Source implementation step, not native transport or activation.
This closes initial source/report/index pin selection before the existing canonical
QUERY preparation; it does not replace the full consumer-integration goal.

1. **Owner/boundary:** Catalog resolves one explicit approved past-exam reference
   and initially selects the configured namespace's current index per view.
   Workflow owns submission/replay; API and workers do not select storage paths.
2. **Canonical source:** the existing official selected-source resolver, accepted
   solution report, released Graph/policy and registered immutable index Artifacts.
3. **Identity/revision:** preserve source/report/profile/Graph/policy hashes and
   separate logical index/revision/member/hash identities. The request ID is an
   application-selected identity, not source authority.
4. **Pointers/checks:** use the existing canonical Artifact reader and shared
   registered-index/manifest closure. Check source permission before metadata
   lookup and recapture the same single source after file reads. Native admission
   and consumer reads still verify exact numeric rows and current authority.
5. **Access pattern:** one selected-source capture at each fence, at most three
   unique namespace lookups and exact immutable revision/member reads. No full
   corpus profile scan or encoder operation during this initial selection.
6. **Structures/indexes:** existing unique namespace index, revision PK/FK, frozen
   local command and ordered view tuple; maps/sets for exact source association.
7. **Scale/complexity:** at most three views, one source/report, bounded1024-binding
   manifests. O(V log I + manifest bytes); no vector bytes or large DB values.
8. **Transaction/concurrency:** use the actual owner's active nonnested root;
   neither commit nor write-lock the mutable index head. Read head once and keep
   that exact pin even if another publisher advances it. Source revocation/drift
   fails late; it is not repaired by reselecting latest.
9. **Dependencies:** Catalog application/adapter reuses its repository and official
   reader. Pure index-closure validation stays in the existing application module.
   Contracts/domain acquire no infrastructure or numerical dependency.
10. **Failure/replay:** absence of a view index is explicit `index=null`, not a
    fabricated binding/vector. Missing accepted report remains paired null
    profile/evidence. A dangling, mismatched or corrupt present index fails rather
    than falling back to another namespace. Replays must read the original stored
    QUERY request first; this initial-capture function is never a replay resolver.
11. **Simpler alternative:** canary-style manual IDs/hashes duplicate canonical
    lookup and cannot safely drive ordinary requests. A new registry, queue or
    indexing framework is unnecessary; existing owners already have the data.

Protocol-first: no new worker/wire message. A small frozen owner-local command
contains an existing selected-source scope, requested views, QUERY/DOCUMENT spaces
and bounded options. Output is the existing closed JSON Schema2020-12
`system-rag-similarity-request/1.0`, parsed before return. Consumer meaning remains
explicit `APPROVED_REFERENCE_ITEM`/`PAST_EXAM_VARIATION`; no private brief, draft,
chat query or textbook Item basis is invented.

Required proof: actual temporary canonical index members; exact initial pins;
all three independent views and absent-index/report coverage; early/late denial;
wrong source/space/recipe/Graph/policy/namespace, corrupt/dangling index; head
advance without latest substitution; bounded operation counts; no model/write;
existing pinned reads and incremental predecessor behavior preserved. Synthetic
source/IAM fixtures must not be reported as actual-user acceptance.

Remaining: first-request durable preparation/replay composition with real API
capture, native Orchestrator transport/runner ownership, automatic HTTP preparation
and live consumer activation. The pending original-query process is not changed.

## Canonical Workflow composition

`prepare_and_start_reference_query_selection_in_session` composes this initial
Catalog capture with the existing canonical request/atomic START application. It
authorizes before exact-key metadata lookup. An existing key reads its stored
context/audit and compares the original source/Graph/policy/options, never another
current head or profile. Both entrypoints share one canonical construction/start
implementation, including actual current admission, definition SHA and full-root
rollback. There is no extra preparation table or parallel replay implementation.

Only a newly captured, actually authorized Catalog context can establish known
`ANCHOR_REPORT_MISSING` or `INDEX_NOT_PREPARED` absence before queue creation.
These internal typed unavailability errors are not authority to ignore a corrupt,
dangling or revoked present index. Supplied/replayed context still uses the
original current-owner admission, not an absence shortcut. Future optional API
integration may preserve normal GraphRAG for these specific absent-input cases;
this source application does not silently enable that API behavior.

The former read-index metadata check is now an explicit public pure application
interface. A shared registered-manifest closure is reused by initial selection,
pinned reads and incremental predecessor reads; namespace/hash/count/Graph/policy/
projection checks do not diverge between the three use cases. Existing pointer,
current source and numeric validation remain in their current owners.

The pre-existing unit owner fixture declared a two-class context with a one-class
configuration. It now uses that context's explicit source classes for its
synthetic configured owner. No production policy or validator was broadened.
Source/IAM seams remain synthetic and are not real permission evidence.

## Verified source and disposable-database checkpoint

- Affected Catalog/pinned read/native preparation and existing item/API preparation
  regression: **404 PASS in215.75s**. The initial22 focused cases and earlier
  227/135/369 regression runs overlap; they are not additive totals.
- Guarded disposable PostgreSQL0055 registry/Artifact gate: **33 PASS in83.84s**.
  Its new case publishes a real temporary index Artifact through the Orchestrator,
  registers it, selects the real head/revision and reads canonical member bytes.
  A second connection's NOWAIT head lock succeeds during the reader's root;
  observation records no INSERT/UPDATE/DELETE during initial capture. Current
  source admission/IAM in this new test are explicit synthetic seams.
- Guarded PostgreSQL stage/runner gate: **90 PASS in69.86s**. New cases prove
  selected-reference preparation followed by original Workflow/START replay, changed
  intent rejection and no Workflow persisted for known initial report/index absence.
  Actual native source selection is covered separately; no production auth/model.
- Strict mypy: five production modules PASS. Ruff/format: ten Python files PASS.
  Final disposable read-only inspection: head0055, no other connections.

No production database mutation, actual model inference, new protocol/schema,
migration, worker behavior, runtime package installation or activation was performed
for this source gate. The existing live QUERY and its authentication prompt remain
on their original protected program/compatible owner.
