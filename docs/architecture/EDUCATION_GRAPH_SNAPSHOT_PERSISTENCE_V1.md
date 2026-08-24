# Education Graph Snapshot Persistence V1

Status: Phase 8 implementation design

Last reviewed: 2026-08-24 UTC

## 1. Responsibility and boundary

Catalog owns publication of one logical Education Knowledge Corpus and its immutable graph
snapshots. Knowledge Analysis owns accepted extraction results; Artifact storage owns projection
bytes; Item Registry owns Item and Item Revision payloads. The graph stores only typed adjacency,
curriculum closure, item-element references, provenance pointers, lifecycle, and hashes. It never
becomes a second source for source documents, Item JSON, product placement, or Usage history.

The publisher is deterministic application code. A Codex worker can propose an analysis Artifact,
but cannot publish a snapshot, access PostgreSQL, or write NAS.

## 2. Canonical source and revision model

```text
KnowledgeCorpus
  -> immutable KnowledgeCorpusRevision
  -> KnowledgeGraph
      -> immutable KnowledgeGraphSnapshotRevision
          -> snapshot-scoped nodes and edges
          -> revision-scoped curriculum closure
          -> immutable ItemElement pointers
          -> Artifact-backed deterministic projections
```

A mutable current pointer exists only on the corpus and graph logical rows. Every workflow,
retrieval request, Evidence Bundle, event, and historical query pins a snapshot revision. A
publication command contains accepted Knowledge Analysis run IDs and, when reviewed curriculum or
Item structure is part of the snapshot, one immutable structure-manifest Artifact pointer. The
publisher resolves every exact accepted-result, proposal, and structure-manifest Artifact Revision
rather than accepting copied nodes, arbitrary dictionaries, or filesystem paths.

## 3. Required pointers and resolution

Before publication each analysis run must be `ACCEPTED`; its source, accepted-result Artifact,
proposal receipt, nodes, edges, anchors, and component members must agree on logical/revision IDs,
schema, media type, lifecycle, member path, byte length, and SHA-256. Every proposed node and edge
must cite at least one resolvable source anchor. Item-element rows additionally pin Item ID, exact
Item Revision, item-content Artifact Revision and SHA, schema version, element kind, and stable
element ID. No omitted revision resolves through a mutable current pointer.

## 4. Access patterns and structures

Dominant operations are exact snapshot lookup, sparse outbound/inbound adjacency, curriculum
subtree traversal, set-membership filtering by Item element kind, provenance lookup, deterministic
ordered export, and atomic current-pointer publication.

- unique B-tree keys cover corpus key, snapshot revision, node/edge identity, and accepted analysis
  membership;
- adjacency indexes are `(snapshot_revision_id, from_node_id, edge_type)` and the inverse;
- curriculum closure is keyed by `(snapshot_revision_id, framework_revision_id, ancestor_unit_id,
  descendant_unit_id)` and indexed for descendant lookup;
- Item elements are unique by `(snapshot_revision_id, item_revision_id, element_kind, element_id)`
  and indexed by exact Item Revision and kind;
- source-pointer rows index exact Artifact Revision and source revision.

Expected indexed lookup is `O(log n + k)`. Snapshot export is `O(n + e)`. Initial scale is tens of
frameworks, thousands of curriculum/source nodes, and up to hundreds of thousands of item elements.
PostgreSQL adjacency remains simpler than a second graph datastore at this scale.

## 5. Publication transaction and concurrency

Projection files are deterministically serialized and committed through the existing
Orchestrator-owned Artifact boundary before the short publication transaction. The final
transaction locks the logical corpus/graph rows, rechecks the expected previous snapshot, inserts
the immutable corpus revision, snapshot, nodes, edges, provenance, closure, and item elements, and
moves both current pointers atomically. A unique idempotency key plus canonical request hash makes
same-input replay return the same snapshot and makes changed input fail closed. Concurrent
different publication for the same prior snapshot loses the current-pointer comparison and
publishes no database snapshot. An already committed but unreferenced projection Artifact is safe
orphan evidence and may be garbage-collected only by a separately reviewed Artifact policy.

## 6. Failure, retry, and rollback

Dangling endpoints, self edges, duplicate stable keys, illegal endpoint pairs, curriculum cycles,
incomplete transitive closure, duplicate Item elements, unsupported source class, general-knowledge
claims without attribution mode, stale current pointers, or any pointer/hash mismatch fail with a
stable code. No partial snapshot becomes current. Retry uses the same idempotency key and exact
request hash; it never substitutes latest sources. Rollback moves selection to a previously pinned
published snapshot through a new reviewed publication/selection action; immutable rows and
Artifacts are never rewritten or deleted.

## 7. Dependency direction and simpler alternative

Frozen graph contracts remain in `catalog_contracts`; Catalog application services own validation
and transactions; SQLAlchemy and filesystem/NAS adapters remain infrastructure. API, CLI, and GUI
may submit typed commands but contain no graph business rules.

Keeping only JSONL artifacts was rejected because Q1/Q2 would repeatedly scan and parse complete
files. Storing complete source or Item payloads in graph rows was rejected as duplication. A graph
database was rejected because the initial accepted queries are served by indexed adjacency and
closure with simpler transactional publication and historical replay.
