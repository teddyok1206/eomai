# Content-team conditional image pipeline V1

## Responsibility and system boundary

The authoring role remains responsible for deciding whether a single item needs zero, one, or two
IMAGE visual slots under the complete content-team prompt. A declarative workflow decision reads
only the validated, pinned authoring-result Artifact Revision. When IMAGE slots exist, the existing
image role produces an ordered drawing plan; Catalog alone renders and commits PNG artifacts to NAS.
Registration binds those immutable PNG revisions to the Item Revision, and the content-team HWPX
adapter materializes them into the program-defined left/right slots. Workers neither communicate
directly nor write PostgreSQL or NAS.

## Canonical source and revision model

The canonical editorial source remains `AssessmentItemContentV2` plus its lossless Markdown member.
An IMAGE marker is layout intent, not image bytes. Each rendered picture is one canonical
`generated-item-stimulus` Artifact Revision. The Item Revision contains the ITEM_CONTENT component
and zero to two ordered IMAGE component pointers. HWPX is a derived deliverable and never becomes the
canonical question or image source.

```text
authoring result revision -> ordered IMAGE slots
image result revision     -> ordered drawing specifications
                           -> generated PNG artifact revisions
item revision             -> ITEM_CONTENT + ordered IMAGE pointers
                           -> derived HWPX artifact revision
```

Logical artifact ID, artifact revision ID, Item Revision ID, and SHA-256 remain distinct.

## Required pointers and resolution checks

The workflow decision pins the authoring step, result schema, artifact revision, and content hash.
Image materialization requires exact slot ordinals/labels, image-result identity, 800x500 media
dimensions, schema/media type, approved artifact and revision state, safe member name, and SHA-256.
Registration persists the same values without resolving an implicit latest revision. HWPX input
resolution rejects missing, duplicate, stale, unapproved, mislabeled, wrongly ordered, wrong-media,
wrong-size, or hash-mismatched images.

## Primary access patterns and data structures

Frequent operations are keyed step-result lookup, membership/uniqueness validation, ordered
iteration over at most two visual slots, DAG traversal, and immutable manifest assembly. Step and
component lookup use maps or indexed database predicates; ordinal uniqueness uses sets and the
existing `(item_revision_id, component_type, ordinal)` unique constraint; visuals use immutable
tuples. Workflow dependencies remain an adjacency-map DAG. No repeated list scan is introduced for
unbounded data.

## Scale, complexity, and indexes

Per item, visual work is bounded by two elements, so validation and rendering are O(1) time and
space with respect to platform scale. Item component resolution uses the existing indexed
`item_revision_id` lookup and unique position constraint. Artifact and revision checks use primary
keys. No new table, index, cache, or large PostgreSQL value is required.

## Transaction and concurrency boundary

Each worker result is immutable before workflow advancement. Catalog renders each drawing in a
workflow/result/ordinal-scoped staging directory and commits via the existing idempotent artifact
service. Item registration transactionally records all component pointers. HWPX build claims one
FIFO build row, materializes pinned bytes in a private workspace, and commits only after structural
validation. Concurrent replay resolves the same immutable outputs or fails an idempotency conflict;
it cannot overwrite a canonical artifact.

## Dependency direction and adapter ownership

JSON Schema and frozen value models own the cross-service protocol. The workflow application uses a
Catalog port to inspect a validated authoring result and materialize drawings. Catalog adapters own
PostgreSQL/NAS and deterministic/local image providers. The HWPX manager resolves registry pointers;
the HWPX builder owns ZIP/XML materialization. Domain and contract packages do not import these
infrastructure adapters.

## Failure, retry, and idempotency behavior

Zero IMAGE slots deterministically skip the image role. One or two slots require an exact ordered
image result; count or label drift fails before NAS commit. Rendering or pointer failure fails the
workflow and never registers a partial Item Revision. HWPX image injection fails without publishing
a deliverable if any placeholder, manifest entry, binary, or relationship is ambiguous. Existing
workflow retry limits apply to the image step, while artifact and HWPX commits remain idempotent by
pinned input hashes.

## Content-team prompt preservation

The complete byte-pinned content-team authoring prompt remains unchanged and authoritative for
whether a visual is necessary and for its zero-to-two canonical layout. Its required illustration
prompt prefix is carried only in the typed image request/result path, never inserted into the item
Markdown. For the hybrid local generation route, the provider-facing generation prompt must equal
that complete prefixed illustration prompt; a parallel or summarized prompt fails validation. The
image role continues to read the pinned KICE illustration reference. EOM adds no subject, item-type,
or mandatory visual rule.

## Simpler alternative and why it is insufficient

Always running the legacy one-image workflow would force or waste an image on no-image items, cannot
represent two IMAGE slots, and contradicts the content-team prompt. Leaving text placeholders in
HWPX loses the canonical generated asset. Embedding PNG bytes or paths in item JSON/Markdown would
duplicate payloads and erase revision/hash identity. A parallel renderer would discard the team
program's proven layout. The selected extension keeps one pipeline and adds only typed conditional
dispatch, ordered pointers, and a bounded post-render image materialization step.

## Review and verification

Tests must cover zero/one/two image decisions, invalid or duplicate ordinals, slot-label mismatch,
stale/hash-mismatched pointers, idempotent materialization, registration component ordering,
no-image compatibility, IMAGE/TABLE and TABLE/IMAGE layouts, two-image HWPX insertion, no remaining
placeholder text, deterministic manifests, and the absence of binary payloads in database values.
Live image-provider and usage-consuming workflow tests remain explicit opt-in tests.
