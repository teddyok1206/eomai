# Generated Item Print Projection Boundary V1

## Responsibility and boundary

The authoring worker produces schema-valid structured item blocks. The image worker produces a
validated drawing specification. The review worker validates that those two immutable revisions are
sufficient for the later item-management and HWPX projections; it does not require a raw
HwpQuestionEditor Markdown file at the authoring boundary.

## Canonical source and pointers

The canonical source remains the pinned content-pack release plus the immutable authoring and image
artifact revisions and their SHA-256 hashes. HWPX and editor Markdown are downstream materializations,
not competing item identities. A workflow pins those revisions and never resolves an implicit latest
artifact.

## Access pattern and representation

The common operation is keyed block lookup followed by ordered block projection, so the item remains a
frozen typed model with stable block identifiers. A deterministic vector manifest is used for
print-critical force-time graphs because its labels, coordinates, scale, and monochrome strokes can be
validated without interpreting color.

## Transactions, failure, and idempotency

Workers remain read-only. The orchestrator validates and commits each artifact once. Missing units,
lost axis multipliers, or a drawing that depends on color fail review before human approval. Content
Pack 1.11 does not add a subject-specific quantity-plausibility heuristic or force one concrete equation
spelling around the pinned editorial prompt. Replaying the same workflow revision reuses its pinned
inputs and does not rewrite released content-pack bytes.

## Simpler alternative

Requiring raw editor Markdown from the authoring worker duplicates the structured item and confuses an
intermediate representation with a deliverable. Allowing colored line graphs and hoping print conversion
preserves meaning is also insufficient for print-critical assessment material. The selected boundary
keeps one structured canonical item and a deterministic downstream HWPX materialization.
