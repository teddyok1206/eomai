# Legacy Item Unit Learning and Editorial Compatibility V1

Status: implementation decision

Last reviewed: 2026-09-03 UTC

## 1. Responsibility and boundary

This design extends the existing Knowledge Analysis and Education Graph pipeline. It does not add a
second knowledge graph or a model-training store. Here, "learning an item" means producing
source-grounded, immutable analysis observations that can be reviewed, published in a pinned Graph
Snapshot, and retrieved as a bounded Evidence Bundle by later authoring workflows.

One learned legacy item has two independent tracks:

1. **Unit knowledge** continuously adds accepted Item Revision observations to the existing
   `knowledge_analysis_runs` history and immutable Education Graph Snapshots.
2. **Editorial compatibility** evaluates one exact Item Revision against one exact content-team
   authoring prompt revision and one exact HwpQuestionEditor handoff-profile revision. A compatible,
   lossless combination closes and is not repeated until one of those revisions changes.

The tracks are separate because scientific and assessment evidence grows as more items arrive,
while compatibility with a fixed renderer and editorial contract can converge. The coordinator may
schedule both tracks for one item, but neither track owns the other track's lifecycle.

Workers remain read-only proposal producers. They receive staged local inputs and return schema-
valid local results. The Orchestrator validates and stages results. Catalog application services own
transactions, immutable registry state, Artifact commits, Graph publication, and NAS commits.

## 2. Canonical sources and authority

The canonical learning source is an approved immutable Item Revision and its pinned `ITEM_CONTENT`
Artifact member. A legacy extraction result and acceptance record are provenance leading to that
Item Revision; they are not an alternative Item source.

Unit knowledge authority is:

- the approved Item Revision and exact item-content member;
- exact legacy occurrence, extraction acceptance, and source-anchor pointers;
- the reviewed curriculum framework revision;
- the knowledge-analysis policy, Execution Preset, and worker proposal schema revisions;
- the exact prior Graph Snapshot and Evidence Bundle when retrieval is used.

Editorial authority is limited to these exact references:

- the content-team integrated-science authoring prompt Artifact member; and
- the reviewed Markdown description of the content-team HwpQuestionEditor handoff profile.

The executable renderer identity is separately pinned as the actual handoff ZIP Artifact ID,
Artifact Revision ID, archive member path, archive SHA-256, and reviewed profile SHA-256. The worker
receives only this small typed identity and the reviewed Markdown description; it never receives or
executes the ZIP. Server-owned validation resolves the ZIP and accepts HWPX renderability only from
an already completed build for that exact Item Revision and executable profile.

EOM may add security, provenance, schema, pointer, and deterministic rendering checks. It must not
add content or format preferences of its own. Every editorial issue therefore names one of the two
authorities, its immutable revision and SHA-256, and a bounded rule locator. Examples embedded in
the team material remain examples; no sample unit, item, visual count, equation, or topic becomes a
global default or prohibition.

## 3. Identity and revision model

```text
Legacy source bundle revision
  -> extraction request/result revision
  -> reviewed extraction acceptance
  -> approved Item / immutable Item Revision
       -> Knowledge Analysis Run (append-only observation)
            -> accepted proposal Artifact Revision
            -> selected immutable Graph Snapshot Revision
       -> Editorial Compatibility Run
            -> immutable compatibility result Artifact Revision
```

Unit learning identity is the existing Knowledge Analysis Run ID. Exact replay uses the same
idempotency key derived from the Item Revision, analysis policy revision, Execution Preset revision,
and exact input dependencies. A different Item Revision, policy revision, or explicitly reviewed
successor analysis creates a new run; historical runs and Graph Snapshots are never overwritten.

Editorial compatibility identity is the tuple:

```text
(item_revision_id,
 item_content_sha256,
 authoring_prompt_artifact_revision_id,
 authoring_prompt_sha256,
 hwpx_profile_artifact_revision_id,
 hwpx_profile_sha256,
 renderer_profile_artifact_revision_id,
 renderer_profile_archive_sha256,
 renderer_profile_sha256,
 compatibility_policy_revision)
```

