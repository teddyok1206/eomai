# Item Origin, Organization, and Assessment Occurrence V1 Design

Status: Phase 6 normative design; schema and persistence are not implemented by this document.

Last reviewed: 2026-08-23 UTC

Related decisions: [ADR 0038](../adr/0038-item-origin-and-assessment-occurrence.md),
[Education Knowledge and Item GraphRAG](EDUCATION_KNOWLEDGE_ITEM_GRAPHRAG.md), and
[Graph V0 acceptance queries](EDUCATION_GRAPH_V0_ACCEPTANCE_QUERIES.md).

## 1. Responsibility and boundary

Catalog owns reviewed Organization identities, Assessment Occurrences, and the immutable origin
profile attached to an exact Item Revision. Content Intake owns untrusted observations and source
files. Item Registry owns Item and Item Revision lifecycle. A future graph snapshot projects
validated pointers from these records; it never becomes their source of truth.

This design does not change `item_type_key`. That field continues to identify the content or
interaction type. Origin, authorship method, institutional identity, examination occurrence,
derivation, and rights are independent dimensions.

The model deliberately does not store source documents, Item JSON, or binary media in PostgreSQL.
Those bytes remain canonical Artifact Revisions. PostgreSQL stores identities, immutable revision
pointers, controlled values, hashes, lifecycle, and small reviewed value objects.

## 2. Canonical identities and revisions

### 2.1 Organization

`Organization` is a logical identity.

| Field | Contract |
| --- | --- |
| `organization_id` | `org_<32 lowercase hex>` |
| `organization_key` | immutable reviewed key, globally unique |
| `current_revision_id` | mutable convenience pointer; never used for historical replay |
| `lifecycle_state` | `ACTIVE`, `RETIRED` |
| `created_at`, `created_by` | UTC timestamp and actor ID |

`OrganizationRevision` is immutable after review.

| Field | Contract |
| --- | --- |
| `organization_revision_id` | `orgrev_<32 lowercase hex>` |
| `organization_id`, `revision_number` | exact logical owner and positive monotonic number |
| `previous_revision_id` | exact predecessor or null only for revision 1 |
| `revision_state` | `REVIEWED`, `SUPERSEDED`, `RETIRED` |
| `organization_class` | controlled value below |
| `display_name`, `locale` | reviewed display value and BCP-47 locale |
| `jurisdiction` | frozen value below |
| `aliases` | deterministic tuple of reviewed alias values |
| `effective_from`, `effective_to` | optional ISO dates; closed interval when both exist |
| `source_evidence` | one or more exact source Artifact member pointers |
| `rights_policy` | exact immutable Rights Policy pointer |
| `revision_sha256` | hash of canonical JSON excluding this field |
| `created_at`, `created_by` | UTC timestamp and actor ID |

Initial `organization_class` values are:

- `EOM_INTERNAL`;
- `NATIONAL_ASSESSMENT_AGENCY`;
- `EDUCATION_AUTHORITY`;
- `SCHOOL`;
- `UNIVERSITY`;
- `PUBLISHER`;
- `PRIVATE_EDUCATION_PROVIDER`;
- `OTHER_REVIEWED`.

Adding a new meaning requires a new contract version. `OTHER_REVIEWED` requires a bounded
`class_detail` value; it is not a place for unreviewed intake text.

`jurisdiction` contains `country_code` (ISO 3166-1 alpha-2), `level` (`NATIONAL`, `PROVINCE`,
`METROPOLITAN`, `CITY`, `COUNTY`, `DISTRICT`, `INSTITUTION`, or `OTHER`), and optional reviewed
`jurisdiction_code`. Display names do not serve as jurisdiction identity.

Each alias contains `alias_kind` (`OFFICIAL`, `ABBREVIATION`, `FORMER`, `LEGACY_SOURCE`), `locale`,
`display_value`, and `normalized_value`. The normalized value is produced by a versioned
normalization policy and is unique only inside one Organization Revision. It is intentionally not
globally unique: the same abbreviation can refer to different organizations. Resolution uses
normalized alias, jurisdiction, effective date, and source evidence. Zero or multiple candidates
remain unresolved and require review.

