# ADR 0173: Institutional science-illustration blind quality loop

Status: accepted for bounded implementation

Date: 2026-10-02 UTC

## Responsibility and boundary

EOM needs a repeatable way to improve generated science illustrations until a reviewer cannot
reliably identify the generated member when it is mixed with approved past-exam artwork.  This is
an evaluation objective for rendering conventions, not permission to reproduce a source drawing.
Exact labels, numerical values, axes, arrows, apparatus geometry and panel labels remain owned by
the deterministic SVG/HWPX path.  The local raster model may supply only the bounded morphology and
unlabelled visual material selected by the image worker.

The quality loop is a development use case.  It does not publish generated benchmark images as Item
components, activate a LoRA adapter, change a production provider binding, or mutate an accepted
past-exam analysis.  External image or language APIs are prohibited.  Only the pinned local model,
approved internal past-exam visual artifacts and existing deterministic renderers are in scope.

## Canonical sources and immutable identity

Every comparison case pins the institutional reference by logical Artifact ID, immutable Artifact
Revision ID, member path, media type, schema reference, member SHA-256 and an optional normalized
crop.  Every generated candidate pins its request, receipt, provider binding, model revision,
prompt-policy revision, seed and output Artifact member.  A filesystem path is only a temporary
materialization and is never identity.

The initial population is stratified across natural objects, manufactured objects, living
organisms, Earth/space scenes and laboratory subjects.  It is also partitioned into explicit
`OBJECT_LINE_ART` and `RASTER_TEXTURE_SCENE` style tracks.  One evaluation plan contains exactly
one track.  The two tracks have materially different tonal, edge and foreground distributions and
must never be pooled into one median.  Deterministic diagrams are retained as route controls; they
are not sent through the raster model merely to increase the sample count.  The accepted 520-item
corpus, three visual-pilot crop sets, the reviewed 24-member object-line-art set, the separately
reviewed 24-member raster/texture/scene set and existing immutable V6 outputs are reused.  Source
images and generated PNGs are not copied into Git or PostgreSQL.

## Blind evaluation protocol

An immutable evaluation plan contains between 12 and 32 comparison cases.  Each case has one
institutional member and one generated candidate in the same style track.  Both sides must depict
the same exact semantic subject identified by a unique `depiction_key`; sharing only a broad family
such as `LIVING_ORGANISM` is insufficient.  The candidate must not reproduce the exact source
artwork.  A canonical SHA-256-derived ordering token assigns opaque labels and presentation order.
The answer key is stored separately from the reviewer form.  The evaluation plan is an internal
orchestrator input and must never be used as the reviewer payload because each case contains
`left_origin`.  A typed review-packet successor contains only content-addressed normalized left and
right PNG members plus the case token and same-depiction metadata.  A separate typed answer-key
artifact contains the token-to-origin mapping.  Both bind the exact evaluation and plan hash.
Presentation tokens are independent CSPRNG 128-bit values.  They are never derived from the case ID
or origin: because there are only two possible origins, a public deterministic hash would let a
reviewer recover the answer by trying both inputs.

The packet builder resolves each pinned source member once, applies the plan's deterministic
presentation policy, and deduplicates normalized bytes by SHA-256 in a keyed map.  Dominant access
patterns are O(1) case/member lookup and stable ordered iteration; construction is O(C*W*H) time and
O(U*W*H) output space for `C` cases and `U` unique normalized images.  It writes only to a local
workspace.  The orchestrator remains the sole owner of separate NAS commits for reviewer packet and
answer key.  Retry with the same plan is byte-identical; any plan or image change produces a new
hash.  Keeping only the plan and relying on UI field hiding is simpler but insufficient because one
serialization mistake would disclose the blind key.
The reviewer records, without seeing origin:

- guessed origin and confidence;
- institutional-style suitability;
- semantic/scientific suitability;
- composition preservation;
- line-weight, detail-density, whitespace and tonal defects;
- whether the image is usable as-is, usable after deterministic overlay, or rejected.

Both members are rendered and measured through
`FOREGROUND_BBOX_FIT_800X500_V1`: pixels darker than 245 define a non-empty foreground box, that
box is proportionally resized (including bounded upscaling) into a 720 x 420 region, and it is
centered on an 800 x 500 white canvas.  The same normalized bytes must drive the future canonical
reviewer presentation and already drive the automated evaluator.  This prevents native crop size
or surrounding whitespace from revealing origin.  Source and generated Artifact members remain
immutable and unchanged.

Automated measurements complement but never replace review.  They include foreground fraction,
edge density, dark/mid-tone fractions, border clutter, small connected-component fraction and
fine-detail fraction.  Metrics are computed in one bounded raster pass plus an adjacency-list/
deque connected-component traversal.  For an 800 x 500 image this is O(W*H) time and O(W*H) worst-
case memory.  Results use keyed maps for case lookup and sets for duplicate member/hash detection,
so plan/result validation is O(C + O).

