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

An accepted analysis and a published Graph snapshot pin the exact Item Revision they originally
validated. A later Item Revision may supersede or retire that source revision; incremental Graph
publication therefore re-resolves the pinned historical revision and its exact component Artifact
and hash instead of requiring it to remain current or silently substituting the latest revision.
New analyses still require a currently `APPROVED` Item Revision. Historical replay accepts only the
terminal `APPROVED`, `SUPERSEDED`, or `RETIRED` lineage, with complete approval or supersession
evidence where applicable.

That historical replay rule does not authorize a new PAST_EXAM placement. Before first publication,
the shared origin resolver requires the Item and Occurrence logicals to be active at their pinned
current revisions, the Item Revision to be `APPROVED`, and the Occurrence and source-bundle
revisions to be `REVIEWED`. Once published, the immutable snapshot remains historical evidence.

## Pointers and resolution checks

An automatic alignment pins the accepted result pointer, prior snapshot revision, Evidence Bundle
and revision, retrieval request and hash, Evidence Bundle manifest pointer, evidence node IDs,
derived MINOR curriculum unit IDs, requesting operator, automatic policy version/hash, and a
self-content hash. The accepted-result pointer permits only the original approved-Item result V2 or
the visual past-exam Item result V9. That closed union preserves old snapshots while allowing exact
PNG-backed analysis to enter the same automatic alignment flow; unrelated document and multimodal
result versions remain invalid. Publication re-resolves every pointer, released policy, permission
hash, evidence entry, graph node, and curriculum unit, then recomputes the policy result exactly.

## Access patterns, structures, and indexes

- Candidate lookup first reads allowlisted work units in stable
  `(batch.created_at, batch ID, work-unit ordinal, work-unit ID)` order and groups them by exact
  acceptance ID. A single indexed decision read derives the allowlisted immutable promotion
  registration keys. Accepted, not-yet-graphed analyses enter scope when either their untrusted JSON
  acceptance string is allowlisted or their one-to-one Item Revision has an allowlisted promotion
  key. Neither anchor prefilters the request schema, JSON source discriminator, or persisted source
  kind, and every in-scope request must fully parse as exact V9 PAST_EXAM before use. The independent
  anchors expose either JSON-acceptance drift or persisted source/Item-pointer drift; an unrelated
  malformed request cannot block the configured batches, while an in-scope discriminator or payload
  defect is an explicit error.
  If both anchors are destroyed, the row can no longer be attributed to this batch locally; final
  corpus coverage detects that missing leaf rather than silently certifying completion.
  The state/history and current-snapshot indexes bound the analysis scan; a new JSON expression
  index is not justified for this one-time 520-Item corpus.
- One authoritative resolver serves candidate preflight, pre-retrieval publication validation,
  occurrence-binding construction, and final Graph publication validation. It performs ten
  fixed-count indexed bulk reads and builds maps/sets keyed by Item Revision, profile, occurrence,
  bundle, acceptance, and Item identity. It requires exactly one profile, occurrence relation,
  assessment-bundle derivation, and matching accepted decision, then cross-binds lifecycle, current
  pointers, rights, source/Artifact hashes, selected work-unit lineage, and the immutable V9 source.
  Invalid rows raise a stable error; only a fully valid high-school grade-1 March origin is a policy
  exclusion. All in-scope pending rows are classified before the 16-Item output limit, so excluded
  rows do not consume the limit and corrupt rows cannot hide behind a valid prefix. Reused
  acceptances retain one candidate and every allowlisted membership must describe the same lineage.
- For `B` allowlisted work units, `A <= 520` pending analyses, and `R` canonical origin rows, a
  cycle uses `O(B + A log A + R)` time and `O(B + A + R)` temporary space; indexed database lookup
  remains `O(log n + k)` per bulk relation. Revalidating the shrinking set each 16-Item cycle is
  bounded for this migration (under about 33 cycles) and intentionally simpler and safer than a
  mutable cache or keyset checkpoint that could skip an invalid row. The unique profile Item
  Revision key, leading profile columns of `uq_item_origin_occurrence` and
  `uq_item_origin_derivation`, revision primary keys, and `(extraction_batch_id, ordinal)` work-unit
  constraint are the dominant lookup paths.
- Conceptual proposal-node keys are deduplicated with a set and sorted once. If an older accepted
  analysis contains no conceptual node, the policy falls back only to its semantic Item-element and
  assessment-pattern keys. A legacy analysis containing only its semantic Item-revision key uses
  that key as the last resort, without inventing or hard-coding any subject content.
- Evidence-node membership and curriculum targets use sets/maps.
- Three-hop alignment uses a multi-source frontier map (`node -> source seeds`) and indexed inbound
  and outbound graph-edge lookups. It performs at most three adjacency queries, `O(V+E)` over the
  bounded neighborhood, with a hard association limit. Policy 1.1 retains only units with maximum
  evidence-seed support and then applies distance/ID ordering, capped at three units.
- Snapshot source membership uses existing unique constraints and indexed foreign keys.

Expected scale is fewer than 10,000 accepted sources per snapshot, at most 64 evidence seeds per
alignment, at most three traversal hops, and at most three selected MINOR units for policy 1.1.
Published policy 1.0 bindings remain replayable with their historical eight-unit cap. Publications
group up to 16 pending Item analyses to avoid one full Graph materialization per Item.

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