Exact replay returns the prior result. A changed tuple creates a new run. `COMPATIBLE` plus all
required deterministic lossless checks closes that tuple. `NEEDS_ADAPTATION` and `BLOCKED` remain
open. Closing one tuple never prevents analysis of later Item or reference revisions.

## 4. Required pointers and resolution checks

Every source, guidance, HWPX profile, proposal, result, and Graph reference carries its logical ID,
immutable revision ID, member path, schema reference, media type, and SHA-256. Resolution verifies:

- logical and revision existence and relationship;
- expected lifecycle and access permission;
- exact member path, schema, media type, byte count, and SHA-256;
- immutable revision approval and non-stale current pointer where a current selection is relevant;
- the Item Revision's one canonical `ITEM_CONTENT` component;
- extraction acceptance and origin linkage for legacy items;
- prompt and HWPX profile membership in the released content-team reference bundle;
- Graph Snapshot publication state and Evidence Bundle membership when retrieval is used.

Missing, stale, withdrawn, dangling, or hash-mismatched pointers fail explicitly. The resolver never
substitutes a latest revision.

## 5. Unit-knowledge accumulation and Graph RAG

The existing `APPROVED_ITEM_REVISION` Knowledge Analysis source, proposal Artifact, accepted result,
Graph structure manifest, Graph Snapshot, retrieval policy, and Evidence Bundle are reused.

For each approved item, the analyst proposes source-anchored Item Revision, Item Element, Concept,
Claim, Formula, Data Representation, and Assessment Pattern nodes and ontology-allowed edges. Unit
alignment resolves against the pinned integrated-science curriculum framework. The accepted run is
added to the reviewed Graph structure and a new immutable snapshot; it does not mutate a previous
snapshot.

Accumulation is intentionally unbounded across accepted item revisions. Exact replay is deduplicated
but new source observations continue to build evidence for the same unit. Retrieval remains bounded:
later item authoring pins one published snapshot and receives only a role- and budget-filtered
Evidence Bundle, not every historical item or the complete graph.

An extraction proposal that has not yet become an approved Item Revision may retain its existing
curriculum observations as provisional evidence. It cannot enter a published Graph Snapshot.
Acceptance and Item import are the sole promotion bridge; promotion schedules the ordinary approved-
item Knowledge Analysis path rather than copying provisional text into Graph storage.

An approved Item alignment is published only through
`knowledge-graph-structure-manifest/3.0` and `knowledge-graph-snapshot-manifest/6.0`. The reviewed
binding pins all of the following as separate identities:

- the accepted Knowledge Analysis Run and accepted-result Artifact Revision;
- the exact predecessor Graph Snapshot Revision;
- one published Evidence Bundle Revision and its retrieval request hash;
- the Evidence Bundle manifest Artifact Revision and the selected evidence node IDs; and
- one or more reviewed `MINOR` curriculum unit IDs from that predecessor snapshot.

The publisher resolves every pointer from Catalog state, requires the Evidence Bundle nodes to be
members of the pinned bundle, and requires each selected curriculum unit to be reachable from those
nodes by a bounded path in the predecessor graph. Only then does projection add direct source
pointers and `ALIGNS_WITH_CURRICULUM` edges for the accepted Item knowledge. This is review, not an
automatic classifier: lexical retrieval proposes bounded evidence, while the reviewed binding is
the unit-alignment authority. A low-quality or irrelevant Evidence Bundle remains immutable history
and is never silently substituted into a later binding.

Lexical seed ranking uses distinct query-term membership and bounded inverse document frequency.
Rare terms therefore outrank generic terms without introducing a mutable embedding index or an
unreviewed curriculum label heuristic. Equal scores are ordered by immutable node ID. Candidate,
edge-expansion, and result counts remain explicitly bounded; replay against one snapshot is
deterministic.

## 6. Editorial and HWPX compatibility convergence

