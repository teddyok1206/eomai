# Product, Form, Assembly, Publication, Usage, and Distribution V1 Design

Status: Phase 6 normative design; schema and persistence are not implemented by this document.

Last reviewed: 2026-08-23 UTC

Related decisions: [ADR 0039](../adr/0039-product-form-assembly-publication-and-usage.md),
[Usage Ledger V0](USAGE_LEDGER_V0.md), and
[Graph V0 acceptance queries](EDUCATION_GRAPH_V0_ACCEPTANCE_QUERIES.md).

## 1. Responsibility and system boundary

Catalog owns Product, Form, immutable Assembly placement, Publication, and Usage history. The
existing `Deliverable` is the Product logical identity and `DeliverableRevision` is the Product
Revision boundary. Existing rows keep their V0 meaning.

Ownership is intentionally split:

```text
Deliverable/Product logical identity
  -> immutable Product Revision
      -> ordered exact Form Revision pointers

Assessment Form logical identity
  -> immutable Form Revision
      -> exact immutable Assembly Revision

Publication logical identity
  -> immutable Publication Revision
      -> exact Product/Form/Assembly revisions
      -> template/layout/profile revisions
      -> rendered Artifact Revisions

Usage Plan                    mutable intent
Assembly Revision             canonical ordered placement
Publication Revision          canonical rendered release
Usage Record                  immutable evidence of actual published use
Distribution Event            append-only aggregate delivery evidence
Graph edge                    rebuildable projection only
```

No layer copies Item content or publication bytes into PostgreSQL. Item and output bytes remain
Artifact Revisions. Per-student identities, answers, scores, and attempts are outside this domain.

## 2. Existing Product compatibility

The V0 `deliverables` and `deliverable_revisions` tables remain valid and retain their identifiers:

- `deliverable_<32 lowercase hex>` is the Product logical ID;
- `delivrev_<32 lowercase hex>` is an immutable Product Revision ID;
- `deliverable_key` remains the stable Product key;
- `deliverable_type` remains `MOCK_EXAM`, `TEXTBOOK`, `WEEKLY`, or `OTHER`;
- existing `title`, `edition`, state, metadata, and hashes are not reinterpreted.

V1 adds a typed Product Revision detail and ordered Form pointers. It does not rewrite V0 metadata
or fabricate forms for historical rows. A V0 Product Revision without V1 details remains readable
through V0 APIs but cannot satisfy a V1 Form/Assembly/Publication query.

`ProductRevisionDetailV1` contains:

| Field | Contract |
| --- | --- |
| `schema_version` | `product-revision-detail/1.0` |
| `deliverable_id`, `deliverable_revision_id` | exact existing Product pointer |
| `edition_key`, `edition_label` | stable machine key and reviewed display label |
| `variant_key` | region/channel/variant-independent stable key or null |
| `locale` | BCP-47 locale |
| `market_region_keys` | sorted unique controlled values |
| `academic_year` | optional four-digit year |
| `form_revision_pointers` | deterministic ordered tuple |
| `detail_sha256` | canonical hash |

Each `ProductFormPointer` contains `assessment_form_id`, `assessment_form_revision_id`, positive
`ordinal`, and `form_revision_sha256`. Ordinals are unique in one Product Revision.

## 3. Assessment Form

`AssessmentForm` is a stable form/session identity within one Product logical identity.

| Field | Contract |
| --- | --- |
| `assessment_form_id` | `form_<32 lowercase hex>` |
| `deliverable_id` | owning Product logical ID |
| `form_key` | stable key unique within Product, such as `01` or `practice-a` |
| `current_revision_id` | mutable convenience pointer only |
| `lifecycle_state` | `ACTIVE`, `RETIRED` |

`AssessmentFormRevision` is immutable:

| Field | Contract |
| --- | --- |
| `assessment_form_revision_id` | `formrev_<32 lowercase hex>` |
| `assessment_form_id`, `revision_number`, `previous_revision_id` | revision chain |
| `deliverable_revision_id` | exact Product Revision owner for this edition/variant |
| `ordinal`, `display_label` | positive order and user-facing label |
| `form_variant_key`, `region_key` | optional reviewed disambiguators |
| `source_occurrence_links` | deterministic typed links, possibly empty |
| `assessment_assembly_revision_id` | exact released Assembly Revision |
| `revision_state` | `DRAFT`, `RELEASED`, `SUPERSEDED`, `WITHDRAWN` |
| `revision_sha256` | canonical hash |
| `created_at`, `created_by` | UTC timestamp and actor ID |

