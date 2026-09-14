# ADR 0085: Origin-scoped automatic Item curriculum alignment

## Status

Accepted for implementation.

## Responsibility and boundary

Catalog publishes an already accepted generated Item analysis into the current Integrated Science
Graph. For a mock-exam Item, the immutable production slot supplies one authoritative `MINOR`
curriculum unit. Catalog must prove that unit through a new automatic Graph-RAG policy before it
commits a structure Artifact or advances the current Graph pointer. Human Item approval is not
relabelled as a human-reviewed curriculum alignment.

## Canonical source and revision model

The canonical origin is the persisted Workflow request and its pinned mock-exam production
occurrence, resolution, registered Item Revision, accepted analysis result, and official review
eligibility receipt. The target curriculum identity is the exact `curriculum_selected_unit_key`
from that immutable slot, resolved in the predecessor Graph to a framework revision, curriculum
unit ID, and graph node ID. Existing automatic-alignment policies 1.0 through 1.2 and Graph
structure/snapshot/publication contracts remain byte-for-byte immutable. Policy 1.3, structure V6,
snapshot V9, and publication V6 are additive successor revisions.

## Required pointers and resolution checks

Each scoped retrieval pins the predecessor Graph Snapshot Revision, access-policy revision and
hash, operator and permission hash, analysis run, selected MINOR unit scope, topic keys, Evidence
Bundle Revision, manifest Artifact Revision, and request/content hashes. Policy 1.3 requires:

- an exact non-descendant `CurriculumRetrievalScope` rooted at the originating MINOR unit;
- the root unit and framework revision to resolve in the predecessor snapshot;
- the root unit's graph node to occur directly in the selected Evidence Bundle node set; and
- the resulting automatic alignment to contain exactly that one root unit.

Missing, stale, non-MINOR, indirect-only, hash-mismatched, or differently scoped evidence fails
before structure or Graph publication. No latest-revision substitution and no post-retrieval unit
union is permitted.

## Access patterns, data structures, scale, and complexity

The production boundary validates exactly 25 ordered analysis/Workflow pairs. It builds maps keyed
by analysis run and curriculum unit key for O(1) membership and deduplication, then performs indexed
primary/unique-key resolution for each pinned unit and Evidence request. Retrieval remains bounded
by the existing 64-node/8-document budget. Policy 1.3 selects one root with one indexed unit lookup
and set membership, O(n) time and O(n) temporary space for at most 64 evidence node IDs. The final
25-member validation is O(25). Existing Graph and curriculum B-tree/primary-key indexes cover these
lookups; no database migration or new index is required.

## Transaction, concurrency, failure, retry, and idempotency

Evidence Bundle publication remains its own immutable Artifact/database boundary. Scoped requests
use a new deterministic idempotency namespace, so they cannot conflict with historical unscoped
1.2 requests. Structure/projection/snapshot Artifacts are immutable, and the final corpus-current
transition remains one compare-and-swap Catalog transaction against the pinned predecessor. A
retry reuses exact scoped Evidence and the same final publication identity; changed slot, Graph,
policy, topic, operator, permission, or hash fails closed.

## Dependency direction and ownership

Canonical JSON Schema 2020-12 contracts and frozen Pydantic models define the successor protocol.
Catalog application services implement retrieval, validation, Artifact materialization, and Graph
publication. The mock-exam coordinator supplies only typed identities and remains the sole workflow
orchestrator. Workers do not communicate, publish Graph state, or write NAS.

## Simpler alternatives rejected

Appending the slot unit after unscoped retrieval would create an unsupported edge. Reusing
`ApprovedItemCurriculumAlignmentBinding` would falsely represent ordinary Item approval as a
human-reviewed curriculum alignment, which the existing automatic-alignment ADR explicitly
forbids. Weakening the originating-slot gate would allow semantically misplaced Items into
assembly. Mutating policy 1.2 or released V4/V5/V8 schema bytes would break immutable replay.
