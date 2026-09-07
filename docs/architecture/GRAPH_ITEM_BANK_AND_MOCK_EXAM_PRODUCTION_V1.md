# Graph Item Bank and Mock Examination Production V1

Status: implementation design

Last reviewed: 2026-09-07 UTC

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
