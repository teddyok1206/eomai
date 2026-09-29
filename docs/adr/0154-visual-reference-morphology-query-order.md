# ADR 0154: Visual-reference morphology query ordering

## Status

Accepted for implementation on 2026-09-29 UTC.

## Context and responsibility

The image worker supplies an English subject that combines target morphology with presentation
directions. The orchestrator derives bounded Wikimedia Commons search terms; the isolated acquirer
verifies the returned source and the local provider rejects unsuitable raster morphology. A live
canary produced `large front view ammonite fossil illustration`, which returned a photograph of a
multi-shell fossil mass. The provider correctly rejected it as background-complex, but the noun
phrase ordering made clean morphology references unnecessarily difficult to retrieve.

The query derivation boundary owns presentation-clause removal. Worker output, visual-reference
schemas, acquisition verification, provider quality gates, and failed Workflow history remain
unchanged.

## Decision

- Remove count determiners as before.
- Detect the supported viewpoint phrase from the complete subject, remove it from its original
  position, then append it after the morphology noun phrase.
- Remove only leading presentation-size adjectives `large`, `small`, and `full-size`; they describe
  framing, not subject identity.
- Continue emitting the stable base and `illustration` variants. For the failed case this produces
  `ammonite fossil front view` and `ammonite fossil front view illustration`.
- Keep single-subject title filters and downstream morphology/background gates fail-closed.

## Data, complexity, and failure

The operation is bounded string normalization over at most 180 characters, O(n) time and O(n)
space. No database, schema, Artifact, queue, network policy, or transaction change is required.
Existing search and acquisition identities remain immutable; a fresh Workflow produces a new
query command. If no suitable reference is found, generation still fails rather than substituting
an unrelated image.

## Simpler alternative considered

Weakening `REFERENCE_SIMPLIFICATION_BACKGROUND_COMPLEX` would admit the exact multi-object photo
that the contract is meant to reject. Hard-coding `ammonite` would not generalize to cars, organisms,
or apparatus. Reordering the already-supported viewpoint phrase is the smallest general fix.
