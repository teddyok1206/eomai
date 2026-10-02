# Institutional science-image style candidate — 2026-10-02

Status: `CANDIDATE_SUBJECT_MATCHED_BLIND_REVIEW_PENDING`

This record separates source implementation and automated evidence from production activation and
human visual acceptance.  The active production binding remains immutable V6.  No Item, accepted
past-exam analysis, LoRA adapter, provider activation, or NAS Artifact was changed by this work.

## Objective

Make locally generated, unlabelled science visual material difficult to distinguish from approved
institutional exam artwork after both are normalized to the same presentation canvas.  This is a
style and usability target, not permission to copy a source drawing.  Exact labels, arrows, values,
apparatus geometry and panel labels remain deterministic SVG/HWPX responsibilities.

The durable design and activation boundary are defined in
[ADR 0173](../adr/0173-institutional-science-illustration-blind-quality-loop.md).

## Immutable input evidence

- reviewed institutional object-line-art crop set: Artifact
  `artifact_df2d008c1d074cad9bb0f22def7246a1`, Revision
  `rev_e3287a5c951e4dca8f4cf6f0a2bfe391`, 24 unique PNG members;
- independently reviewed institutional raster/texture/scene crop set: Artifact
  `artifact_5bca120c22bf444e9424bf1c8d440a4c`, Revision
  `rev_3e119d8935d14e388f89296d1dbb0eec`, 24 unique PNG members;
- diverse subject benchmark result: Artifact `artifact_488613d0142d46f794d829820c5bac9a`,
  Revision `rev_164000aaf8c44e7dafcbe150bfa02b68`, 18 BASE raster outputs plus controls;
- benchmark plan: Artifact `artifact_60be197d5d4d400f8c8f1fe7af0094ba`, Revision
  `rev_b803a0177ab6424496a7f8a7ba1696ef`;
- production V6 is unchanged and remains the rollback.

The authorized source population is not one homogeneous visual distribution.  The 24 object crops
are sparse authored line art.  The separate 24-member raster population contains photographs,
halftone astronomical scenes, geological textures and fossil/specimen rasters.  They share the same
approved training authorization but must not be pooled into one median or one blind comparison.
Selection and metric evaluation use sets and keyed lookups for uniqueness and O(N) bounded raster
passes, including a deque-based connected-component traversal.

## Baseline and candidate measurements

All rows below use the same pinned `FOREGROUND_BBOX_FIT_800X500_V1` presentation.  Earlier
native-canvas diagnostics are superseded because tight institutional crops and full 800 x 500 model
canvases otherwise encode origin through whitespace alone.

| Population | Count | Foreground median (‰) | Dark median (‰) | Mid-tone median (‰) | Edge median (‰) | Fine detail median (‰ foreground) | Tiny components median (‰ foreground) | Component median |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Approved institutional object line art | 24 | 135 | 16.5 | 118.5 | 50 | 2 | 0 | 19 |
| Approved institutional raster/texture/scene crops | 24 | 449 | 193 | 244 | 43 | 0 | 0 | 1 |
| Unprocessed benchmark BASE rasters | 18 | 584.5 | 46 | 545 | 121 | 22 | 2 | 251.5 |
| Candidate V7, diverse BASE reuse | 17 accepted / 18 | 131 | 29 | 92 | 76 | 14 | 0 | 48 |

The raw BASE population was too photographic.  Existing V6 examples removed the background but
retained excessive microline and disconnected noise.  V7 keeps the V6 contour extraction and adds
a pinned final normalization pass:

- Gaussian radius `0.85` and median kernel `5`;
- three final tones `(32, 96, 255)` with thresholds `80` and `235`;
- removal only of disconnected components of at most `48` foreground pixels;
- final horizontal/vertical white borders of `40`/`24` pixels;
- explicit fine-detail, tiny-component and component-count fail-closed gates.

Before small-component cleanup and final border clearing, only 3 of 18 diverse BASE outputs passed.
The final implementation accepts 17; the overly dense galaxy output remains rejected with
`LOCAL_IMAGE_LINE_ART_EDGE_DENSITY_INVALID`.  The rejection is intentional.  The first 17-pass
candidate still had median edge/fine-detail/component measurements of 103/44/77 on the normalized
canvas.  A bounded smoothing sweep selected the values above and reduced them to 76/14/48 while
retaining the same 17-pass set.  The institutional medians are 50/2/19, so further subject-matched
review remains necessary rather than claiming parity from metrics alone.

The expanded institutional measurement exposed a routing invariant: V7 is an
`OBJECT_LINE_ART` candidate only.  It must not be judged against, or activated for, the dense
`RASTER_TEXTURE_SCENE` population.  Raster photographs and textures require a separate successor
candidate and separate blind plan.  Combining the two distributions produces a meaningless median
and would reward the wrong output treatment.

