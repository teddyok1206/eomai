# ADR 0112: Past-exam-grounded local image quality benchmark

Status: accepted for implementation

Date: 2026-09-25 UTC

## Responsibility and boundary

EOM needs a repeatable way to compare the current fixed local SSD-1B prompt policy with bounded
successor candidates against the visual language observed in the accepted past-exam corpus.  This
benchmark is development evidence, not an item-production workflow and not a replacement for the
image worker.  It never changes an accepted analysis, Item Revision, Graph snapshot, model
revision, Content Pack, or production prompt policy.

The image worker continues to decide what a requested illustration must depict.  Catalog continues
to own the production route and deterministic SVG overlay.  The benchmark runner may invoke only
the installed fixed local image-provider unit with typed requests.  It must not invoke an external
model API, write to NAS, or register generated experiments as approved Item assets.  Benchmark PNGs
are bounded temporary materializations; only their hashes, metrics, exact prompts, receipts, and
the aggregate decision may be retained in the development report.  A future durable benchmark
Artifact must be committed by an orchestrator-owned application use case before any PNG is placed
in NAS.

## Canonical sources and observed population

The canonical references are the immutable accepted legacy item extraction results reachable from
the active `integrated-science-textbooks` Graph snapshot.  At the decision date the exact
occurrence-backed target contains 520 Item Revisions, 505 items with at least one visual pattern,
and 537 `AssessmentVisualPatternObservation` records.  The visual population is dominated by
COMPOSITE (171), DIAGRAM (146), TABLE (72), and FLOW (44).  Rendering modes are VECTOR_LIKE (302),
RASTER (162), MIXED (50), and TEXT_ONLY (23).  GRAYSCALE or MONOCHROME accounts for 535 of the 537
patterns.

Those observations are evidence about assessment style, not direct generation instructions.  An
exact source image member and optional normalized bounding box are pinned for each benchmark sample.
The benchmark must not compare against an implicit latest Graph or a filesystem path.

## Logical entities, revisions, and pointers

`local-image-quality-evaluation-plan/1.0` is one immutable plan identified by `imageeval_*` and its
canonical SHA-256.  It pins:

- the Graph revision, snapshot hash, manifest hash, and sorted 520-target set hash;
- the complete installed local provider binding and model revision;
- a stable ordered prompt-variant set;
- an ordered stratified sample set;
- for every sample, the Item Revision, accepted extraction-result Artifact member, exact visual
  observation, exact page-image Artifact member, page number, and optional normalized box;
- every positive/negative prompt, prompt hashes, and a common seed shared by variants of that
  sample.

`local-image-quality-evaluation-result/1.0` binds every output to the plan hash, the original typed
generation request and receipt, automated measurements, and an optional bounded manual rubric.
Logical Artifact ID, Artifact Revision ID, member path, schema/media identity, and member content
hash remain separate.  A path is never accepted as identity.

## Sampling and routing decision

The first bounded run uses 12 stratified GPU-eligible patterns and three prompt variants (36 local
generations).  It emphasizes PHOTOGRAPH, RASTER/MIXED COMPOSITE, and raster-like natural or organic
scenes.  Exact graphs, maps, axes, particle models, apparatus geometry, labels, equations, arrows,
scales, and panel labels remain deterministic SVG/HWPX responsibilities and are assessed as routing
controls rather than sent to the diffusion model.

The variants isolate one factor at a time:

1. `CURRENT_KO`: the deployed compact Korean subject policy;
2. `ENGLISH_SUBJECT`: the same style prefix and negative prompt with a bounded English subject;
3. `ASSESSMENT_STYLE_EN`: a compact English scientific-assessment illustration style plus the same
   semantic subject and deterministic-label exclusion.

All variants for one sample use the same seed, model, sampler, dimensions, and inference settings.
Pixel similarity to the original is not a success criterion: EOM must not reproduce copyrighted
source artwork.  The source crop supplies aggregate visual-style references only.

## Access patterns and data structures

The dominant corpus operations are indexed joins by pinned revision/acceptance IDs, membership and
deduplication by immutable identity, ordered stratified sampling, and one-pass metric aggregation.
The plan uses tuples for ordered immutable output and sets/maps for uniqueness and lookup.
Selection and validation are O(P + S*V) time and O(P + S*V) space, where P is 537 observed patterns,
S is initially 12, and V is initially 3.  No persistent table or index is added: the accepted
corpus, Artifact tables, and Graph revision are already indexed canonical sources.