The compatibility worker receives the exact Item content plus the two authority references as
staged, untrusted read-only files. Its output records:

- `COMPATIBLE`, `NEEDS_ADAPTATION`, or `BLOCKED`;
- source-anchored item evidence for every issue;
- the exact authority and rule locator for every issue;
- deterministic Markdown/HWPX projection checks and any required lossless adaptation;
- whether the exact revision tuple is `OPEN` or `CLOSED`.

`COMPATIBLE` is valid only with no issues, no lossy transformation, and all four deterministic
checks passing. For legacy V1 Item content, content-contract validation may pass, but Markdown
projection and losslessness fail until a reviewed V2 Item Revision exists; EOM never fabricates the
missing editorial fields. For V2, the server validates the canonical JSON, exact Markdown
serialize/parse round trip, stored Markdown byte identity, and a successful HwpQuestionEditor build
for the exact executable profile. `NEEDS_ADAPTATION` or `BLOCKED` requires at least one authority-grounded issue and
remains open. No issue may cite an EOM-authored taste rule. A closed exact tuple is reused without a
new Codex job; a changed Item, prompt, HWPX profile, or compatibility policy opens a fresh tuple.

Compatibility observations remain an editorial sidecar. They may gate HWPX delivery or propose a
new Item Revision through the normal review flow, but they are not scientific facts and are not
projected into the Education Graph.

## 7. Primary access patterns and data structures

| Access pattern | Structure or index | Expected cost |
| --- | --- | --- |
| source history for one Item Revision | existing B-tree `(source_kind, source_revision_id, created_at DESC)` | `O(log n + k)` |
| exact analysis replay | existing unique idempotency key | `O(log n)` |
| lexical retrieval seed | B-tree `(snapshot_revision_id, term, node_id)` plus per-term frequency | `O(log n + k)`, bounded `k` |
| reviewed unit-path proof | indexed immutable adjacency, maximum 3 hops | bounded by explicit frontier limit |
| unit retrieval | immutable Graph adjacency plus curriculum closure | bounded by retrieval policy |
| graph evidence deduplication | stable node/edge keys and source-pointer sets | expected `O(1)` in-memory membership |
| compatibility exact tuple history | B-tree by canonical tuple SHA-256 and creation order | `O(log n + k)` |
| one terminal result per exact tuple | partial unique index where state is `OPEN` or `CLOSED` | `O(log n)` |
| open compatibility work | partial B-tree on state and creation order | `O(log n + k)` |
| append-only audit history | monotonic event sequence per run | `O(log n)` append/lookup |

Graph publication uses keyed maps and sets while combining proposals; it does not repeatedly scan
lists for identity or deduplication. PostgreSQL stores only identities, states, small indexed values,
and Artifact pointers. Item JSON, Markdown, images, HWPX, and complete worker results remain Artifact
members in NAS.

The Item-alignment binding is a small frozen value object inside the reviewed structure manifest;
no large evidence body or Item payload is duplicated in PostgreSQL. A new persistent table is not
needed because publication already materializes source pointers and adjacency rows under the new
snapshot revision. Frequent lookups continue to use the existing snapshot/node, snapshot/edge,
curriculum-unit, Evidence Bundle revision, retrieval-request, and Artifact revision indexes. The
publication pass is linear in accepted proposals plus emitted nodes and edges; the bounded path
proof visits at most three explicitly capped frontiers.

Expected scale is hundreds of thousands of Item Revisions, millions of source pointers, and many
immutable Graph Snapshots. Snapshot materialization is linear in the selected accepted runs and
edges; online retrieval is bounded by indexed adjacency and explicit evidence budgets.

## 8. Transactions, concurrency, retry, and idempotency

Knowledge Analysis retains its existing state machine and unique idempotency boundary. Proposal
validation and Artifact commit finish before acceptance. Graph publication locks the logical corpus
and commits one new immutable snapshot revision atomically.