### 2.2 Assessment Occurrence

`AssessmentOccurrence` represents one stable real-world examination event or event family member.
It is separate from an EOM Product or Form.

| Field | Contract |
| --- | --- |
| `assessment_occurrence_id` | `occurrence_<32 lowercase hex>` |
| `occurrence_key` | immutable reviewed key, globally unique |
| `current_revision_id` | mutable convenience pointer only |
| `lifecycle_state` | `ACTIVE`, `RETIRED` |

`AssessmentOccurrenceRevision` is immutable and contains:

| Field | Contract |
| --- | --- |
| `assessment_occurrence_revision_id` | `occurrev_<32 lowercase hex>` |
| `assessment_occurrence_id`, `revision_number`, `previous_revision_id` | revision chain |
| `revision_state` | `REVIEWED`, `SUPERSEDED`, `WITHDRAWN` |
| `issuing_organization_revision_id` | exact reviewed Organization Revision |
| `occurrence_kind` | controlled value below |
| `exam_family_key` | controlled taxonomy key, not display text |
| `administration_year` | four-digit year |
| `administration_date` | exact date when established, otherwise null |
| `session_key` | reviewed session/round key or null |
| `subject_key` | reviewed subject key |
| `form_key`, `region_key` | optional reviewed disambiguators |
| `display_label` | user-facing label, never identity |
| `source_evidence` | one or more exact source Artifact member pointers |
| `rights_policy` | exact immutable Rights Policy pointer |
| `revision_sha256` | canonical hash |
| `created_at`, `created_by` | UTC timestamp and actor ID |

Initial `occurrence_kind` values are `NATIONAL_ENTRANCE`, `NATIONAL_ACHIEVEMENT`,
`EDUCATION_AUTHORITY_EXAM`, `SCHOOL_EXAM`, `INSTITUTIONAL_EXAM`, and `OTHER_REVIEWED`.

The uniqueness key is the reviewed tuple of issuing organization logical identity, exam family,
administration year/date, session, subject, form, and region. A corrected label or date creates a
new revision of the same occurrence. Evidence that identifies a distinct session or form creates a
different logical occurrence. A withdrawn occurrence remains resolvable for historical queries.

## 3. Shared immutable pointers

The V1 schemas define, rather than infer, these pointer shapes:

```text
ArtifactMemberPointer
  artifact_id
  artifact_revision_id
  sha256
  schema_ref
  media_type
  logical_name
  normalized member_path

RightsPolicyPointer
  rights_policy_id
  rights_policy_revision_id
  rights_policy_sha256

ItemRevisionPointer
  item_id
  item_revision_id
  item_manifest_sha256

SourceRevisionPointer
  source_kind
  logical_id
  revision_id
  manifest_sha256
```

Every resolver validates logical/revision ownership, expected schema and media type, lifecycle,
caller permission, hash, and immutability. It never resolves an omitted revision through a current
pointer. Rights Policy records are a separate policy-domain responsibility; this contract pins
their identity, revision, and hash without copying policy content.

## 4. ItemOriginProfile V1

`ItemOriginProfile` is a frozen one-to-one value owned by one exact Item Revision. It does not have
an independently mutable current pointer.

Required fields are:

| Field | Contract |
| --- | --- |
| `schema_version` | `item-origin-profile/1.0` |
| `item_origin_profile_id` | `originprofile_<32 lowercase hex>` |
| `item_id`, `item_revision_id`, `item_manifest_sha256` | complete Item Revision pointer |
| `source_domain` | controlled value below |
| `creation_method` | controlled value below |
| `source_organization_revision_id` | optional exact Organization Revision |
| `assessment_occurrence_revision_ids` | sorted unique tuple, possibly empty |
| `derivation_pointers` | sorted unique typed source pointers |
| `rights_policy` | required exact Rights Policy pointer |
| `provenance_pointers` | non-empty tuple of exact existing evidence pointers |
| `profile_sha256` | canonical hash |
| `created_at`, `created_by` | UTC timestamp and actor ID |

