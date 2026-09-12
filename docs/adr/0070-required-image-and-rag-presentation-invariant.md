# ADR 0070: Required image and RAG presentation invariant

## Status

Accepted.

## Context and responsibility

The public one-Item request already carries the authoritative `image_mode` value, and the
knowledge-backed execution plan already pins the retrieval requirement and Evidence Bundle.  A
released authoring result nevertheless could contain no `IMAGE` visual: the Content Pack described
image creation as optional, the image decision counted only the submitted visuals, and review ran
after the zero-image branch had already skipped the image worker.  Requiring an image profile proved
capacity, not authored presentation.

The application boundary owns request normalization, the orchestrator owns pre-commit result
validation, the workflow runner owns state transitions, and the Content Pack owns worker
instructions.  Existing Item Revisions and Content Pack releases remain immutable.

## Canonical source and identities

`WorkflowRequest.image_mode` remains the single source of truth for standalone generation.  A
mock-exam slot remains the source of truth for its exact material profile, because mock-exam
workflows intentionally carry image capacity even for `TEXT`, `DATA`, `TABLE`, and `INQUIRY` slots.
For a Graph-grounded standalone request, `required_item_elements` must include `image`; the immutable
resolved execution plan and Evidence Bundle remain the reproducibility pins.

No large content or image bytes are added to PostgreSQL.  The existing chain remains:

```text
Workflow request -> pinned execution plan -> authoring Artifact Revision
                 -> image Artifact Revision -> approved Item Revision components
```

## Decision

1. Publish a successor Content Pack.  It renders `request.image_mode` explicitly for authoring and
   review.  `required` demands at least one ordered `IMAGE` slot, an upper stem that introduces the
   figure, and a genuine material/data region.  Quantitative setup and observations belong in
   `DATA`; `CONDITION` is limited to assumptions and constraints.  The image worker continues to
   derive what to draw from the exact typed draft and the two unchanged team-lead guidance files.
2. Standalone Graph-grounded request normalization adds `image` and `paragraph` to the existing
   `choice` retrieval filter.  Lookup remains an indexed set-membership/grouping query in
   `O(candidate elements)` and does not expose batch identity.
3. Before an authoring Artifact is committed, the orchestrator rejects an image-required evidence
   plan without an `IMAGE` slot.  It also requires a positive `PAST_EXAM` `REFERENCE_PATTERN`
   citation to bind the authored upper stem, every `DATA` block's content leaf, and every image
   slot's typed `kind` leaf.  Citation and manifest lookup use dictionaries and sets, so validation
   is `O(entries + citations + paths)`.
4. The workflow image decision independently refuses to take the zero-image branch for a
   standalone content-team request whose `image_mode` is `required`.  Mock-exam slot behavior is
   unchanged and continues to use the slot material-profile validator.
5. Review instructions independently reject missing required images, missing figure-introducing
   upper-stem/data structure, or misuse of `CONDITION` as the whole stimulus.

The existing JSON Schema and Pydantic wire shapes already express `image_mode`, typed visuals,
Evidence citations, and immutable plan pointers.  This change tightens their cross-document
invariant; it does not mutate or silently reinterpret an existing schema document.

## Failure, retry, and concurrency

Violations fail before canonical authoring storage with a stable evidence-validation code, or at
the independently fenced image decision if an older/bypassed artifact reaches it.  Retrying the
same idempotency key revalidates the same immutable input and cannot create a second Artifact.
No worker-to-worker or worker-to-NAS path is introduced.

## Alternatives

Prompt-only guidance was rejected because a worker can still omit the slot and the state machine
would skip image generation.  Making every mock-exam workflow produce an image was rejected because
it would contradict pinned non-image material profiles.  Adding a duplicate `image_required` field
to the brief was rejected because it would create two mutable sources of truth.
