# ADR 0052: Project assessment occurrences and item placements into Graph RAG

Status: Accepted

Date: 2026-09-06

## Context and responsibility

Past-examination learning already preserves immutable Item Revisions, Item Origin profiles, and
Assessment Occurrence Revisions. The Education Graph, however, only projects the learned Item's
semantic analysis and curriculum alignment. It cannot answer either dominant navigation pattern:

1. exact examination lookup by administration year, target grade, month, and subject, followed by
   ordered item iteration; or
2. curriculum-unit traversal to the exact examinations and item numbers that supplied evidence.

More importantly, the previous item-production retrieval policy excluded `PAST_EXAM`, so one-shot
Codex authoring could not receive this evidence even after successful legacy learning.

This change belongs to Catalog contracts, origin persistence, Graph publication, and knowledge
retrieval. Workers continue to return semantic proposals only. They do not invent examination
identity, mutate Graph state, or write NAS.

## Canonical sources and revision model

- `AssessmentOccurrenceRevision` is the canonical examination identity and metadata source.
- `ItemOriginProfile` plus its occurrence relation is the canonical Item-to-examination source.
- the accepted extraction decision is the canonical item number within that source bundle.
- the accepted Item knowledge analysis is the canonical semantic evidence source.
- a `KnowledgeGraphStructureManifest` pins all of those immutable pointers for one Graph snapshot.

An examination is represented as:

```text
Assessment Occurrence logical ID -> immutable Occurrence Revision
                                  -> ordered Item Placement -> immutable Item Revision
                                                             -> curriculum/concept evidence
```

The placement is not another Item and does not copy Item content. It is a small immutable value that
pins occurrence revision, Item revision, origin profile, accepted analysis, item number, and
curriculum-unit IDs.

## Protocol and pointer checks

Occurrence protocol V2 adds `target_school_level`, `target_grade`, and `administration_month`.
Registration validates the grade range for the school level, month/date agreement, current logical
revision, issuing organization, rights policy, evidence Artifact Revision, and self hash. V1 rows
remain readable but cannot satisfy a typed year/grade/month examination query.

Graph structure V5 adds immutable assessment-item placement bindings. Publication resolves every
binding against the exact accepted analysis, approved Item Revision, Item Origin profile,
Occurrence Revision, extraction decision, rights/evidence lineage, and curriculum alignment.
Projection deterministically creates `ASSESSMENT_OCCURRENCE_REVISION`,
`ASSESSMENT_ITEM_OCCURRENCE`, and `ITEM_REVISION` nodes plus typed edges. These structural node and
edge types are reserved to the projector and rejected in worker proposals.

March examinations for high-school grade 1 are valid archived source evidence but are excluded from
Integrated Science learning selection because they assess the preceding middle-school curriculum.
The raw Content Intake revision remains immutable and unchanged.

## Access patterns and data structures

Exact examination lookup uses a B-tree index over
`(graph_snapshot_revision_id, administration_year, target_school_level, target_grade,
administration_month, subject_key, item_number)` on the immutable
`assessment_item_occurrence_references` projection and returns a small ordered placement tuple. Unit
lookup first resolves the current snapshot's indexed curriculum-unit node and then uses the inbound
Graph edge index to join the same placement projection. The projection stores only typed identities,
display metadata, and hashes; Item bytes remain canonical in the referenced Artifact Revision.
Structure assembly uses dictionaries and sets for identity lookup and deduplication, followed by
deterministic tuple sorting; no repeated list scan is required.

Expected scale is at most 10,000 learned Item bindings per structure manifest. Registration and
exact examination lookup are O(log n + k). Snapshot projection is O(nodes + edges + bindings), and
bounded two-hop Evidence Bundle retrieval remains O(reachable edges) within its existing limits.
The structure Artifact is canonical snapshot input; relational graph rows are an immutable derived
projection/cache and are rebuilt atomically for each new snapshot.

## Transactions, concurrency, and idempotency

Occurrence registration retains its logical-key advisory lock and append-only revision checks.
Graph publication retains optimistic current-snapshot comparison and a single transaction for all
derived graph rows and the current pointer. Placement identity derives from pinned IDs and item
number, so replay is byte-identical; conflicting identity or hash fails closed.

Learning batches are selected explicitly. A source archive can contain excluded files, but only
reviewed non-March occurrence/bundle pointers enter a learning batch. Failed work is recorded by the
existing continue-and-collect lifecycle and never silently substituted or retried as a different
revision.

## Dependency direction and one-shot authoring

Contracts define the ontology and pointer values. Catalog application services validate canonical
records and publish/query snapshots. PostgreSQL, NAS, and graph rows remain infrastructure details.
The GUI/API construct typed retrieval requests; the orchestrator materializes the resulting
Evidence Bundle `context.md` for one-shot Codex. The released item-production preset and request
draft both allow `PAST_EXAM`, so bounded two-hop traversal from the selected curriculum unit reaches
the placement, examination, and pinned Item Revision nodes. The rendered context identifies the
source class, examination label, item number, unit labels, and immutable evidence pointer. The
orchestrator materializes only the validated, bounded `context.md`; it does not copy full Item JSON
or NAS bytes into the worker workspace. This is a release gate, not an optional administrative
view: a snapshot is insufficient if the same analyzed evidence cannot enter one-shot authoring
without direct worker communication or runtime source access.

## Alternatives rejected

Parsing year/grade/month from filenames or labels is ambiguous and not indexable. Attaching an item
number directly to an Item Revision fails when the same Item is observed in multiple examinations.
A separate examination browser table would create a parallel truth disconnected from Graph RAG.
Adding `PAST_EXAM` only to the prompt would not make the immutable evidence retrievable. The chosen
model extends the existing origin and Graph publication boundaries and uses one ontology for both
operator navigation and one-shot authoring.
