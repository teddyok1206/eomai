# Item Revision HWPX profile resolution V1

## Responsibility and boundary

The HWPX application service selects the closed renderer that matches the canonical `ITEM_CONTENT`
component of one current approved Item Revision. The Studio asks for `item-revision-auto`; neither
the browser nor the GUI gateway reimplements Catalog component rules. Existing explicit renderer
requests remain supported.

## Canonical source and revision model

The Item Revision and its pinned ordinal-zero `ITEM_CONTENT` artifact revision are authoritative.
`eom.assessment.item-content/1.0` resolves to `eom-template`; `item-content/2.0` resolves to the
content-team HwpQuestionEditor profile. The resulting build stores the resolved renderer, immutable
source artifact IDs, revision ID, source hash, and renderer release snapshot. Paths are not identity.

## Access pattern and data structure

Resolution is one bounded ordered scan of the revision component tuple followed by a keyed schema
lookup. Item revisions contain a small component set, so this is O(n) time and O(1) auxiliary space;
no persistent cache or new index is warranted. Zero or multiple eligible canonical components fail
as an ambiguous source.

## Transaction, concurrency, and failure

Resolution happens before the existing idempotent build record transaction. The resolved profile is
part of the request hash and the build record; the runner never resolves a floating current
revision. Existing operator/idempotency uniqueness and build state transitions are unchanged.
Unsupported, stale, non-current, unapproved, or mixed component pointers fail before rendering.

## Dependency direction

The API schema exposes the selection mode. The HWPX application service owns resolution because it
already owns Item Revision eligibility and renderer ports. The GUI sends a presentation request and
does not inspect storage or implement renderer business rules.

## Retry and alternatives

Retry reuses the stored resolved renderer and pinned artifact revision. Making the GUI fetch
components and choose a renderer was rejected because it duplicates application policy across a
presentation adapter and creates a read/create race. Defaulting every item to one renderer was
rejected because V1 and V2 item contracts are intentionally distinct.
