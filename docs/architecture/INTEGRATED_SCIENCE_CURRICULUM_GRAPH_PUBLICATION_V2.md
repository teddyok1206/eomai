# Integrated Science Curriculum Graph Publication V2

Status: implementation design

Last reviewed: 2026-08-31 UTC

## 1. Responsibility and boundary

Catalog Contracts owns one reviewed, SHA-pinned Curriculum Outline resource. Knowledge Analysis
continues to own accepted textbook observations. Graph publication joins those two independent
authorities without changing either one: the outline supplies reviewed hierarchy, codes, Korean
display labels, and stable graph identities; accepted analyses supply pinned source evidence,
concepts, relationships, and page anchors.

Workers do not create framework revisions, publish graph state, write PostgreSQL, or write NAS.
The Catalog application service validates and commits framework and graph Artifacts through its
existing storage boundary.

## 2. Canonical source and revision model

The reviewed source-controlled
`eom-integrated-science-editorial-outline-v1.json` is the canonical authoring source. Runtime
identity is not its path or label. Publication materializes it once into the pointer-oriented
structure Artifact already owned by the Graph publication boundary:

```text
KnowledgeGraphStructureManifest V2
  -> exact framework key and deterministic immutable framework revision identity
  -> pinned outline key, revision, and SHA-256
  -> immutable ordered curriculum unit value objects
  -> sorted accepted Analysis Run IDs
  -> exact analysis-run to curriculum-unit bindings
  -> optional approved Item element bindings

KnowledgeGraphSnapshotRevision
  -> exact accepted results
  -> exact structure-manifest Artifact Revision
  -> snapshot-local curriculum units and transitive closure
  -> deterministic alignment edges and projections
  -> every node/edge source pointer pins its originating Analysis Run
```

Framework logical key, deterministic immutable revision ID, unit ID, Artifact ID, Artifact
Revision ID, and content hash remain separate. This release intentionally does not introduce a
second mutable Curriculum registry or new framework tables: the approved structure Artifact is the
publication authority. Historical V1 structure manifests and Graph Snapshots are not rewritten or
reinterpreted.

## 3. Pointer and resolution checks

Before structure commit or publication, Catalog verifies:

- the outline resource is a regular packaged resource with its pinned SHA-256 and schema;
- framework key/revision identity and pinned outline identity are coherent;
- the structure Artifact and Artifact Revision are approved, agree on logical identity, member
  path, schema, media type, byte count, and SHA-256;
- all 43 unit identities are unique and exactly ordered as 2 volumes, 6 large units, and 35 middle
  units;
- every non-root parent resolves in the same immutable revision and has the expected level;
- every analysis binding names one accepted run in the publication source set and one existing
  framework unit;
- each analysis source's reviewed `curriculum_unit_keys` agrees exactly with its bound middle unit;
- the complete 495-range source set is gap-free, non-overlapping per document revision, and pins
  the expected 1,702 physical pages;
- dangling, stale, mixed-revision, wrong-label, wrong-code, wrong-hash, or extra bindings fail
  closed.

## 4. Access patterns, structures, and indexes

Dominant operations are exact framework-key lookup, immutable revision lookup, code lookup,
ordered child traversal, graph-root lookup, analysis-to-unit lookup, subtree traversal, lexical
lookup, and append-only publication history.

- exact structure retrieval: Artifact/Artifact Revision primary keys and immutable content hash;
- unit lookup while projecting: maps keyed by unit ID, unit key, code, and graph stable key;
- ordered traversal: immutable tuple sorted by unit key plus adjacency map keyed by parent ID;
- analysis membership: map keyed by analysis-run ID during projection and unique manifest entries;
- repeated ranges of one Document Revision: one transaction-scoped immutable artifact/dependency
  cache, while each range request, accepted result, proposal, and hash is still validated;
- node merge: hash map keyed by stable key, with a set of exact source labels and source pointers;
- adjacency and closure: existing indexed snapshot-local adjacency list and transitive closure.
- source-pointer lookup: snapshot/node/Analysis Run composite identity; anchor IDs are local to an
  Analysis Run and are never treated as globally unique within one Document Revision.

One Document Revision may contribute hundreds of non-overlapping analysis ranges. Source-pointer
rows therefore include `analysis_run_id` and reference the snapshot's exact accepted-analysis
association. Retrieval groups pointers by Analysis Run and immutable artifact member, resolves the
exact range request, and selects at most one bounded entry per canonical Artifact member/use. The
canonical Projection Artifact retains every exact range pointer even when the bounded Evidence
Bundle selects only the highest-ranked range.

