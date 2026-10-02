# Institutional science-image style candidate — 2026-10-02

Status: `CANDIDATE_BLIND_REVIEW_PENDING`

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

- reviewed institutional crop set: Artifact `artifact_df2d008c1d074cad9bb0f22def7246a1`,
  Revision `rev_e3287a5c951e4dca8f4cf6f0a2bfe391`, 24 PNG members;
- diverse subject benchmark result: Artifact `artifact_488613d0142d46f794d829820c5bac9a`,
  Revision `rev_164000aaf8c44e7dafcbe150bfa02b68`, 18 BASE raster outputs plus controls;
- benchmark plan: Artifact `artifact_60be197d5d4d400f8c8f1fe7af0094ba`, Revision
  `rev_b803a0177ab6424496a7f8a7ba1696ef`;
- production V6 is unchanged and remains the rollback.

The source set includes plants, animals, fossils, laboratory apparatus, physical objects, terrain,
weather, Earth/space and mixed real-world scenes.  Selection and metric evaluation use sets and
keyed lookups for uniqueness and O(N) bounded raster passes, including a deque-based connected-
component traversal.

## Baseline and candidate measurements

| Population | Count | Foreground median (‰) | Dark median (‰) | Edge median (‰) | Fine detail median (‰ foreground) | Tiny components median (‰ foreground) | Component median |
|---|---:|---:|---:|---:|---:|---:|---:|
| Approved institutional crops | 24 | 188 | 29.5 | 138.5 | 106.5 | 2 | 7 |
| Unprocessed benchmark BASE rasters | 18 | 827 | — | — | — | — | — |
| Earlier production V6 examples | 2 | 88.5 | 73.5 | 140 | 916.5 | 76 | 1142.5 |
| Candidate V7, diverse BASE reuse | 17 accepted / 18 | 115 | 28 | 92 | 108 | 0 | 90 |

The raw BASE population was too photographic.  Existing V6 examples removed the background but
retained excessive microline and disconnected noise.  V7 keeps the V6 contour extraction and adds
a pinned final normalization pass:

- Gaussian radius `0.7` and median kernel `3`;
- three final tones `(32, 128, 255)` with thresholds `192` and `235`;
- removal only of disconnected components of at most `16` foreground pixels;
- final horizontal/vertical white borders of `40`/`24` pixels;
- explicit fine-detail, tiny-component and component-count fail-closed gates.

Before small-component cleanup and final border clearing, only 3 of 18 diverse BASE outputs passed.
The final implementation accepts 17; the overly dense galaxy output remains rejected with
`LOCAL_IMAGE_LINE_ART_EDGE_DENSITY_INVALID`.  The rejection is intentional.  Threshold sweeps from
95 through 224 showed 192 was the closest tested tonal match while retaining all 17 structural
passes.

## Contracts and validation

New additive JSON Schema 2020-12 families and matching frozen Pydantic models cover:

- provider binding, request and receipt V7;
- institutional-style evaluation plan, automated result and independent human review;
- immutable input/output members, balanced blinded order, at least four subject families, exact
  content-derived identities, full case coverage and canonical hashes;
- reviewer origin guesses, style/semantic/composition scores, defect codes and recomputed verdict.

Generated pixels may pass metrics while still containing pseudotext, a wrong subject, a copied
composition or a scientific defect.  Those are critical human-review failures; they are not hidden
or repaired by the postprocessor.

## Verification status

- full image-runtime non-live suite: 138 PASS;
- repository API/non-image suite: 3,803 PASS, 40 opt-in/environment skips;
- JSON Schema mirrors and canonical hashes: PASS;
- strict type checking in the explicit image test environment: PASS;
- Ruff formatting/check and diff check: PASS;
- 18-subject offline candidate replay: 17 PASS, 1 expected fail-closed rejection;
- temporary 12-case normalized A/B sheet: generated for review without exposing the answer key;
- production activation: NOT PERFORMED;
- canonical NAS publication of the temporary sheet: NOT PERFORMED;
- independent blinded human review: PENDING;
- fresh GPU inference using V7 runtime: PENDING a reviewed release/deployment boundary.

The temporary comparison is diagnostic only.  It reused immutable raw model outputs and did not
create canonical evidence.  A production-canary decision requires a new subject-stratified 12–32
case plan, orchestrator-committed presentation and answer-key Artifacts, and an independent review
meeting the predeclared origin-identification/style/semantic/composition thresholds.

The diagnostic sheet also shows that the stated end goal is not yet met.  Plant, fossil and simple
object candidates are relatively close, but several landscapes and complex scenes remain easy to
distinguish because the generated canvas is cleaner and more uniformly outlined, while institutional
crops contain authored shading, labels or layout context.  One spacecraft candidate contains
pseudotext and must be rejected.  A pixel-metric improvement therefore cannot be reported as
"indistinguishable" without the subject-matched independent review.

## Next safe activation sequence

1. Build and inspect contract/provider wheels from a clean commit.
2. Deploy the V7 contract/provider code as a dormant bounded candidate without changing the active
   V6 Catalog binding.
3. Before any Item-path canary, add the protocol-first successor generated-stimulus file-set and
   Catalog adapter branches required to carry a V7 receipt.  Do not funnel V7 bytes into the V6
   file-set identity.
4. Generate fresh, subject-matched candidates under the GPU lease through the orchestrator.
5. Commit plan, normalized reviewer presentation, hidden answer key and metric result as separate
   immutable Artifacts.
6. Complete independent blind review.  Reject pseudotext, semantic drift and composition defects.
7. Only if the review says `CANDIDATE_CANARY_ELIGIBLE`, run one Item canary and verify Preview/HWPX.
8. Activate a successor binding separately; rollback remains selection of unchanged V6.
