# ADR 0149: Single-subject reference selection, EXIF orientation, and terminal failure

## Status

Accepted for implementation on 2026-09-28 UTC.

## Responsibility and boundary

The visual-reference infrastructure adapter selects and normalizes non-authoritative Wikimedia
morphology references for a generated assessment image.  It does not choose answer-bearing labels,
change the content-team drawing request, or own the final image Artifact.  The Orchestrator remains
the only component that publishes validated reference and generated-image artifacts.

A live one-item canary requested one frontal ammonite.  Discovery admitted an aggregate
`Ammonite Pavement` file ahead of single-specimen files, and several Wikimedia JPEGs reported their
post-EXIF dimensions while Pillow initially exposed their stored pixel dimensions.  The acquirer
therefore rejected a valid oriented raster.  The workflow runner then treated the deterministic
`VISUAL_REFERENCE_IMAGE_INVALID` detail as generic worker unavailability and repeated the entire
image worker five times.

## Canonical source and revision model

The canonical morphology source remains a pinned visual-reference bundle revision containing the
verified Commons page revisions, original-byte hashes, and one normalized PNG member.  Discovery
command/result, intent, acquisition command/result, bundle revision, generated-image revision, and
their SHA-256 values remain separate immutable identities.  Failed canaries and predecessor bundles
are preserved; no existing contract bytes or database rows are rewritten.

## Decision

1. When the validated English subject explicitly requests one object, discovery excludes titles
   with an explicit aggregate-scene marker such as `pavement`, `collage`, `collection`, `group`,
   `multiple`, or `specimens` before the bounded candidate tuple is pinned.  Other candidates keep
   deterministic suitability ranking, official relevance order, and page-ID tie breaking.
2. Raster validation checks encoded format, animation, and encoded pixel bound first.  It then
   applies EXIF orientation and compares the oriented dimensions with the official Commons
   dimensions.  This accepts legitimate orientation metadata without weakening format, size,
   decompression-bomb, host, license, or byte-hash validation.
3. `VISUAL_REFERENCE_IMAGE_INVALID` is a terminal pre-commit detail.  It cannot improve by rerunning
   the same image worker and immutable reference intent, so the workflow must fail once rather than
   consume the full role-attempt budget.

No schema successor is required: candidate cardinality already permits one through five entries,
and normalization/error codes are existing contract values.  This ADR precedes the behavior change.

## Access patterns and data structures

Discovery iterates over at most 20 official search results and sorts at most five admitted
candidates.  A frozen marker tuple and normalized-title membership checks are `O(C*M)` with small
bounded constants; result sorting remains `O(C log C)`.  Normalization is one bounded raster pass,
`O(W*H)` time and transient memory.  No DB table, index, cache, queue, or binary payload is added.

## Transaction, concurrency, retry, and idempotency

Discovery/acquisition remains read-only until the Orchestrator publishes a fully validated bundle.
Workspace output is still exclusive and atomic.  Exact command replay remains byte-stable.
Deterministic invalid-image failure terminates before NAS commit; source-unavailable behavior stays
under the already bounded adapter policy.  Concurrent workflows retain independent command IDs and
the existing artifact idempotency keys.

## Dependency direction and alternatives

Title suitability and EXIF handling stay inside the Wikimedia/image-provider infrastructure
adapter.  Retry classification stays in the workflow runner application boundary.  Contracts do not
import Pillow, HTTP, filesystem, or orchestration code.

Prompt-only avoidance is insufficient because the image worker does not select Commons results.
Accepting metadata dimensions without decoding would weaken the trust boundary.  Rerunning the
worker cannot repair a pinned deterministic raster mismatch.  A new search framework or external
vision API would add unnecessary state and trust surface; the bounded adapter fix is sufficient.
