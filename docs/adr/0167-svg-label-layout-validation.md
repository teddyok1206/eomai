# ADR 0167: deterministic SVG label-layout validation

## Status

Accepted for implementation on 2026-10-01.

## Context

The safe SVG contract proves that worker-authored overlays contain only bounded elements,
attributes, fixed fonts, and required labels.  It intentionally does not prove spatial
legibility.  A valid science diagram therefore placed the `P` label over the conductor attached
to an electrode.  The label was present, used an approved font, rendered deterministically, and
passed registration, but was not publication quality.

Released Content Pack `generated-knowledge-item@1.20.13`, its worker results, registered Item
Revisions, and generated image Artifacts are immutable.  A repair must not reinterpret those
historical results or edit a registered SVG/PNG in place.

## Decision

### Responsibility and boundary

`eom_image_contracts` owns a pure, versioned label-layout policy and its JSON Schema 2020-12 /
Pydantic receipt.  The policy accepts a sanitized SVG overlay and an injected deterministic raster
function.  It has no filesystem, subprocess, database, NAS, or orchestration dependency.

The orchestrator adapter invokes the already installed fixed `rsvg-convert` runtime after ordinary
role-result validation and before Artifact commit.  Enforcement is enabled only when the resolved
execution plan pins the exact bundle hash of the successor Content Pack.  A passing receipt is
stored in the image job's `ARTIFACT_COMMITTED` event.  A stable layout error fails the pre-commit
attempt as `WORKER_RESULT_INVALID`; the existing bounded step-attempt policy may schedule a new
image attempt.  Workers never call each other or write NAS.

Catalog independently repeats the same policy immediately before deterministic SVG/PNG
materialization for the successor Pack.  This defense does not trust the worker or orchestrator
receipt and never substitutes another Revision or silently moves a label.

### Canonical source and pointer model

The worker image result remains canonical.  Its exact drawing JSON produces a drawing SHA-256 and
contains the SVG overlay.  The validation receipt is a small derived attestation bound to the
canonical overlay hash, ordered label bounds, fixed renderer/font identities, policy revision, and
self-hash.  It is not a second image source and contains no image bytes.

Historical Pack `1.20.13` remains on the prior policy.  Successor Pack `1.20.14` is the first
identity that requires `eom-svg-label-layout/1.0`.  Enforcement is selected by its immutable bundle
hash in the resolved plan, not by mutable "latest" lookup.

The frozen `1.20.14` source-tree hash is
`sha256:41d86ae2dc5460b3e5988049bdf7c23362256175368360faf75a6845ded2f7cb` and its bundle hash is
`sha256:72150b33965cbd70465cd13738df41eef66d9a9ed51d7a16b84897227c53a391`.

### Access patterns and data structures

The dominant operation is a bounded scan of one 800x500 raster per SVG plus one raster per text
element.  Text elements are contract-bounded.  Pixel masks are fixed-size byte arrays, label bounds
are immutable tuples, and label membership/cardinality uses maps and sets.  For `L` labels the
policy is `O(L * width * height)` time and `O(width * height + L)` working space; both canvas and `L`
are bounded independently of corpus size.  No database scan, cache, table, index, or migration is
introduced.

The geometry raster is converted into an edge mask, so a label may remain readable inside a
uniform light filled component while conductors, outlines, and high-contrast geometry cannot cross
or crowd it.  Separately rendered text alpha produces exact fixed-font bounds.  Bounds must stay
inside the canvas, preserve minimum clearance from geometry and other labels, and contain exactly
one occurrence of every required label.

### Transaction, concurrency, retry, and idempotency

Validation occurs before the image result enters `COMMITTING`, so a rejected attempt creates no
Artifact record and writes no NAS Artifact.  Receipt construction is a pure function of immutable
input and fixed runtime identities; replay produces the same self-hash.  The normal workflow
attempt number, unique job identity, claim/lease fencing, and maximum step-attempt limit remain the
only retry authority.

Catalog validates again before its own Artifact commit.  A failure is explicit and leaves the
previous Item/Revision/Artifact untouched.  Automatic coordinate repair is forbidden because it
could change a scientifically meaningful relationship.

### Dependency direction

The image-contract package contains only values, schema loading, canonical hashing, PNG decoding,
and the renderer-callback policy.  Orchestrator and Catalog infrastructure supply the fixed raster
adapter.  Neither contracts nor domain models import either service.  The image prompt is changed
only in the additive Pack successor; the two authoritative content-team guidance files are not
modified.

## Simpler alternatives rejected

1. **Prompt wording only.** This reduces incidence but cannot prove the rendered output.
2. **Mutate `1.20.13`.** This changes released behavior and invalidates reproducible history.
3. **Automatically move colliding labels.** A generic renderer cannot know whether a label's side,
   anchor, or distance is scientifically meaningful.
4. **Validate only in Catalog registration.** The invalid image result would already be committed
   and the normal pre-commit retry boundary could not help.
5. **Add Pillow to core.** The fixed PNG subset is small and deterministic; a bounded decoder keeps
   the optional image-library dependency out of the orchestrator runtime.

## Required verification

- Schema and Pydantic accept the same receipt and reject wrong hashes, order, bounds, or identities.
- The observed `P`/conductor SVG fails before Artifact commit with a stable layout code.
- A corrected `P`/`Q` placement passes and yields a deterministic receipt.
- Legitimate labels inside uniform light fills, axis labels, Korean labels, and multiple labels do
  not produce false positives.
- canvas overflow, required-label cardinality, label-label overlap, and renderer drift fail closed.
- old Pack/schema bytes are unchanged and old Pack `1.20.13` does not acquire the new semantic rule.
- Catalog repeats the policy before materializing successor-Pack images.
- focused tests, Ruff, strict mypy, wheel/package-resource checks, and an opt-in bounded live item
  smoke pass before activation.
