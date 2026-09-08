# Graph Item Bank and Mock Examination Production V1

Status: implementation design

Last reviewed: 2026-09-08 UTC

Normative editorial source: `content/authoring-rules/integrated-science-mock-exam-assembly-v1.md`.
The source guide is pinned by revision and SHA-256. Its subject-specific slot policy is policy data;
it is not compiled into a generic assembly algorithm.

## Responsibility and boundaries

Catalog owns immutable Item, Form, Assembly, placement, and Artifact pointers. The Application API
exposes read-only item-bank queries and idempotent assembly commands. The HWPX application service
materializes validated Item Revision artifacts only after an Assembly Revision is released. The GUI
is a presentation adapter and contains no selection, scoring, or layout rules.

Workers do not communicate with one another and do not write PostgreSQL or NAS. Any future worker
proposal is validated by the Orchestrator; only the Orchestrator/Catalog boundary may commit an
Assembly or output Artifact.

## Canonical sources and revision model

- Item content: `Item -> immutable ItemRevision -> typed component ArtifactRevision pointers`.
- Curriculum evidence: one pinned, published Graph Snapshot and its reviewed outline Revision.
- Assembly policy: logical policy identity, immutable policy Revision, schema version, and hash.
- Examination: `AssessmentForm -> immutable FormRevision -> immutable AssemblyRevision`.
- Output: released Assembly Revision plus pinned template/layout revisions -> output Artifact
  Revisions. HWPX/PDF bytes are never database values.

Mutable current pointers are conveniences only. Item-bank results, assembly history, build requests,
and publication provenance pin exact revision IDs and hashes.

## Access patterns and data structures

The item bank serves: recent ordered iteration, exact examination lookup, Graph traversal from a
curriculum unit to item placements, and optional indexed item-type/difficulty filtering. Existing
B-tree indexes on snapshot/exam/item revision and Graph adjacency indexes provide bounded lookups.
The query adapter bulk-loads unit bindings for a page and uses maps keyed by placement node and unit
ID, avoiding N+1 queries and repeated list scans. Expected scale is tens of thousands of placements;
page work is `O(page size + linked units)` in memory.

Assembly is a fixed-size constraint problem (25 slots for the reviewed mock-exam policy). Candidate
Item Revision pointers are indexed once by curriculum, score compatibility, item/material type,
difficulty, inquiry evidence, and eligibility. Membership and deduplication use sets; final order is
an immutable tuple. Deterministic bounded backtracking is acceptable after candidate counts and
visited nodes are measured. A general solver is not introduced until measured need justifies it.

The dominant persistent reads are assembly-by-form, placements-by-assembly ordered by section and
position, and reverse usage-by-item. Existing foreign keys, unique placement constraints, and B-tree
indexes own those access paths. New indexes are added only with an observed query-plan need.

A whole-exam HWPX build resolves the ordered Item Revision set in two indexed Catalog queries and
resolves all unique Artifact/ArtifactRevision member pointers in two additional indexed queries.
Maps keyed by immutable revision/member identity preserve Assembly order and make validation and
materialization `O(item count + component count)` in time and space. Each item is rendered through
the reviewed content-team program. Its displayed number and exam score are presentation values
projected from the immutable Assembly slot; the original Item JSON, original item-level score, and
editorial Markdown hashes remain unchanged. The final package contains one ordered HWPX section per
item, while equation, table, and visual counts remain content-driven rather than fixed template
quotas.

## Transactions, concurrency, failure, and replay

Item-bank access is read-only and fails closed if the current Graph pointer or an Item Revision
pointer is stale, missing, in an invalid lifecycle state, or hash-inconsistent.

An assembly command validates all policy, Graph, rating, usage-snapshot, Item, component, and hash
pointers before one transaction appends an immutable Assembly Revision and ordered placements.
Idempotency keys replay the same manifest and reject a different request hash. Candidate shortage,
duplicate revisions, unresolved curriculum aliases, or any failed invariant returns a stable error
and creates no successful revision. Released revisions are never edited.

HWPX builds use a pinned Assembly Revision and are idempotent by request hash. A failed render keeps
diagnostic state but publishes no successful output pointer. Artifact commit and the successful
build transition share the established Orchestrator/Catalog transaction and manifest checks.

## Dependency direction

GUI/CLI -> application use cases -> assembly domain validator -> catalog/API contracts. PostgreSQL,
NAS, Graph lookup, and HWPX are adapters implementing application-owned interfaces. Contract/domain
packages do not import service or infrastructure packages.

## Rejected simpler alternative

A GUI-only list plus a mutable JSON array of item IDs would be shorter, but it cannot preserve Graph
snapshot identity, policy provenance, item hashes, concurrency, replay, or reproducible HWPX output.
Copying Item JSON into a form would also create a second authority. Therefore the implementation
extends the existing pointer-oriented Form/Assembly model and materializes bytes only at preview and
render boundaries.

