# Document grouped image style dataset splits

Status: Accepted for implementation, 2026-10-03 UTC.

## Responsibility and canonical source

The image contracts package owns a pure, deterministic split of approved crop metadata, not
ingestion, image classification, training, or storage. Existing reviewed crop sets and their pinned
PDF source members are canonical. Object line art and raster scenes remain separate tracks;
scientific diagrams remain deterministic Python/SVG outputs. Existing frozen splits are not edited.

## Identity and resolution

A caller supplies the logical split ID, immutable revision ID and UTC timestamp. A separate
canonical document SHA-256 binds the complete split. Each sample pins its crop, source PDF,
depiction, exam-group hash and reviewed near-duplicate cluster. The split also pins its reviewed inventory and
internal-use authorization. A sample ID hashes its immutable metadata; this is a local member key,
not a replacement for Artifact identity. The Orchestrator adapter must check target existence,
schema, media, permission, lifecycle, member/hash and authorization scope before staging. Contract
validation alone does not certify image bytes, rights, review quality or successful training.

## Operations and structures

The main operations are grouping, membership, duplicate rejection and stable ordered iteration.
Union-find joins samples sharing a source PDF logical ID, PDF byte hash, exam group or reviewed duplicate
cluster. This joins transitive bridges across documents and prevents aliases of one PDF entering
different partitions. Dictionary indexes avoid pairwise comparison. Exact duplicate crop hashes
are rejected rather than silently dropping provenance. Source documents are indivisible even when
a split overshoots its target. Previously designated holdout sample IDs force their entire group
into holdout. Unknown holdout IDs fail explicitly.

At most 10,000 samples are accepted. Group construction takes O(n alpha(n)) time and O(n) space;
stable ordering takes O(n log n). Input iteration is bounded to 10,001 entries to detect overflow
without consuming an unbounded iterator. Assignment places smaller groups first, with seeded hashes
of sorted group member IDs as the tie breaker, never Python's randomized hash. This avoids consuming
a large document group before small evaluation quotas; it is a deterministic greedy policy, not an
exhaustive partition-feasibility solver. Maps/sets enforce partition consistency in O(n). Counts
are derived, not separately persisted. Near-duplicate detection stays in the existing crop review
and perceptual-index boundary; a null cluster means no cluster was declared by that reviewed
inventory, not a guarantee of visual uniqueness.

## Concurrency and ownership

The function has no I/O or shared state. Concurrent calls with identical values produce identical
bytes. The Orchestrator commits the manifest through its existing idempotent Artifact application
boundary; workers receive staged files and never write NAS. No DB table, queue, index, service or
dependency is added. Infrastructure depends on the public contract API, never the reverse.

## Failure and alternatives

Insufficient independent groups or sample counts produce `INSUFFICIENT`, not fake duplicated
samples or a weakened full-training gate. Partition minima are an explicit frozen experimental
input; readiness is only relative to those minima, not production authorization. Default full
experiment targets are 100 train, 24 validation and 32 holdout. Smaller micro probes keep their
separate existing evaluation-only authorization. Failures in identity, hash, UTC, membership or
partition consistency reject the manifest; retry does not change seeds or choose another revision.

Randomly splitting crop rows is simpler but leaks the same exam and similar illustrations into
training and evaluation. Splitting only by PDF misses cross-document duplicate clusters and PDF
aliases. This small pure contract closes those boundaries without a new dataset framework.
