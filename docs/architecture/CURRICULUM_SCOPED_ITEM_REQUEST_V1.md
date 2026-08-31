# Curriculum-scoped Item Request V1

Status: implementation design for the additive Scientific Studio request contract.

Decision date: 2026-08-27 UTC

Authorities:

- `EOM_INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_V1.md` fixes the reviewed EOM labels, codes, and
  sibling order for six product large units and 35 product middle units.
- A published Curriculum Framework Revision and Knowledge Graph Snapshot remain separate runtime
  authorities. This design does not pretend that the editorial outline has already been published
  into either one.

The initial GUI therefore exposes the outline for item classification but reports
`RESERVED_CANDIDATES_NOT_PUBLICATION_PROOF` and keeps Graph grounding disabled. Enabling grounding
requires a later reviewed publication that contains every advertised stable root and its curriculum
closure, plus a capability-contract change; the browser never infers readiness from labels.

## 1. Responsibility and boundary

Scientific Studio owns presentation and draft editing. Application API exposes the authenticated
read-only outline projection and resolves a submitted editorial key into the internal immutable
scope. The workflow request contract owns the resolved authoring brief. Catalog owns resolution of
that scope's graph root against the current published `integrated-science-textbooks` snapshot.
The BFF obtains that corpus identity from the fresh Application API capability projection rather
than maintaining a second operational constant. Workers receive only
the validated brief and pinned Evidence Bundle material; they do not resolve Graph or filesystem
paths themselves.

The product hierarchy shown to an editor is:

```text
대단원 -> 중단원 -> 소단원
```

The current reviewed data contains 대단원 and 중단원 only. 소단원 is a disabled, empty extension
slot. It must not be equated with an achievement standard or populated from labels heuristically.

Product and Graph level names are intentionally kept distinct:

```text
product 권       -> Graph MAJOR
product 대단원   -> Graph MIDDLE
product 중단원   -> Graph MINOR
product 소단원   -> not defined yet
```

## 2. Canonical source and revision model

The source-controlled V1 outline is the canonical selection catalog for the editor. A packaged,
schema-validated copy is an application resource, not a database identity. Any label, parent, or
order change requires a successor catalog revision; V1 bytes remain immutable.

The browser and BFF carry only a selected editorial unit key. Application API resolves it into a
small frozen curriculum-scope value containing the outline revision and hash, selected level,
canonical breadcrumb, and reserved Graph stable key. The stable key is a mapping candidate, not
proof that a live Graph node exists. Grounded execution still fails closed unless Catalog resolves
that exact key in a published snapshot and validates its framework/unit pointer.

## 3. Request and pointer contract

The new brief is additive `knowledge-item-brief-v2`; V1 remains readable without reinterpretation.
V2 contains:

- the existing structured item constraints;
- normalized, reviewed natural-language authoring guidance and its SHA-256;
- the original request SHA-256;
- an optional selected editorial unit key at the external Application API boundary;
- an immutable resolved curriculum scope, including the deepest selected unit's Graph stable key,
  at the internal workflow boundary.

Selection and Graph grounding are separate. A curriculum selection may classify a general-knowledge
item without Graph access. If Graph grounding is enabled, a selection is mandatory and only its
deepest stable key becomes `curriculum_root_key`; ancestors are display/provenance values, not three
independent retrieval seeds.

The authoring prompt treats the natural-language value as delimited editorial data. It cannot
override the output schema, sandbox, evidence, or security contract. Its stored hash must match the
normalized text.

## 4. Primary access patterns and data structures

Frequent operations are exact code lookup, parent lookup, ordered child listing, and deepest-unit
selection. The packaged catalog is small (6 + 35 entries), but it is loaded once into immutable
tuples and indexed maps:

- `unit_by_key`: O(1) exact lookup;
- `children_by_parent`: O(1) parent lookup plus O(k) stable sibling iteration;
- `ancestors_by_key`: bounded O(depth), currently at most two product levels;
- duplicate code and sibling order validation: O(n) with sets/maps.

No large content or graph projection is stored in a draft. Graph traversal continues to use the
existing indexed closure table after Catalog resolves the stable key to pinned framework/unit IDs.

## 5. Transaction, concurrency, and idempotency

Request Drafts remain session-local and mutable. Submission materializes one immutable V2 brief.
The draft specification hash covers all structured fields, the reviewed guidance, and selected
editorial key; changing any of them changes the submission key/fingerprint. Application API and
workflow business-fingerprint checks remain the durable idempotency boundary.

Existing workflows pin V1 briefs and their Content Pack release. A new immutable Content Pack
release consumes V2. Activation changes only the pointer used by future workflows; historical
releases and running workflows are unchanged.

`generated-knowledge-item@1.2.0` is the creation boundary for V2 briefs. Once it is activated, new
starts through the current Studio use V2; historical V1 workflows remain readable and pinned to
their original release. A client that must continue creating V1 workflows needs an explicit
versioned pack-selection contract rather than an implicit fallback to the prior active release.

## 6. Failure and retry behavior

- unknown code, mismatched breadcrumb, duplicate sibling order, or invented 소단원: request invalid;
- Graph grounding without a curriculum selection: request invalid;
- selected stable key absent from the published snapshot: fail before workflow/worker creation with
  the existing curriculum-scope error;
- Graph publication capability absent: the Studio control remains disabled and sends no retrieval
  intent;
- changed draft with a reused idempotency key: conflict, never silent replay;
- no automatic workflow or worker retry is introduced.

## 7. Dependency direction

The versioned curriculum value and loader live in contract/domain code. Application API imports
that contract and exposes a bounded read-only projection. Scientific Studio validates and projects
the untrusted HTTP response through its existing gateway, without acquiring Catalog, SQLAlchemy, or
database dependencies. Application API accepts the V2 DTO and resolves the key; workflow stores the
frozen brief; Catalog prepares prompt and metadata and resolves Graph through its existing adapter.
No domain package imports GUI, SQLAlchemy, filesystem, or HTTP code.

## 8. Scale and persistence

V1 is 41 selectable nodes and fits comfortably in memory. Expected future size is at most a few
thousand curriculum nodes per catalog revision. PostgreSQL continues to store only workflow JSON,
metadata, graph identities, revisions, relations, and hashes. Textbook PDFs, Markdown, images, and
Evidence Bundle bytes remain artifact-backed and are not copied into request rows.

## 9. Security and provenance

Natural-language guidance is bounded, control-character checked, normalized, hashed, and never sent
to Slack. It is not a shell command or raw worker prompt. The GUI never accepts a graph revision,
filesystem path, model, slot, or policy override from this form. Catalog alone pins the current
Graph Snapshot, access policy, and Evidence Bundle revisions.

## 10. Simpler alternatives rejected

Three free-text inputs were rejected because labels/codes can disagree and Graph keys can be
invented. Encoding the hierarchy only in the `topic` string was rejected because it loses identity,
parentage, and reproducibility. Editing brief V1 or Content Pack 1.1.0 in place was rejected because
it would reinterpret historical workflows. Treating product 소단원 as Graph
`ACHIEVEMENT_STANDARD` was rejected because no reviewed mapping exists.

## 11. Verification

Tests must cover canonical catalog cardinality/order, middle-first parent fill, the future generic
small-to-middle-to-large resolver, incompatible descendant clearing, unknown/mismatched values,
natural-language hash closure, V1 replay preservation, V2 prompt/metadata materialization, deepest
Graph root projection, Graph miss before worker creation, schema mirror equality, OpenAPI, BFF
security, and release isolation.