## Production-candidate projection

The occurrence browser remains a backward-compatible examination-history view.  Production uses a
separate `production-item-candidate-view/1.0` projection so an approved authored Item does not need
invented examination coordinates and a past-exam Item keeps its real occurrence identity.  The
canonical source is the current published Graph Snapshot's accepted
`APPROVED_ITEM_REVISION` analysis membership, its canonical `item-revision:<revision-id>` node, the
node's reviewed curriculum edges, and the immutable Item/Item Revision/component rows.  A past-exam
context is attached only when the same analysis resolves to one typed occurrence reference.

The projection keeps logical Item ID, immutable Item Revision ID, component ID, Artifact ID,
Artifact Revision ID, and content SHA-256 separate.  It never resolves an implicit latest Artifact
revision.  Basic mock-exam/HWPX eligibility is deliberately structural: active Item lifecycle,
eligible immutable revision state, exactly one ordinal-zero JSON `ITEM_CONTENT` pointer using the
V2 content-team schema, and an exact editorial-Markdown member/hash pointer.  Rating, usage,
inquiry, material, scoring, and slot-policy decisions remain Stage 3 application rules and are not
fabricated by this read model.  Ineligible rows remain observable with stable reason codes.

Primary access is ordered snapshot-local iteration, optional source/profile/eligibility membership,
and curriculum-subtree traversal.  The adapter uses existing B-tree Graph source/node/edge and Item
component indexes, fetches one bounded page, then bulk-loads occurrence, curriculum, and component
maps.  Work is `O(page size + linked units + components)` time and space; no per-row query or binary
materialization is allowed.  The snapshot is immutable, so offset cursors are stable within its
hash-pinned identity.  Publication creates one canonical structural Item Revision node per reviewed
Item binding and direct adjacency edges to its reviewed units; sets merge repeated evidence and
prevent duplicate edges.

The query is read-only.  Missing nodes, ambiguous source classes, stale Item pointers, duplicate
canonical components, unknown curriculum targets, and incoherent past-exam context fail explicitly;
an unsupported but coherent component produces an ineligible candidate instead of a guessed
conversion.  Graph publication remains one existing transaction with deterministic replay.  The
API layer depends on typed contracts, while SQL/Graph resolution stays in its infrastructure
adapter.  No new persistent cache, table, dependency, or index is introduced because the existing
snapshot adjacency and component indexes already serve the bounded access paths.

## Server-driven assembly planning

The Catalog application service owns mock-exam planning.  The browser supplies Deliverable/Form
presentation values and returns the opaque plan hash, timestamp, policy pointer, and Graph Snapshot
pointer issued by preview; the Web gateway never accepts browser-authored scoring, curriculum
coverage, inquiry classification, material classification, review rating, or position.
The canonical sources are the released assembly and layout policies, the reviewed rating policy,
the current published Graph Snapshot, immutable Item/Item Revision/component and Artifact Revision
pointers, the latest pinned Item review record, and the append-only usage ledgers as observed by the
planning transaction.  Content bytes are materialized only at this validation boundary through a
bounded, no-follow Artifact member read and are never copied into PostgreSQL.

The team lead's reviewed 25-row default layout is a separate immutable layout-policy revision.  It
maps positions to official score, coverage role, coverage requirement or balance large-unit,
required inquiry status, and preferred difficulty/material profile.  This keeps examples from
becoming Item content while preserving the reviewed assessment-level arrangement exactly.  A
separate rating-policy revision maps only a review record with decision `APPROVE` and
`final_rating` A/B/C to production eligibility; missing or unrecognised ratings are not guessed.

Candidate resolution is one bounded Graph/Item query followed by bulk review, Artifact, curriculum,
and usage queries.  Maps keyed by immutable revision ID provide O(1) lookup; curriculum and source
membership use sets; usage history is a sorted append-only projection whose hash is captured in a
small immutable snapshot value.  The expected scale is at most 5,000 Graph candidates and tens of
thousands of usage rows.  Resolution is O(candidates + edges + reviews + usage) time and space.
The fixed 25-slot constraint search indexes candidates by requirement and large unit, orders slots
by option count, uses a selected-revision set, and is bounded by an explicit visited-node limit.
A general solver is intentionally not introduced because the reviewed layout is fixed-size and no
measured need justifies another dependency.