A `SourceOccurrenceLink` contains an exact Assessment Occurrence Revision pointer and relation
`REPRODUCES`, `ADAPTS`, or `REFERENCES`. It does not make the EOM Form and external occurrence the
same identity. `REPRODUCES` additionally requires reviewed rights allowing reproduction.

An immutable Product Revision pins exact Form Revisions. Advancing any Form current pointer does
not change a historical Product Revision.

## 4. Assessment Assembly

`AssessmentAssembly` is a stable grouping identity within one Form logical identity. It permits an
authoring sequence of immutable candidate revisions without mutating a released manifest.

| Field | Contract |
| --- | --- |
| `assessment_assembly_id` | `assembly_<32 lowercase hex>` |
| `assessment_form_id` | owning Form logical ID |
| `current_revision_id` | mutable convenience pointer only |

`AssessmentAssemblyRevision` is an immutable typed manifest:

| Field | Contract |
| --- | --- |
| `schema_version` | `assessment-assembly-manifest/1.0` |
| `assessment_assembly_revision_id` | `assemblyrev_<32 lowercase hex>` |
| `assessment_assembly_id`, `revision_number`, `previous_revision_id` | revision chain |
| `assessment_form_id` | exact logical owner |
| `blueprint_revision_pointer` | optional exact approved blueprint pointer |
| `placements` | non-empty deterministic tuple of frozen ItemPlacement values |
| `total_points_milli` | exact sum of placement points |
| `revision_state` | `DRAFT`, `VALIDATED`, `RELEASED`, `SUPERSEDED`, `WITHDRAWN` |
| `manifest_sha256` | canonical hash |
| `created_at`, `created_by` | UTC timestamp and actor ID |

Each `ItemPlacement` contains:

| Field | Contract |
| --- | --- |
| `placement_id` | `placement_<32 lowercase hex>` |
| `section_key`, `section_ordinal` | controlled key and positive order |
| `position` | positive position unique within section |
| `display_number` | bounded display label; never ordering identity |
| `item_id`, `item_revision_id`, `item_manifest_sha256` | complete immutable Item pointer |
| `points_milli` | non-negative integer, avoiding floating-point values |
| `usage_role` | `PRIMARY`, `PRACTICE`, `REVIEW`, `EXAMPLE`, or `OTHER_REVIEWED` |
| `source_usage_plan_id` | optional exact Usage Plan pointer |

The tuple must already be sorted by `(section_ordinal, position, placement_id)`. Duplicate
`placement_id`, `(section_key, position)`, or source Usage Plan pointers are rejected. The manifest
hash uses EOM `canonical_json_bytes` over the full model with `manifest_sha256` omitted. Floats are
forbidden.

An Item pointer resolves only to an `APPROVED` or historically `SUPERSEDED` Item Revision owned by
the stated Item and matching the manifest hash. A current Item pointer is never consulted.

Reordering, replacing, rescoring, moving, or changing the role of an Item creates a new Assembly
Revision. Releasing that assembly creates a new Form Revision and, when product composition
changes, a new Product Revision. Historical placements never move.

## 5. Publication

`Publication` is the stable identity for one rendered distribution line of one Form. It is not an
Artifact and not a Usage Record.

| Field | Contract |
| --- | --- |
| `publication_id` | `publication_<32 lowercase hex>` |
| `assessment_form_id` | owning Form logical ID |
| `publication_key` | stable key unique within Form |
| `current_revision_id` | mutable convenience pointer only |
| `lifecycle_state` | `ACTIVE`, `RETIRED` |

`PublicationRevision` is immutable:

| Field | Contract |
| --- | --- |
| `schema_version` | `publication-revision/1.0` |
| `publication_revision_id` | `publicationrev_<32 lowercase hex>` |
| `publication_id`, `revision_number`, `previous_revision_id` | revision chain |
| `deliverable_revision_id` | exact Product Revision |
| `assessment_form_revision_id` | exact Form Revision |
| `assessment_assembly_revision_id`, `assembly_manifest_sha256` | exact Assembly Revision |
| `template_revision_pointer` | exact approved template revision |
| `layout_profile_revision_pointer` | exact reviewed layout/profile revision |
| `output_artifacts` | non-empty deterministic tuple of Artifact Revision pointers |
| `revision_state` | `DRAFT`, `VALIDATED`, `RELEASED`, `WITHDRAWN` |
| `published_at` | UTC timestamp, required only for `RELEASED`/`WITHDRAWN` |
| `publication_sha256` | canonical hash |
| `created_at`, `created_by` | UTC timestamp and actor ID |

Each output pointer includes artifact logical/revision IDs, SHA-256, schema, media type, safe
member path, filename, and output role (`PRIMARY`, `ANSWER_KEY`, `ACCESSIBLE`, or `SUPPLEMENT`).
The primary output role is unique. Rendered bytes are never stored in the row.