`source_domain` is one of `INTERNAL_EOM`, `EXTERNAL_INSTITUTION`, `EXTERNAL_INDIVIDUAL`, or
`LEGACY_UNKNOWN`. `creation_method` is one of `HUMAN_AUTHORED`, `AI_ASSISTED`, `AI_GENERATED`,
`IMPORTED`, `ADAPTED`, or `UNKNOWN`.

Derivation pointers are discriminated values of type `ITEM_REVISION`, `DOCUMENT_REVISION`, or
`SOURCE_REVISION`. Each contains a complete immutable target pointer and a relation
`DERIVED_FROM`, `TRANSLATED_FROM`, `DIGITIZED_FROM`, or `RECONSTRUCTED_FROM`. They do not copy the
target payload.

Provenance pointers are discriminated values for existing `WORKFLOW`, `CONTENT_INTAKE`,
`ITEM_PROVENANCE`, and `MANUAL_REVIEW` records. AI-generated and AI-assisted profiles pin the exact
workflow and approved result evidence. Imported profiles pin Content Intake evidence. Manual
profiles pin a reviewed manual-source or workflow record. The profile composes those records and
does not replace them.

### 4.1 Cross-field rules

1. `INTERNAL_EOM` requires the reviewed EOM Organization Revision.
2. `EXTERNAL_INSTITUTION` requires a non-EOM Organization Revision.
3. `EXTERNAL_INDIVIDUAL` may omit an Organization but requires reviewed manual/source evidence.
4. `LEGACY_UNKNOWN` permits only `IMPORTED` or `UNKNOWN`, requires unresolved intake evidence, and
   receives a rights policy that forbids general retrieval until reviewed.
5. `AI_ASSISTED` and `AI_GENERATED` require an exact workflow provenance pointer.
6. `IMPORTED` requires an exact Content Intake provenance pointer.
7. `ADAPTED` requires at least one derivation pointer.
8. An institutional past-exam classification requires at least one reviewed Assessment Occurrence
   whose issuing Organization matches the profile's source Organization.
9. Occurrence observations remain independently valid when a source item is later reproduced by an
   EOM Product. Reproduction does not change the source domain.
10. Duplicate occurrence, provenance, or derivation targets are rejected.
11. Every profile requires a Rights Policy pointer, including EOM-owned and unknown material.
12. Correcting any profile field creates a new Item Revision and profile. Existing profiles remain
    immutable and continue to support historical queries.

“Past examination” is therefore a verified query predicate over an occurrence pointer, not a
boolean or filename/tag heuristic.

## 5. Intake and resolution states

Untrusted organization names and occurrence labels first enter a mapping proposal with state
`PROPOSED`. Each observation then becomes `RESOLVED`, `UNRESOLVED`, `CONFLICT`, or `REJECTED`.

- `RESOLVED` pins one exact reviewed revision and the normalization-policy revision.
- `UNRESOLVED` retains source evidence and candidate-free reason codes.
- `CONFLICT` retains multiple candidate revision IDs and requires a human decision.
- `REJECTED` records why the observation cannot create a canonical fact.

No state other than `RESOLVED` can create an Organization/Occurrence graph edge or satisfy an
institutional-origin filter. Replaying the same source revision, mapping-contract revision, stable
row identity, and normalized hash is idempotent. A different hash under the same key fails with a
stable conflict; it is not treated as a retry.

## 6. Access patterns, data structures, and indexes

Dominant operations are key lookup, revision traversal, alias candidate lookup, origin filtering,
reverse occurrence lookup, and sparse derivation traversal.