Structure pointer lookup is `O(log n)` through existing Artifact indexes, in-memory unit lookup is
`O(1)` average, projection merge is `O(nodes + edges)` plus deterministic sorting, and closure
generation is `O(units * depth)` with a maximum current depth of three. At 43 framework units and
495 source ranges, this is bounded and does not justify a new framework table set or a separate
graph database.

## 5. Display-label and alias policy

Stable key and node type define merge identity; a display label does not. Publication V2 uses the
additive Projection V3 contract to preserve every exact, safe worker label as an immutable alias.
Its provenance remains recoverable through the snapshot's pinned accepted-analysis results and
node source pointers. It chooses the
preferred label deterministically:

1. a reviewed framework label wins for canonical curriculum nodes;
2. otherwise, for a `ko-KR` corpus, labels containing Hangul rank before labels without Hangul;
3. higher independent source occurrence ranks first;
4. ties use canonical Unicode/code-point ordering.

No machine translation or silent text normalization is performed. A node-type conflict still
fails closed. Lexical indexing uses the stable key, preferred label, and every alias, so English
worker terminology remains searchable while Korean product display remains consistent.

## 6. Curriculum-to-analysis alignment

The publisher derives one `ALIGNS_WITH_CURRICULUM` edge from each eligible knowledge node in an
accepted analysis to each exact middle unit assigned to that analysis range. It also emits reviewed
`CONTAINS_CURRICULUM_UNIT` edges for the framework hierarchy. Alignment provenance reuses the
analysis node's exact source pointers; hierarchy identity and Korean labels are independently
proven by the pinned Structure Manifest Artifact.

This makes a curriculum subtree a real retrieval seed rather than a disconnected classification
row. Retrieval remains bounded to the selected root and its descendants before traversing a
maximum of two graph hops. The public GUI grounding capability stays disabled until the complete
published snapshot and retrieval acceptance pass.

## 7. Transaction, concurrency, idempotency, and failure

Structure Artifact commit and graph publication are separate transactions with separate
idempotency keys and canonical request hashes. Same-key/same-input replay returns the existing
immutable result; same-key/different-input fails. Concurrent Graph publication locks the logical
current pointer and requires the exact expected prior revision. The losing transaction publishes
no database snapshot. A committed but unreferenced Artifact is orphan evidence and is not silently
adopted or deleted.

One-shot live rollout uses one authorization marker and one attempt marker for structure Artifact
commit, one for Graph publication, and one for Evidence Bundle retrieval. There is no
automatic retry with a fresh key. A failed step preserves its inputs and first error boundary.

The additive database migration backfills historical pointer rows only when each legacy pointer
resolves to exactly one snapshot Analysis Run. Ambiguous legacy data fails migration closed rather
than selecting a run implicitly. Downgrade is rejected after history uses the new run-scoped
identity if removing that dimension would recreate duplicate pointer identities.

## 8. Dependency direction

JSON Schema and frozen value models live in `catalog_contracts`. Catalog application services own
structure materialization, pointer resolution, projection, and transactions. SQLAlchemy,
filesystem/NAS, and
operator scripts remain infrastructure adapters. API/GUI may later expose read-only framework and
capability projections but do not own framework or Graph business rules.

## 9. Simpler alternatives rejected

Passing the Markdown outline directly to the Graph publisher was rejected because a repository
path is not runtime identity and cannot be pinned by historical retrieval. A separate mutable
Curriculum registry was rejected because this fixed 43-unit reviewed hierarchy has only one real
runtime consumer today and the immutable Structure Manifest already supplies its revision and
pointer boundary. Reusing structure
manifest V1 was rejected because it assumes curriculum nodes already exist in worker proposals and
does not prove a resolvable framework authority. Hard-coding 43 nodes in the GUI or retrieval
service was rejected as duplicated business state. Translating or overwriting worker labels was
rejected because it destroys provenance. Publishing the 495 analyses without hierarchy was
rejected because the curriculum selectors would still have no usable subtree root.

## 10. Acceptance

Source acceptance requires schema-first validation, old V1 hash preservation, deterministic
manifest/projection serialization, alias merge and conflict tests, missing/stale/hash tests,
idempotent and concurrent publication tests, exact run-scoped pointer resolution for repeated
Document Revision ranges, migration upgrade/downgrade checks, runtime privilege tests, strict
typing, format/lint, and package isolation checks.

Live acceptance requires exactly 43 framework units, 119 closure rows (43 self + 41 direct-parent
+ 35 grandparent), 495 accepted analyses, 1,702 gap-free pages, no duplicate source page in the new
snapshot, Korean canonical labels for all framework nodes, resolvable textbook provenance, one
immutable Graph Snapshot, and one bounded Evidence Bundle that resolves through a selected
curriculum subtree. The historical pilot snapshot remains immutable and addressable.
