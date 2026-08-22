# Assessment Item Content V1

## Responsibility and boundary

`assessment-item-content/1.0` is the canonical, presentation-neutral content snapshot for one
Item Revision. It belongs to the catalog contract layer. A protocol version that supports
structured authoring (or a reviewed import adapter) produces it, the Item Registry pins its
artifact revision, and delivery adapters consume it. HWPX, textbooks, mock exams, PDF, web preview,
and future exports are consumers; none of them owns the item content. The current workflow v1.1
placeholder result is not silently promoted into this contract: it remains template-ineligible
until a future protocol revision or import boundary emits a schema-valid `ITEM_CONTENT` artifact
and all pinned media artifacts.

The first HWPX adapter supports only the subset represented by the approved
`placeholder-item-v1` question template. Unsupported content fails with a stable compatibility
error. The adapter never silently falls back to a Kordoc report or mutates the canonical item.

## Canonical source and revision model

```text
Item -> immutable Item Revision -> ITEM_CONTENT component pointer
                              -> image/artifact revision pointers

Delivery -> ordered pinned Item Revision pointers + presentation profile revision
         -> generated Artifact Revision
```

The Item Revision is the reproducible snapshot. The content JSON is a small immutable value
artifact. Images and other binary media remain independent artifacts and are referenced by typed,
pinned pointers. A media pointer includes the exact safe POSIX artifact member and that member's
SHA-256 because an accepted Content Intake may package several files under one Artifact Revision.
The member is an immutable location inside the artifact manifest, not a storage path. A NAS or host
filesystem path is never part of this contract.

## Data model

The content snapshot contains ordered semantic blocks, an interaction, a solution, and scoring
information. Blocks have stable IDs so a delivery adapter can select or reorder them without
copying their payload. Equations declare their notation. Images carry an immutable artifact
revision and expected hash. Tables are rectangular values, not renderer-specific XML.

The schema deliberately does not contain a question number, page number, book chapter position,
HWPX marker, template file path, or storage URI. Those are delivery concerns.

The first supported projection is `eom-question-template-v1`. A textbook or mock-exam adapter may
select a different ordered subset or visual profile from the same pinned content, but it must not
rewrite, relabel, or resolve a newer Item Revision implicitly. A new adapter is activated only when
its profile revision and compatibility rules are explicit and tested.

## Access patterns and structures

- Exact Item Revision lookup: indexed primary/foreign keys already used by the registry.
- Component lookup: `(item_revision_id, component_type, ordinal)` unique index; the canonical
  content component uses `ITEM_CONTENT, 0`.
- Block lookup during projection: a map keyed by unique `block_id`, O(n) construction and O(1)
  lookup. Ordered output uses the source tuple order.
- Choice and statement membership: unique IDs validated as sets in the frozen Pydantic model.
- Textbook/mock-exam assembly: ordered immutable Item Revision pointer tuples plus a pinned
  publication/profile revision; no content copies. Placement metadata such as section, sequence,
  question number, points display, and answer-book inclusion belongs to that delivery manifest,
  not to the canonical item.

Expected item payloads are small (normally tens of blocks, bounded by 100). Binary size is not
stored in PostgreSQL or embedded in the JSON.

## Transaction and concurrency boundary

The workflow commits the validated content artifact before registration. Registry registration
resolves and validates the exact artifact revision and hash, then atomically creates the immutable
Item Revision and its component pointers. Idempotent replay returns the existing revision only when
the registration identity is unchanged. Delivery builds pin the Item Revision, content artifact
revision, template revision, and hashes in their request identity.

The reviewed import adapter follows the same boundary. An ADMIN pins a current APPROVED Item
Revision, submits schema-valid content, and explicitly records a review reason. The Catalog
application manager commits one canonical content Artifact Revision and asks the Registry to create
a new immutable APPROVED Item Revision while preserving the base revision's Content Pack, workflow,
metadata, provenance, and every non-content component pointer. Registry registration atomically
supersedes the base revision. HTTP idempotency protects request replay; content-hash and registration
identities deduplicate the artifact and revision boundaries.

The loopback Application API never receives NAS or Catalog staging access. It validates the public
request, authenticates the reviewer, and sends the bounded small-value content snapshot over the
private `catalog-application/1.0` Unix-socket protocol. The orchestrator-owned Catalog Application
Manager is the only side of this boundary that materializes staging bytes and calls the canonical
artifact commit adapter. The socket authenticates the fixed API UID with `SO_PEERCRED`; both request
and response are validated against packaged JSON Schema 2020-12 resources and frozen Pydantic
models. Binary media never crosses this command boundary and remains a pinned Artifact Revision
member.

The dominant operations are exact Item/Revision lookup, component-position replacement, and media
member lookup. DB access uses primary and unique indexes. Components are collected once into a
keyed map, O(n), instead of repeatedly scanned. Artifact member lookup is one bounded manifest scan
followed by a hash check of the exact immutable member. No binary bytes enter DB rows. If artifact
commit succeeds but concurrent Registry registration loses, the immutable unreferenced artifact
remains valid evidence and a later idempotent request can reuse it.

This path is deliberately an administrative reviewed boundary, not a worker shortcut. A future
workflow protocol v2 can emit the identical content contract and use the same Registry service.
Textbook and mock-exam assembly pin ordered Item Revision tuples plus their own delivery profile
revision, so they reuse canonical content without copying it.

## Dependency direction

```text
workflow/catalog application -> assessment content contract
Application API adapter       -> Catalog application protocol
Catalog application manager   -> artifact/Registry adapters
HWPX application adapter      -> assessment content contract + HWPX contract
assessment content contract   -> no infrastructure
```

The canonical contract does not import HWPX, SQLAlchemy, NAS, HTTP, or worker code. The HWPX
projection is an adapter and may depend on both stable contracts.

## Failure, retry, and idempotency

Missing, stale, unapproved, wrong-media, wrong-schema, or hash-mismatched pointers fail explicitly.
Duplicate block/choice/statement IDs fail validation. An HWPX template incompatibility fails before
builder submission. A delivery build is idempotent on the full pinned input and presentation
profile identity; it never resolves an implicit latest revision during replay.

## Simpler alternative considered

Using Markdown as the canonical item was rejected because choices, correct responses, semantic
tables, media pointers, and solution structure become heuristic parser output. Storing the legacy
HWPX item JSON as canonical was rejected because its fixed 2x3 table, one image, one equation, and
three-statement layout would couple every future textbook and mock-exam feature to one template.
Kordoc `FormatProfile` was also rejected as the template boundary: it reproduces table styling but
not the approved question document's full structure.
