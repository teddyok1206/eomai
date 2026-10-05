# ADR 0199: Reviewed exterior annotations in native TRAIN targets

## Status

Proposed next implementation boundary, 2026-10-05 UTC. No schema released,
worker behavior, dependency, installed package, source pixels or production
activation changed by this decision note. Native target1.2 remains no-mask.

## Evidence and scope

Twelve previously unprepared source regions were rendered and individually
opened through the existing TRAIN-only source pipeline. Nine are deferred;
several contain usable objects but adjacent text/leader fragments. Three targets
were prepared and reviewed with explicit captions and observed expression classes.
The inherited contour label often describes a toned/annotated scene, not a clean
training image. More raw counts alone will not fix that admission mismatch.

The house and monkey are candidates for removing **separate exterior text**,
without changing depicted geometry, shades or composition. Doctor/patient's
central label/leader, the jellyfish's internal callout, and missing glove/hand
parts are not automatically recoverable through this policy. Exact scientific
axes/leaders/structures remain Python/SVG/native responsibilities.

## Required design

1. Boundary: extend the current reviewed CPU target-preparation path only.
   Define JSON Schema 2020-12 before matching frozen Pydantic models and worker
   behavior. Do not weaken native1.2 or create a second executor/plugin framework.
2. Canonical source: existing approved original PDF and immutable native crop.
   White annotation patches belong only to a separately reviewed target derivative;
   original source bytes, source caption and source publication remain untouched.
3. Identity: explicit successor command/result and target revision pin source
   Artifact/revision/hash, reviewed recipe and caption. Changing a mask/subject
   statement is a new revision, never a new independent drawing or silent replay.
4. Resolution: keep existing metadata-first source/review/authorization admission,
   TRAIN-only split, exact schema/media/member/lifecycle/permission/hash checks,
   and PREPARE-only bounded PNG reads. No latest fallback or reserved pixels.
5. Access patterns: bounded ordered decisions, set uniqueness/coverage, map lookup
   by source ID, immutable manifests. At most32 sources and a small closed bound
   on exterior rectangles per source; no searchable registry/cache/database needed.
6. Structures/complexity: reuse existing normalized rectangles and rational fit;
   validate pixel bounds/overlap once. O(number of source pixels + output pixels)
   time and one decoded source/output at a time. No full-corpus raster scan.
7. Ownership: contract/domain owns recipe/provenance rules; trainer's image
   adapter owns pixel checks and exact white replacement. Orchestrator alone stages,
   dispatches and commits. Worker sees local files only, no model/GPU/NAS/DB/auth.
8. Concurrency/transaction: existing unique workspace, result receipt and publisher
   idempotency boundary. Terminal replay validates exact outputs without transforms
   or writes. Unknown execution/failed output is not permission to redispatch.
9. Pixel policy: reviewer declares exterior-annotation rectangles and protected
   subject regions. Rectangles must not overlap protected geometry; require a
   fixed white clearance ring inside the source frame so connected leaders/contours
   are rejected. Replace only declared pixels with white, then reuse grayscale,
   aspect-preserving native fit/margin. No OCR guessing, thresholding, inpainting,
   generative repair, silhouette reconstruction or global contrast change.
10. Failure: stable invalid-frame/protected-contact/nonwhite-clearance/hash errors.
    Do not enlarge masks, relax tolerances, switch policy or turn FAIL into success.
    Human inspection remains essential: geometry/clearance checks cannot prove that
    an enclosed disconnected scientific mark is merely annotation. Reinspect every
    target before explicit admission; count/symbol/composition captions must match.
11. Simpler alternative: keep all annotated sources deferred and search for new
    clean material. Preserve that option for central overlaps/missing parts. It is
    insufficient for isolated exterior labels on otherwise complete reviewed
    shapes. Existing768x512 masked targets do not preserve native geometry/identity;
    duplicating their executor or silently lifting the1.2 no-mask rule is not acceptable.

## Compatibility and acceptance

Inventory all consumers before implementation, especially native LoRA target-batch
schema constraints. New target revisions are unusable for training until their exact
successor schema is supported by an explicit training-command successor; released
command1.0 must not resolve a new result under the old1.2 descriptor. Preserve old
JSON Schema bytes, typed models, numerical recipes and historical replay fixtures.
Prefer one public protocol resolver at the existing owner over repeated adapter
version checks. No runtime installation or experiment on partially supported contracts.

Required tests: JSON Schema/Pydantic/canonical equivalence, immutable predecessors,
target/run/caption identities, exterior mask bounds/overlap/protected contact,
nonwhite clearance, disconnected-symbol limitation, pixel equality outside declared
mask before existing fit, three native canvases, deterministic bytes/manifest,
metadata-before-media, missing/stale/hash/permission/split rejection, duplicate
source/target references, receipt failures, no-write terminal replay, installed
source-free role, wheel contents/RECORD and training admission compatibility.

First execution, after complete source/installed gates, should be one bounded
CPU preparation of the already reviewed house/monkey candidates, with no extra PDF
render, generation, GPU or training. Inspect originals and derivatives side by side;
if a safe exterior recipe cannot be declared, defer honestly and find other sources.
Full training cohort, independent blind review and Item/HWPX canary remain separate
open gates. This note does not promote either rejected twelve-target adapter.