- unique B-tree: logical keys and `(logical_id, revision_number)`;
- B-tree: `(normalized_alias, country_code, jurisdiction_level)` for candidate lookup;
- B-tree: occurrence family/year/subject and issuing Organization Revision;
- unique one-to-one: `item_revision_id` on ItemOriginProfile;
- B-tree: source domain, creation method, Organization Revision, Occurrence Revision;
- adjacency rows: derivation edges indexed from and to exact revision pointers;
- partial current-pointer indexes are convenience only and prohibited in historical resolution.

Expected exact lookup and filtering cost is `O(log n + k)`. Alias resolution is bounded by indexed
candidates. No repeated full-list scan, graph database, or free-text fuzzy resolver is accepted
without measured evidence and a review queue.

Initial scale assumptions are thousands of organizations/occurrences, hundreds of thousands of
Item Origin profiles, and a small bounded number of provenance/derivation pointers per profile.
PostgreSQL rows store only metadata and pointers; source bytes remain Artifact Revisions.

## 7. Transaction, concurrency, and lifecycle

Creating a reviewed revision atomically inserts the immutable revision, its aliases/evidence
pointers, an append-only event, and advances the logical current pointer using optimistic lock
versioning. Hash/idempotency conflicts roll back the entire transaction.

Creating an ItemOriginProfile occurs in the same Catalog transaction that commits its owner Item
Revision, or in an additive revision transaction that creates a new Item Revision. A profile is
never attached later by mutating a historical revision.

Logical retirement prevents new references but does not break historical resolution. Revision
rows and profiles are append-only. Database triggers reject update/delete after review; corrections
create new revisions. Concurrent creation is serialized by logical key and idempotency-key unique
constraints.

## 8. Dependency direction

Canonical JSON Schema and frozen Pydantic values belong to `catalog_contracts`. Item Registry may
depend on these contracts or their small public value interfaces. Catalog application services own
resolution and transactions. SQLAlchemy, filesystem, Content Intake, and Artifact access remain
in infrastructure adapters. Graph publication consumes only approved typed pointers.

Workers may propose origin observations but cannot create Organization, Occurrence, profile, graph,
or Artifact records and cannot write NAS.

## 9. Required acceptance scenarios

1. A human-authored new item has `EXTERNAL_INDIVIDUAL` or reviewed `INTERNAL_EOM`,
   `HUMAN_AUTHORED`, no occurrence, manual/workflow evidence, and a rights pointer.
2. An institutional past item has `EXTERNAL_INSTITUTION`, exact Organization and Occurrence
   revisions, immutable source evidence, and a rights pointer.
3. EOM human, AI-assisted, and AI-generated items share `INTERNAL_EOM` but preserve distinct
   creation methods and exact workflow/manual provenance.
4. An EOM adaptation has `INTERNAL_EOM`, `ADAPTED`, and exact source Item or Document Revision
   lineage; it does not inherit the source occurrence as its own publication event.
5. A legacy organization string with zero or multiple candidates remains unresolved and cannot
   satisfy a verified-origin query.
6. A new Organization/Occurrence revision leaves prior Item profiles and graph snapshots unchanged.
7. Stale, missing, unapproved, rights-mismatched, schema/media-mismatched, and hash-mismatched
   pointers fail explicitly.
8. Changing `item_type_key` does not alter origin, and changing origin does not alter interaction
   type.

## 10. Simpler alternatives rejected

- One `item_kind` enum cannot represent independent source, method, occurrence, derivation, and
  rights dimensions.
- Free-text organization tags do not provide revision identity or safe alias resolution.
- A `past_exam` boolean cannot identify the event, evidence, rights, or correction revision.
- Copying provenance JSON into a graph or Item metadata creates conflicting authorities.
- Resolving an omitted revision to current makes historical results non-reproducible.
- Automatically fuzzy-matching legacy strings turns ambiguity into false canonical facts.

## 11. Phase boundary

This document resolves the Phase 6 origin/organization/occurrence ownership and field decisions.
Implementation must begin with additive JSON Schema 2020-12 resources and byte-parity tests. It
does not authorize a production migration, Content Intake import, graph publication, worker run, or
live Codex invocation.