Approved Item publication additionally requires that the V3 structure's predecessor snapshot equal
the corpus current snapshot at transaction time. Concurrent publication therefore fails instead of
rebasing or resolving “latest.” An exact command replay returns the already-published result through
the existing request idempotency boundary; a different structure or source set under the same key
fails. Artifact publication, projection rows, snapshot state, and the corpus current pointer remain
one application transaction/NAS commit boundary. A dangling bundle, stale predecessor, missing
reviewer, non-`MINOR` target, missing evidence node, or unsupported path fails before current-pointer
advance.

Editorial compatibility uses the same pattern: idempotent request creation, one workflow
submission, immutable proposal commit, deterministic validation, and terminal result commit. A
response-loss replay with the same idempotency key returns the same run; the same key with different
input fails. At most one `OPEN` or `CLOSED` result may exist for an exact revision tuple. Operationally failed
runs remain immutable history, and an explicit reviewed successor may name exactly one failed
predecessor until the tuple closes. Automatic model retry is disabled. An `OPEN` editorial result
is not retried against unchanged Item bytes: adaptation produces a new Item Revision and therefore
a new tuple.

Unit-analysis failures do not erase prior accepted evidence and do not block unrelated items.
Compatibility failures do not block unit knowledge accumulation, but a blocking compatibility result
may prevent HWPX delivery for that exact Item Revision.

## 9. Dependency direction and ownership

JSON Schema and Pydantic value objects live in Catalog contracts. Application commands and services
coordinate existing knowledge analysis and the new compatibility lifecycle. Infrastructure adapters
resolve PostgreSQL, Artifact/NAS, HWPX, filesystem, HTTP, and worker execution boundaries. Domain and
contract packages do not import those adapters. The Web/API exposes typed commands and views only;
it contains no graph, compatibility, or editorial business rules.

## 10. Rejected simpler alternatives

- **Put every legacy item directly into a prompt:** rejected because it duplicates large payloads,
  loses revision provenance, and bypasses bounded Graph retrieval.
- **Store one mutable summary per unit:** rejected because later evidence would overwrite history and
  prevent reproducibility.
- **Treat the team prompt as Graph knowledge:** rejected because editorial instructions are not
  curriculum or scientific facts and have a different convergence lifecycle.
- **Run compatibility forever with unit learning:** rejected because an unchanged, proven compatible
  tuple adds cost without new evidence.
- **Publish extraction proposals directly:** rejected because only approved Item Revisions may enter
  the existing Graph publication boundary.
- **Build a parallel graph:** rejected because the current ontology, snapshot publisher, retrieval
  service, and Evidence Bundle boundary already own this responsibility.

## 11. Implementation and acceptance sequence

1. Add Draft 2020-12 request/result contracts for editorial compatibility and exact reference
   provenance.
2. Add Pydantic validation, schema resources, registry validation, and negative pointer/convergence
   tests.
3. Add pointer-only compatibility run/event persistence with composite idempotency and partial work
   indexes.
4. Add Catalog application commands and Orchestrator staging/validation; workers cannot reach DB or
   NAS.
5. Add a coordinator that schedules the existing approved-item Knowledge Analysis track and the
   compatibility track independently.
6. Import and approve the already validated one-item legacy extraction through the existing
   acceptance/origin/Item boundaries, then execute one real analysis pair.
7. Retrieve a fresh evidence bundle from the exact predecessor snapshot, review its bounded graph
   path to the intended curriculum unit, append the V3 Item alignment, and publish a V6 Graph
   Snapshot. Verify the new snapshot includes the exact accepted Item source pointer and direct unit
   edge, while the predecessor remains byte-identical.
8. Begin corpus processing from deterministic non-conflicting source-bundle proposals, continuing
   independently while conflicts remain in review.

Completion requires schema validation, formatter, linter, strict type checking, focused unit and
integration tests, missing/stale/hash/idempotency/concurrency coverage, deployment verification, one
real result inspection, and confirmation that no EOM-authored content or format restriction entered
the compatibility authority set.
