# Automatic Item Curriculum Graph Publication V1

## Responsibility and boundary

The Catalog application turns already accepted, immutable approved-Item knowledge analyses into
incremental `integrated-science-textbooks` Graph snapshots. It performs no model call and no human
review. Human-reviewed alignments remain distinct and unchanged. Catalog alone creates retrieval
evidence, commits the structure/Graph Artifacts to NAS, and advances the corpus current pointer.

## Canonical source and revision model

The canonical content source is an accepted Knowledge Analysis result and its pinned proposal
members. The alignment source is an immutable Evidence Bundle against one prior Graph snapshot.
Each publication appends accepted analysis run IDs and creates a new immutable structure-manifest
revision and Graph snapshot revision. Logical corpus identity, snapshot revision, Artifact revision,
and content hash remain separate.

## Pointers and resolution checks

An automatic alignment pins the accepted result pointer, prior snapshot revision, Evidence Bundle
and revision, retrieval request and hash, Evidence Bundle manifest pointer, evidence node IDs,
derived MINOR curriculum unit IDs, requesting operator, automatic policy version/hash, and a
self-content hash. Publication re-resolves every pointer, released policy, permission hash,
evidence entry, graph node, and curriculum unit, then recomputes the policy result exactly.

## Access patterns, structures, and indexes

- Candidate lookup is an ordered indexed join from configured extraction batches to accepted
  analyses and the current snapshot membership.
- Conceptual proposal-node keys are deduplicated with a set and sorted once. If an older accepted
  analysis contains no conceptual node, the policy falls back only to its semantic Item-element and
  assessment-pattern keys. A legacy analysis containing only its semantic Item-revision key uses
  that key as the last resort, without inventing or hard-coding any subject content.
- Evidence-node membership and curriculum targets use sets/maps.
- Three-hop alignment uses a multi-source frontier map (`node -> source seeds`) and indexed inbound
  and outbound graph-edge lookups. It performs at most three adjacency queries, `O(V+E)` over the
  bounded neighborhood, with a hard association limit.
- Snapshot source membership uses existing unique constraints and indexed foreign keys.

Expected scale is fewer than 10,000 accepted sources per snapshot, at most 64 evidence seeds per
alignment, at most three traversal hops, and at most eight selected MINOR units. Publications group
up to 16 pending Item analyses to avoid one full Graph materialization per Item.

## Transaction, concurrency, failure, retry, and idempotency

Evidence, structure, projection, and snapshot Artifacts are immutable and idempotency-keyed. The
publication command pins the expected current snapshot. A concurrent advance fails with the stable
stale-current error; the next poll re-resolves the new current snapshot and creates a fresh command.
The database snapshot/current-pointer transition remains one Catalog transaction. Partial immutable
Artifacts are safe to replay and are never silently substituted. Failed Knowledge Analysis runs are
preserved and retried only as explicit fresh successor runs.

## Dependency direction and ownership

JSON Schema and frozen contract models define structure V4, publication V4, and snapshot V7.
Catalog application services depend on those contracts. The bounded SQL traversal and Artifact/NAS
operations remain Catalog infrastructure/application concerns. Workers neither publish the Graph
nor write NAS.

## Simpler alternative rejected

Putting the automation operator into V3's `reviewed_by_operator_id` would falsely represent a human
review. Publishing without a structure manifest would discard curriculum hierarchy/alignment.
Directly assigning units from labels or sample-specific terms would be content hard-coding. The V4
automatic binding keeps the reviewed framework intact while making automatic provenance explicit,
policy-bound, evidence-bound, and reproducible.

## Runtime configuration and operational acceptance

`AUTO_ACCEPT_AND_LEARN` requires the existing extraction-batch, Content Pack release, and analysis
risk-policy pins plus `EOM_LEGACY_ITEM_AUTOMATION_GRAPH_ACCESS_POLICY_REVISION_ID`. The optional
`EOM_LEGACY_ITEM_AUTOMATION_GRAPH_BATCH_SIZE` is an integer from 1 through 16 and defaults to 16.
These are immutable identities or bounded scheduling controls, not content rules.

The automatic application order is: reconcile one active analysis, publish one full pending Graph
batch, create one explicitly allowlisted fresh successor for a failed analysis, or promote and
schedule one newly accepted Item. A final partial Graph batch is published only after all configured
extraction work units leave active/pending states. Human review rows are never synthesized. Historic
failed runs remain immutable; recovery creates a new run ID linked by the predecessor pointer.