Automated metrics are intentionally simple and reproducible with Pillow/NumPy plus bounded local
OCR: grayscale fraction, near-white background fraction, dark-ink fraction, edge fraction, ink
bounding-box coverage, and unexpected glyph count.  Manual review scores semantic fidelity,
assessment style, unwanted text, extra objects, and cropping.  These are complementary; a high
pixel metric cannot waive a semantic or scientific failure.

## Transaction, concurrency, retry, and cleanup

The benchmark does not participate in Catalog Artifact transactions.  Each provider request has an
immutable request hash and unique workspace identity.  Same-plan replay must use the same request
bytes; a conflicting request fails closed.  The fixed provider systemd unit and its existing GPU
lease serialize GPU ownership.  A failed request remains failed evidence and is not overwritten by
a new seed.  Bounded retry, if explicitly requested, reuses the exact request identity.

Temporary output directories are mode 0700 with regular, single-link files.  Reads use no-follow,
bounded size, before/after identity checks, exact hashes, and decoded-pixel bounds.  After the user
has reviewed selected contact sheets, cleanup removes only the exact benchmark temporary root; it
does not touch provider, corpus, Artifact, or accepted-output storage.

## Dependency direction

The schemas and frozen models live in `image_contracts`.  The operator CLI validates a plan and
calls a small benchmark application service.  The application service constructs existing
`LocalImageGenerationRequest` values and invokes the fixed provider adapter.  Filesystem, systemd,
OCR, and image decoding remain infrastructure adapters.  Contracts never import those adapters,
and no production worker or Catalog rule imports benchmark code.

## Failure and acceptance rules

Missing/stale pointers, schema/media/hash mismatch, changed Graph/model binding, duplicate samples,
variant drift, seed mismatch, tokenizer truncation, provider failure, unsafe image bytes, unexpected
text, or incomplete sample-by-variant coverage fail explicitly.  The run may be recorded PARTIAL,
but it cannot select a production policy.  A successor prompt policy is proposed only when its
stratified manual results and automated policy checks beat the current policy without weakening
deterministic SVG ownership.  Production activation still requires a successor contract/Pack and a
separate item canary.

## First-run result and production decision

The bounded run completed all 36 generations on 2026-09-25 UTC with the pinned SSD-1B binding.
Every output passed request/receipt/hash/dimension validation.  The exact temporary result is
`imageeval_683d8a10fc0147422140a53b3e6e2483`; its typed result self-hash is
`sha256:fbbb7abfe48608ce3a5f2af49a1f7dc638c5709253e0104fc25242e489c7158a`.

Visual inspection found a consistent language effect.  `CURRENT_KO` frequently ignored the
scientific subject and produced unrelated photographic people or landscapes.  `ENGLISH_SUBJECT`
recovered the requested object or scene in all representative rows but remained too photographic.
`ASSESSMENT_STYLE_EN` most consistently produced clean monochrome exam-style line art, white space,
and a centered readable subject.  It is not authoritative for labels or geometry and did not make
every diagram scientifically exact; those elements remain deterministic SVG responsibilities.

Therefore Content Pack 1.20 requires the image worker to provide a bounded English local-model
subject for a HYBRID drawing while preserving the complete Korean scene and scientific constraints
elsewhere in the typed drawing.  Catalog prompt policy 1.5 adds the benchmarked assessment-line-art
prefix and fixed negative requirements.  The existing Korean policy 1.4 remains a replay-compatible
fallback for predecessor Pack results; policy selection and revision are included in request
identity.  No source prompt, accepted Item, Graph record, or predecessor Pack is mutated.

## Simpler alternative and why it is insufficient

Looking at a few hand-picked PNGs without exact source/model/prompt pins cannot distinguish model,
seed, language, or style-policy effects and cannot be reproduced.  Sending all 537 patterns to the
GPU would waste capacity and regress exact scientific geometry.  Direct pixel matching risks source
imitation and rewards the wrong objective.  The bounded typed A/B/C benchmark is the smallest design
that isolates prompt effects while preserving EOM's deterministic-label and immutable-pointer
boundaries.