## Contracts and validation

New additive JSON Schema 2020-12 families and matching frozen Pydantic models cover:

- provider binding, request and receipt V7;
- institutional-style evaluation plan, automated result and independent human review;
- a reviewer-safe packet containing only content-addressed normalized left/right PNGs and a
  separately hashed answer key; the evaluator plan itself is never a reviewer payload;
- immutable input/output members, balanced blinded order, at least four subject families, one
  explicit style track, unique exact depiction keys, exact content-derived identities, full case
  coverage and canonical hashes;
- reviewer origin guesses, style/semantic/composition scores, defect codes and recomputed verdict.

Generated pixels may pass metrics while still containing pseudotext, a wrong subject, a copied
composition or a scientific defect.  Those are critical human-review failures; they are not hidden
or repaired by the postprocessor.  `PSEUDOTEXT` now contributes to the recomputed critical-defect
count, and any generated side marked `REJECT` makes a canary-eligible verdict invalid.

The final dormant V7 binding is pinned by
`sha256:15291519fca12605a0775505483b9491d179b53470d248f8d0a004950def1565`.
Catalog now parses deployed provider revisions through one authoritative discriminator and
explicitly rejects V7 as not deployed.  This prevents a candidate binding from falling through to
the V1 parser or being published under V6's `generated-item-stimulus-file-set/9.0` identity while
the required successor file-set and Content Pack do not yet exist.

## Verification status

- full image-runtime non-live suite: 142 PASS;
- repository API/non-image suite: 3,803 PASS, 40 opt-in/environment skips;
- JSON Schema mirrors and canonical hashes: PASS;
- strict type checking in the explicit image test environment: PASS;
- Ruff formatting/check and diff check: PASS;
- 18-subject offline candidate replay: 17 PASS, 1 expected fail-closed rejection;
- temporary 12-case normalized A/B diagnostic: retired because broad subject-family matching still
  paired different depictions and therefore cannot support an acceptance verdict;
- blinded packet/answer-key schema-model parity, deterministic build, origin-field separation,
  exact member resolution and tamper negatives: PASS;
- production activation: NOT PERFORMED;
- canonical NAS publication of the temporary sheet: NOT PERFORMED;
- independent blinded human review: PENDING;
- fresh GPU inference using V7 runtime: PENDING a reviewed release/deployment boundary.

The retired comparison reused immutable raw model outputs and did not create canonical evidence.
A production-canary decision requires a new 12–32 case plan whose two sides share the exact
`depiction_key`, whose entire plan uses one `style_track`, and whose presentation and hidden answer
key are orchestrator-committed as separate Artifacts.  The independent review must meet the
predeclared origin-identification/style/semantic/composition thresholds.

The diagnostic sheet also shows that the stated end goal is not yet met.  Plant, fossil and simple
object candidates are relatively close, but several landscapes and complex scenes remain easy to
distinguish because the generated canvas is cleaner and more uniformly outlined, while institutional
crops contain authored shading, labels or layout context.  One spacecraft candidate contains
pseudotext and must be rejected.  A pixel-metric improvement therefore cannot be reported as
"indistinguishable" without the subject-matched independent review.

The final object-track gallery makes the remaining semantic gap concrete.  Burr fruit, the apple
tree, air-cushion packaging, plants and the fossil retain useful exam-like contours.  Reused BASE
outputs for safety equipment, biodiversity, a non-human animal and a generic consumer product do
not depict the requested subject reliably enough.  They are rejected development evidence, not
examples to publish.  The next blind run must use the production reference-conditioned path so a
verified external morphology reference constrains the requested object while V7 supplies only the
line-art treatment.  Postprocessing alone must not be used to conceal a wrong subject.

## Next safe activation sequence

1. Build and inspect contract/provider wheels from a clean commit.
2. Deploy the V7 contract/provider code as a dormant bounded candidate without changing the active
   V6 Catalog binding.
3. Before any Item-path canary, add the protocol-first successor generated-stimulus file-set and
   Catalog adapter branches required to carry a V7 receipt.  Do not funnel V7 bytes into the V6
   file-set identity.
4. Select 12–32 institutional references without answer-bearing text and generate fresh candidates
   for the same exact depiction keys under the GPU lease through the orchestrator.
5. Commit plan, normalized reviewer presentation, hidden answer key and metric result as separate
   immutable Artifacts.
6. Complete independent blind review.  Reject pseudotext, semantic drift and composition defects.
7. Only if the review says `CANDIDATE_CANARY_ELIGIBLE`, run one Item canary and verify Preview/HWPX.
8. Activate a successor binding separately; rollback remains selection of unchanged V6.