Product, Form, and Assembly ownership must form one exact chain. A Publication cannot combine a
Form from one Product Revision with an Assembly belonging to another Form. Template, layout, Item,
and output pointers are validated before release.

## 6. Usage Record V1

The mutable `UsagePlan` remains intent. `UsageRecord` remains append-only evidence of actual use.
V0 records remain valid without invented pointers.

V1 extends a record with:

| Field | Contract |
| --- | --- |
| `contract_version` | `usage-record/1.0` |
| `usage_record_id` | existing `usagerecord_<32 lowercase hex>` |
| `item_id`, `item_revision_id` | exact Item pointer |
| `deliverable_id`, `deliverable_revision_id` | exact Product pointer |
| `assessment_form_id`, `assessment_form_revision_id` | exact Form pointer |
| `assessment_assembly_revision_id`, `placement_id` | exact canonical placement |
| `publication_revision_id` | exact released Publication |
| `section_key`, `section_ordinal`, `position`, `points_milli`, `usage_role` | immutable placement snapshot |
| `source_usage_plan_id` | optional unique source plan |
| `source_kind`, `source_key`, `source_hash` | idempotent fulfillment identity |
| `recorded_at`, `recorded_by` | UTC timestamp and actor ID |

The placement snapshot is deliberate denormalization for audit and indexed reads, not a second
authority. At fulfillment it must equal the referenced Assembly placement byte-for-byte for the
shared fields. The Assembly manifest owns composition; the Usage Record owns the fact that this
placement was actually published. Triggers reject every Usage Record update/delete.

Releasing a Publication atomically inserts exactly one V1 Usage Record per Assembly placement, or
verifies an idempotent existing set. Uniqueness is enforced by `(publication_revision_id,
placement_id)` and `(publication_revision_id, section_key, position)`. Replaying the same source
key/hash returns the same records; the same key with a different hash fails closed.

Existing V0 fulfillment remains available only for V0 Products. It cannot fabricate Form,
Assembly, or Publication pointers. A future migration may report V0 rows as `LEGACY_V0`; it may not
silently upgrade them.

## 7. Distribution Event

Distribution is separate from composition and publication. `DistributionEvent` is append-only
aggregate evidence only:

| Field | Contract |
| --- | --- |
| `schema_version` | `distribution-event/1.0` |
| `distribution_event_id` | `distribution_<32 lowercase hex>` |
| `publication_revision_id` | exact released Publication Revision |
| `event_kind` | `RELEASED_TO_CHANNEL`, `DELIVERED_AGGREGATE`, `RECALLED`, `CORRECTED` |
| `channel_key` | reviewed channel taxonomy key |
| `audience_segment_revision_id` | optional opaque protected aggregate-segment pointer |
| `aggregate_count` | optional non-negative count permitted by policy |
| `access_policy_revision_id` | exact aggregate-access policy |
| `source_evidence` | exact Artifact member pointer or trusted system-event pointer |
| `corrects_event_id` | required only for `CORRECTED`, otherwise null |
| `occurred_at`, `recorded_at`, `recorded_by` | UTC evidence timestamps |
| `event_sha256` | canonical hash |

No event stores learner names, account IDs, answers, scores, attempts, or a list of recipients. A
small-cohort policy may suppress `aggregate_count` or the entire graph projection. Corrections are
compensating events; prior events are never updated or deleted.

## 8. Legacy mapping proposal

The Phase 11 importer will use a schema-valid proposal, never direct spreadsheet-to-ledger writes.
Each proposed row contains:

- Content Intake batch/file and source Artifact Revision pointers with SHA-256;
- sheet key, stable source row identity, and normalized row hash;
- mapping-contract revision ID and hash;
- resolved Product/Product Revision, Form/Form Revision, Item/Item Revision pointers;
- proposed section, position, points, usage role, publication date, and source-plan pointer;
- `RESOLVED`, `UNRESOLVED`, `CONFLICT`, or `REJECTED` state;
- reason codes, candidate pointers, reviewer decision, and reconciliation group.

Only `RESOLVED` and human-approved rows can create canonical Assembly/Publication/Usage records.
An omitted or unknown Item Revision never resolves to `Item.current_revision_id`. Duplicate source
row identity/hash is idempotent; duplicate placement or changed hash is a conflict. Original
workbooks remain immutable Artifact Revisions.

## 9. Access patterns, structures, and indexes

Dominant operations are exact key lookup, ordered iteration, reverse Item usage, edition/form
lookup, immutable history replay, and concurrent idempotent fulfillment.