The primary style target is not a perfect zero-percent identification rate from a tiny sample.  A
candidate is eligible for a production canary only when, on a balanced blinded set, it improves
institutional-style suitability without worsening semantic suitability or composition retention,
has no critical scientific defect, and generated-origin identification is no better than the
predeclared bounded threshold.  The exact threshold and sample size are fixed in the plan before
review.  Activation remains a separate successor-binding decision.

## Successor rendering strategy

Production V6 remains immutable and is the rollback.  Candidate work is additive:

1. retain the image worker's exact bounded English subject and the team-lead/KICE provenance pins;
2. preserve a clean reference's global composition through the existing adaptive simplifier;
3. use a deterministic assessment-line-art postprocessor successor to reduce isolated speckles and
   microtexture while retaining connected subject contours: Gaussian radius `0.85`, median kernel
   `5`, removal of disconnected foreground components of at most `48` pixels, and a final
   `40 x 24` pixel clean border;
4. measure fine-detail and tiny-component ratios explicitly rather than inferring quality from a
   broad edge-density interval;
5. keep text, exact geometry and editorial panel labels outside the diffusion output;
6. use LoRA only when a blinded, subject-stratified comparison beats the base candidate.  Existing
   mixed LoRA evidence does not authorize global activation.

The postprocessor successor must use fixed integer kernels and thresholds recorded in the request.
It may remove only bounded small components and soften microtexture.  It must not invent or delete a
large connected subject part.  Composition retention, foreground bounds and the new detail metrics
fail closed before an Artifact commit.

The first bounded calibration reused 24 approved institutional object crops and all 18 raster BASE
outputs from the immutable 89-subject benchmark.  The predecessor contour gate rejected one overly
dense galaxy output.  Of the remaining 17, the successor accepted all 17 after bounded cleanup; an
earlier cleanup without component removal and final border clearing accepted only 3 of 18.  A
second sweep, measured only after both origins were fit to the same 800 x 500 foreground canvas,
selected a final dark threshold of `80`, tones `(32, 96, 255)`, median kernel `5` and the 48-pixel
component bound.  It preserved the 17/17 structural pass rate while reducing normalized median
edge/fine-detail/component measurements from 103/44/77 to 76/14/48.  Institutional object-line-art
medians are 50/2/19.  These measurements justify a candidate, not runtime activation.  Pseudotext,
wrong subjects and scientific defects remain review failures even if their pixel metrics pass.

A first temporary 12-pair sheet was deliberately rejected as acceptance evidence after inspection:
it paired broad families rather than exact depictions (for example, different kinds of organisms or
objects).  That discovery produced the single-track and exact-`depiction_key` invariants above.
The same inspection showed that the separately approved raster reference population is largely
photographic/halftone material.  The V7 assessment-line-art route cannot silently serve that track;
a future raster/texture candidate requires its own successor binding and evaluation plan.

## Transaction, concurrency, retry and storage

The orchestrator resolves all input pointers, stages local read-only inputs and owns the only NAS
commit.  The isolated evaluator/provider writes only to a unique mode-0700 workspace.  Same-plan
replay requires byte-identical input and is idempotent; a changed candidate policy or seed receives
a new identity.  The GPU lease serializes provider use.  A failed output remains failed evidence
and is never overwritten.  Review and answer-key Artifacts are committed separately so the review
surface cannot reveal origin before submission.

Generated PNGs, contact sheets and long metric output live in NAS file-set Artifacts with manifests;
PostgreSQL retains only typed pointers, hashes and lifecycle metadata.  Temporary workspace copies
are removed only after a successful orchestrator commit and receipt verification.

## Dependency direction

JSON Schema 2020-12 and frozen Pydantic contracts live in `image_contracts`.  Evaluation domain
logic consumes decoded bounded rasters and has no SQLAlchemy, filesystem, systemd or HTTP imports.
The application service resolves pointers and coordinates the evaluator.  NAS, PostgreSQL, local
GPU and filesystem behavior remain infrastructure adapters.  Neither the image worker nor the
provider may communicate directly with another worker or write to NAS.

## Failure and rollback

Missing/stale pointers, schema/media/hash mismatch, duplicate source/output members, duplicate
depiction keys, mixed style tracks, answer-key leakage, unbalanced origin ordering, invalid PNGs,
changed provider/model pins, incomplete coverage, out-of-range detail metrics, reviewer `REJECT`,
pseudotext or another critical review defect fail explicitly.  Failure never falls back to an
implicit latest revision or an external model.  Candidate code/config can be removed without
affecting V6.  Runtime rollback is selection of the unchanged V6 binding; immutable benchmark and
review evidence remains available.

## Simpler alternative and why it is insufficient

Looking at hand-picked generated PNGs can find obvious defects but cannot measure recognizability,
separate subject accuracy from style, or prevent reviewer bias.  Pixel similarity to the source
would reward copying and punish legitimate new compositions.  A global LoRA activation based on the
existing 24-sample mixed result would ignore subject-specific regressions.  A small typed blind
comparison plus deterministic metrics is the smallest design that directly tests the stated goal
without changing production or weakening provenance.