Preview is read-only.  Its hash and timestamp form a 15-minute optimistic creation token.  Planned
creation repeats historical-cutoff resolution inside the existing Deliverable-locked transaction,
requires the exact preview hash, validates every immutable pointer and hash, then appends the Form,
Assembly Revision, and placements atomically.  The released manifest pins the layout/rating policy revisions, the
Graph Snapshot, the usage snapshot hash, each review and content Artifact Revision, and the
server-generated plan hash.  Concurrent creation for one Deliverable/Form serializes on the
Deliverable row; exact replay returns the existing immutable revision, while a conflicting Form or
pointer fails.  Candidate shortage, search-bound exhaustion, pointer drift, or any validation error
rolls back without a partial Assembly Revision.  The simpler client-authored placement array was
rejected because it lets presentation code invent domain facts and cannot reproduce review or usage
provenance.

## Released V2 Assembly to HWPX

The HWPX application service accepts both released Assembly manifest revisions. V1 placements
continue to resolve their canonical Item Revision components. V2 placements use the content
Artifact Revision pointer already embedded in the server-authored plan and cross-check it against
the same immutable Item Revision before materialization; image components remain pinned by the Item
Revision manifest. The renderer receives one version-neutral, hash-pinned Assembly pointer and an
ordered tuple of item materialization pointers. The V2 database placement identity is derived from
the Assembly Revision, slot ID, and Item Revision using the same content-addressed rule used when the
Assembly transaction was committed. No Item JSON, Markdown, image, or HWPX bytes are copied into
PostgreSQL.

The dominant operations are an exact Assembly Revision lookup, two indexed bulk Item/component
queries, and two indexed bulk Artifact/member queries for at most 200 placements. Maps keyed by
Item Revision and artifact/revision/member identity give `O(n)` time and space while preserving the
immutable position tuple. The existing requested-build partial index and row lock remain the queue
claim boundary; no new persistent cache or index is needed at the reviewed 25-item scale.

Admission validates the released manifest, its policy/Graph identity, the full ordered Item set,
the V2 plan's direct content pointers, and the released content-team handoff before appending one
idempotent build request. Processing repeats those checks before staging. A manager restart never
silently retries a renderer: an interrupted `RUNNING` or `VALIDATING` assessment build is left alone
while its fixed renderer unit may still be active, then terminalized with a stable interrupted-build
code once that unit is absent. If the internal HWPX job and Artifact Revision were already committed
before the manager stopped, recovery accepts that exact immutable receipt instead of rendering
again. A caller may explicitly request a new build under a new idempotency key after any failure.
Item and assessment queues are alternated by the single manager loop, so a continuous stream
in one queue cannot starve the other; each individual claim remains FIFO and `SKIP LOCKED`.

The V1 content-team exam render protocol remains immutable for historical Assembly V1 builds. A V2
render protocol is used for planned Assembly V2 builds because the isolated builder must receive
the exact `plan_sha256`, displayed number, and `points_milli` for every placement; the Assembly
manifest hash alone proves provenance but cannot tell a renderer which presentation values to put
on the page. V2 accepts only the reviewed 1500/2000/2500 milli-point values, deterministically maps
them to `1.5`/`2`/`2.5`, and returns a `render_plan_sha256` over the complete ordered presentation
projection. The manager and builder derive that hash from one contract-owned projection function,
and the package manifest, validation report, and terminal result must all agree before the
Orchestrator commits the artifact. Protocol V1 continues to produce byte-compatible requests and
uses the source item's score; no queued historical request is reinterpreted.

The renderer boundary is one fixed systemd worker with no DB or NAS write authority. The manager
materializes only validated files in its temporary workspace, and the Orchestrator remains the sole
artifact committer. Protocol history is append-only and keyed by version plus schema-bundle hash;
new V2 jobs cannot collide with V1 idempotency history. Failure publishes no successful pointer,
and interrupted work follows the no-replay recovery rule above. The simpler alternatives—mutating
the canonical Item score, inferring score from position inside the renderer, or resolving current
Item/policy pointers at render time—were rejected because they introduce a second authority or make
a released exam non-reproducible. Recovery by automatic renderer replay was also rejected because
an interrupted external process cannot be proven safe to repeat without a new operator request.

## Acceptance checks

- JSON Schema 2020-12 precedes new DTO and behavior.
- Item-bank filters preserve exact Graph/Item/occurrence pointers and reject high-school grade-1
  March evidence.
- Assembly tests cover missing/stale/hash-mismatched pointers, duplicate references, candidate
  shortage, exact 25/50000 and 8/9/8 scoring, 21/4 slot reasons, 4..5 inquiry items, adjacency,
  deterministic manifests, idempotent replay, and concurrent creation.
- HWPX tests cover ordered question/answer/explanation output, optional visual/table/equation
  components without fixed counts, deterministic manifests, download identity, and absence of
  binary payloads in database rows.
- Full integration uses opt-in markers when it consumes Codex usage or touches live services.
