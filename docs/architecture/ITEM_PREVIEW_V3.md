# Completed Item Preview V3

Status: implementation design
Date: 2026-09-14 (UTC)

## Responsibility and system boundary

Scientific Studio renders one explicitly selected, immutable Item Revision without interpreting NAS
paths or trusting browser-supplied Artifact pointers. Catalog remains the only component that
dereferences canonical content and media. Application API authorizes those reads. The Web BFF maps
the validated domain content into a presentation-only preview contract, and the browser renders that
contract with DOM APIs.

```text
browser
  -> Studio BFF preview JSON / same-origin visual URL
  -> Application API ITEM_READ boundary
  -> private Catalog application socket
  -> approved Item Revision + pinned component Artifact Revision
```

This design adds `item-preview/3.0` and a separate
`catalog-item-component-media-request/response/1.0`. Historical preview V1/V2 and block-addressed
Catalog media contracts remain byte-immutable.

## Canonical source and revision model

The canonical source is the requested approved Item Revision. Its required ordinal-zero
`ITEM_CONTENT` component pins a logical Artifact, immutable Artifact Revision, schema reference,
media type, and SHA-256. Content-team images are separate required `IMAGE` components keyed by their
typed visual ordinal. They pin their own Artifact and Artifact Revision; the Web preview never
creates or stores another image copy.

Supported schema references are classified through one exact lookup table:

- assessment item V1, including its historical URI alias;
- content-team item V2, including its URI alias;
- content-team item V3, including its URI alias.

Unknown schemas produce the stable `UNSUPPORTED_CONTENT_SCHEMA` presentation state. Missing,
duplicated, stale, malformed, or hash-mismatched known pointers are errors, not an asynchronous
"preparing" state.

## Required pointers and resolution checks

Preview construction validates the requested Item ID against the Item response, the requested
Revision ID against the Revision response, the Item/current-revision relation, approved lifecycle,
revision ETag, Workflow ID, Content Pack Release ID, exactly one required canonical content
component, and content schema/profile agreement. It never invents `unknown` provenance.
Content-team visual slots must match the exact ordered set of required `IMAGE` component ordinals.
Catalog media resolution revalidates revision approval, component type and ordinal, component
schema and media type, logical Artifact identity, immutable Artifact Revision identity, approval
state, member path, size, file type, media signature, and SHA-256 before streaming bytes.

The browser receives only a same-origin URL derived from `(item_id, item_revision_id,
visual_ordinal)`. It cannot choose an Artifact ID, revision ID, member path, or expected hash.

## Access patterns and data structures

- Schema classification is O(1) map lookup.
- Components are scanned once and indexed by `(component_type, ordinal)` in a map, O(c) time and
  O(c) bounded space; duplicate positions fail explicitly.
- Canonical blocks and content-team sections preserve ordered tuple iteration, O(b).
- Content-team visuals are bounded at two entries, while general preview blocks remain bounded at
  100 entries.
- Catalog resolves one component through the existing indexed `(item_revision_id)` query plus the
  database uniqueness constraint on `(item_revision_id, component_type, ordinal)`.

At the current scale no new persistent index is necessary. The existing Item-component index and
unique constraint match the lookup and uniqueness operations.

## Projection rules

V1 keeps its existing ordered block projection. V2/V3 preserve the canonical editorial order:

1. upper stem;
2. `<자료>` and `<조건>` blocks;
3. inquiry content, or zero to two table/image visuals in array order;
4. lower question stem and score;
5. optional `ㄱ/ㄴ/ㄷ` statement set;
6. choices, answer, explanation, concept source, and authoring intent.

`TABLE_ONLY` therefore renders a table without manufacturing an image. One image has no panel
label. Two image or two table panels retain their typed `(가)/(나)` labels as editable text. Mixed
table/image layouts preserve the source array order.

## Transaction, concurrency, retry, and idempotency

All preview operations are read-only and open no write transaction. GET requests are repeatable
against the pinned Item Revision. They never resolve an implicit latest Artifact Revision and never
repair a dangling pointer. Media is streamed once in bounded chunks and verified end-to-end. The
browser increments a monotonic request generation for each selection, so a slow response for an
older Item cannot overwrite a newer selection. Starting or failing a lookup clears every structured
edit and HWPX target before presenting the status; stale identifiers are never left actionable.

Preview readiness is synchronous for an approved immutable Item. `PROCESSING` is reserved for a
future contract that carries an actual asynchronous job identity and poll target; V3 deliberately
does not expose a temporal state without such evidence.

## Dependency direction and ownership

Catalog owns storage and pointer validation. Application API owns authorization and HTTP streaming.
The Web BFF owns only schema-family classification and presentation projection. JavaScript owns no
business rule and renders only the BFF contract. No worker, orchestrator, or NAS write path changes.

## Failure behavior

- Unknown canonical schema: HTTP 200 with `UNSUPPORTED` and
  `UNSUPPORTED_CONTENT_SCHEMA` so users receive an accurate capability message.
- Known schema with malformed content or component disagreement: fail closed with a stable upstream
  response error.
- Missing/stale/hash-invalid media: fail closed at Catalog/Application API; no placeholder bytes or
  alternate revision are substituted.
- Authentication and authorization failures retain their existing API behavior.

## Frontend/backend drift prevention

The repository maintains the following closed alignment matrix:

| Boundary | Release-blocking comparison |
| --- | --- |
| Browser request | every literal method/path must match a BFF route; the one reviewed dynamic route is counted exactly |
| BFF upstream request | every method/path must exist in the committed Application API OpenAPI document |
| Application API | regenerated OpenAPI bytes and its pinned SHA-256 must match source routes |
| Preview response | JSON Schema 2020-12 and Pydantic must accept the same representative variants; semantic invariants fail in Pydantic |
| Browser renderer | JSON Schema block discriminators, accepted block set, and implemented render branches must be identical |
| Browser DOM | every literal selector must exist exactly once and the local ES-module dependency graph must close inside static assets |
| Product state | typed backend state-machine literals must be present in the Korean presentation vocabulary |
| Release files | source package, wheel members, wheel RECORD descriptors, and installed package inventory must be the same exact set |

Node parses every shipped JavaScript file as an ES module. Pointer negatives cover missing targets,
cross-resource identities, duplicate component keys, stale revisions, malformed Artifact URIs,
hash mismatches, unsupported schemas, and unverified media bytes. A deployed older commit is reported
as deployment lag; mixed, missing, or unknown files inside one installed release fail installation
verification.

A production-data read-only audit projected all 558 current approved Items without accessing NAS
outside the Catalog boundary: four canonical V1, three content-team V2, 31 content-team V3, and 520
legacy V1 URI-alias Items. This is runtime compatibility evidence, while the compact unit matrix
continues to exercise `NONE`, `TABLE_ONLY`, `IMAGE_ONLY`, `IMAGE_IMAGE`, `IMAGE_TABLE`,
`TABLE_IMAGE`, `TABLE_TABLE`, and inquiry independently.

## Simpler alternatives rejected

Adding V2/V3 strings to the old V1 gate would pass a different data shape into the V1 block parser
and fail with a 502. Embedding PNG bytes in preview JSON would duplicate large data and bypass
streaming. Reading NAS paths in Web would break the Catalog ownership and runtime isolation
boundaries. Making permanent schema absence look like "preparing" would hide a deterministic
capability defect. The additive typed projection and component-media operation are the smallest
changes that preserve existing security and identity invariants.