- unique B-tree: Product key; `(deliverable_id, revision_number)`;
- unique B-tree: `(deliverable_id, form_key)` and `(assessment_form_id, revision_number)`;
- unique B-tree: `(assessment_assembly_id, revision_number)`;
- unique B-tree: `(assembly_revision_id, section_key, position)` and placement ID;
- B-tree: placement `item_revision_id` for reverse lookup;
- unique B-tree: `(publication_id, revision_number)` and primary output role;
- unique B-tree: `(publication_revision_id, placement_id)` for Usage fulfillment;
- B-tree: Usage by exact Item Revision, Product/Form/Publication revision, and recorded time;
- B-tree: Distribution by Publication Revision, channel, and occurred time;
- unique source keys/hashes for idempotent import and fulfillment;
- graph adjacency is derived and snapshot-scoped; it is never used to validate ledger authority.

Product/Form/Assembly retrieval is `O(log n + k)` with deterministic ordered iteration. Reverse
usage is `O(log n + k)`. Publication fulfillment is `O(p log n)` for `p` bounded placements inside
one transaction; batch pointer validation avoids N+1 queries. Initial expected scale is thousands
of products/forms, hundreds of thousands of placements, and millions of immutable Usage Records.

PostgreSQL adjacency and B-tree indexes are sufficient. A cache, graph database, or search engine
does not own ordering or usage history and requires measured evidence before introduction.

## 10. Transactions and concurrency

Assembly creation validates Item pointers in one batched read, checks ordering/uniqueness and score
totals, computes the canonical hash, and atomically inserts the revision and placements. Concurrent
revision numbers are serialized by logical-row locking plus a unique constraint.

Publication release locks the Publication logical row, validates the entire Product/Form/Assembly
chain and outputs, inserts the immutable Publication Revision, creates/verifies all Usage Records,
appends events, and advances current pointers in one transaction. Rendering and Codex execution
occur outside this transaction and return only immutable Artifact pointers.

Failure before commit publishes no partial Usage history. Retry uses a scoped idempotency key and
canonical request hash. Same key/same hash returns the prior result; same key/different hash is a
stable conflict. Withdrawals and corrections create new revisions/events and never rewrite history.

## 11. Dependency direction

JSON Schema and frozen value contracts belong to `catalog_contracts`. Item Registry supplies Item
revision lifecycle values. Catalog application services own use cases and transactions. SQLAlchemy,
Artifact storage, HWPX/rendering, spreadsheet parsing, and graph publication are adapters.

CLI/API/GUI construct typed commands and render results; they do not calculate placement rules.
Workers may propose blueprints or mapping rows only through the Orchestrator. They do not create
Product/Form/Assembly/Publication/Usage rows and do not write NAS.

## 12. Required Phase 6 scenarios

1. “00모의고사” Product Revision contains ordered Form Revisions 1 through 12.
2. Item A's exact revision is form 1, section `main`, position 12; Item B's exact revision is form
   5, position 7.
3. The same exact Item Revision appears in multiple publications and yields distinct Usage Records.
4. Different revisions of one logical Item used in different editions remain distinguishable.
5. Reordering or replacing an Item creates new Assembly/Form/Product revisions; historical Q3
   results remain unchanged.
6. Withdrawing/correcting an Item or Publication preserves prior placement/Usage evidence and adds
   an explicit new lifecycle record.
7. A Distribution Event proves only aggregate delivery and contains no learner-level data.
8. An ambiguous legacy workbook row remains quarantined and creates no placement, Usage Record, or
   graph edge.
9. Duplicate positions, dangling/stale pointers, hash mismatch, mixed Product/Form chains, and
   graph/ledger disagreement fail closed.
10. Existing V0 Deliverable and Usage rows remain readable without fabricated V1 pointers.

## 13. Simpler alternatives rejected

- Treating each form as an unrelated Product loses edition/product grouping.
- Encoding form and position in free-text Usage fields cannot provide immutable identity.
- Making graph edges canonical loses transactional ordering and idempotency.
- Copying Item payloads into manifests or Usage rows duplicates canonical content.
- Mutating one Assembly after reorder destroys publication history.
- Treating Publication as the output Artifact loses the release identity and its input chain.
- Mixing Distribution or student activity into Usage rows crosses privacy and retention boundaries.
- Resolving legacy rows to current Item revisions silently creates false history.

## 14. Phase boundary

This document resolves Phase 6 Product/Form/Assembly/Publication/Usage/Distribution ownership,
field, compatibility, and transaction decisions. Implementation must proceed with additive JSON
Schema 2020-12 resources and frozen models before any migration or behavior. It does not authorize
a production migration, legacy import, graph publication, HWPX build, or live Codex invocation.
