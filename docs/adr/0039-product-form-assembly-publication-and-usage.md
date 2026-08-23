# ADR 0039: Separate Product, Form, Assembly, Publication, Usage, and Distribution

## Status

Accepted

## Context

EOM already has logical Deliverables, Deliverable Revisions, mutable Usage Plans, and immutable
Usage Records. It also needs to represent a product such as “00모의고사”, its forms 1 through 12,
the exact ordered Item Revisions placed at each question number, publication artifacts, and later
distribution history.

A graph edge alone cannot enforce ordered placement, transactional uniqueness, or immutable
publication history. A single undifferentiated “usage” table would mix planning, assembly,
publication, distribution, and student activity.

## Decision

The existing `Deliverable` remains the logical **Product** identity and
`DeliverableRevision` becomes the immutable **Product Revision** boundary. Existing fields and rows
retain their V0 meaning; current `edition` is preserved as a legacy initial label while future
edition/variant metadata is pinned in the revision.

Additive future entities are:

```text
Deliverable (Product logical identity)
  -> DeliverableRevision (Product Revision)
      -> ordered AssessmentFormRevision pointers

AssessmentForm (stable form/session identity within Product)
  -> AssessmentFormRevision
      -> one released AssessmentAssemblyRevision pointer

AssessmentAssemblyRevision
  -> ordered immutable ItemPlacement values
      -> exact ItemRevisionPointer

PublicationRevision
  -> exact Assembly Revision
  -> layout/template/profile revisions
  -> output Artifact Revision pointers

UsageRecord
  -> exact Item Revision
  -> exact Product/Deliverable Revision
  -> exact Form, Assembly, and Publication revisions for new-version records
  -> section, position, page, points, and usage role

DistributionEvent
  -> Publication Revision
  -> aggregate channel/cohort pointer and counts only
```

`ItemPlacement` is an ordered frozen value inside an immutable Assembly manifest, not a separately
mutable logical item. At minimum it contains section, positive position, optional points, usage
role, and a complete Item Revision pointer. `(assembly_revision_id, section, position)` is unique.
Canonical serialization and SHA-256 make assembly output deterministic.

Usage planning remains separate. A plan may reference the intended Product/Form and preferred Item
Revision. Publication fulfillment creates immutable Usage Records from the released Assembly and
Publication Revision; it never converts or mutates the plan into history. Existing V0 Usage Records
remain valid without invented Form/Assembly/Publication pointers. New contract-version records
require those pointers once the additive schema is activated.

Reordering, replacing, rescoring, correcting, or changing a layout/template creates a new Assembly
or Publication Revision at its owning boundary. It never mutates an Item Revision or historical
Usage Record.

Distribution is not placement. An aggregate Distribution Event may record that a Publication
Revision reached a reviewed cohort/channel. Per-student identity, answers, scores, and attempts are
outside the general education graph and require a separate protected learning-record design.

## Graph Projection

The graph projects pointer-backed Product/Form/Placement/Usage edges for search and analysis.
Canonical ordering and evidence remain in Assembly manifests and Usage Records. A projection that
disagrees is rejected or rebuilt; the graph never repairs the ledger.

## Transactions and Idempotency

Assembly publication validates all Item pointers, unique positions, score/blueprint constraints,
and manifest hash before atomically inserting the immutable revision and moving a current pointer.
Publication and Usage fulfillment lock the plan/publication boundary and use unique source and
placement keys. Codex or rendering occurs outside the transaction.

Legacy spreadsheet import is two-stage: immutable source intake and schema-valid mapping proposal,
then reviewed canonical commit. Ambiguous or fuzzy Item matches remain quarantined. Replay succeeds
only for the same source revision, mapping-contract revision, row identity, and normalized hash.

## Access Patterns and Indexes

- Product and Form key lookup: unique B-tree keys;
- ordered forms and placements: `(product_revision, ordinal)` and
  `(assembly_revision, section, position)` indexes/constraints;
- reverse usage by Item Revision: B-tree on exact `item_revision_id`;
- released publication lookup: indexed lifecycle and Form/Assembly/Publication pointers;
- graph navigation: derived snapshot-scoped sparse adjacency.

Expected exact and ordered retrieval is O(log n + k). Full Item payloads and publication binaries
remain Artifact Revisions, not database JSON/BLOB copies.

## Consequences

“Item A was form 1 question 12” is independently auditable and remains true when Item A later gets
a new current revision. One Product can contain multiple forms and one Item Revision can have many
valid Usage Records. Existing Usage Ledger history survives additive migration.

The simpler alternatives were rejected: encoding forms in free-text `section` cannot provide
revision identity; treating each form as an unrelated Product loses product grouping; making graph
edges canonical weakens ordering and transactions; and putting learner activity into the same graph
creates an unjustified privacy boundary.
