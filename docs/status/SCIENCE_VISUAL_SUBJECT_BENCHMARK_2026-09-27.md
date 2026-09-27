# Science visual subject benchmark — 2026-09-27 UTC

## Outcome

`ROUTE_COVERAGE_PASS / VISUAL_QUALITY_PARTIAL / GLOBAL_ADAPTER_ACTIVATION_FORBIDDEN`

The occurrence-backed, accepted 520-item science corpus contains 537 visual observations. The
subject inventory closes that population as 514 covered observations plus 23 explicit text-only or
non-rendered omissions. It identifies 87 distinct visual subjects, including cars, anonymous human
figures, beakers, laboratory apparatus, graphs, cells, circuits, geologic sections, astronomical
scenes, fossils, plants, animals, weather, and real-world objects.

One bounded benchmark exercised every inventoried subject. It produced 69 deterministic route
diagnostics, 18 paired local-GPU BASE/ADAPTER comparisons, and two human-raster policy negatives.
Both negatives were rejected and produced no raster output. The 105 PNG outputs and terminal result
were published as one Orchestrator-owned immutable file set. Workers did not access PostgreSQL or
NAS, and the adapter remained evaluation-only.

This benchmark proves route coverage and output integrity. It does not claim that every diagnostic
is production-ready. The deterministic benchmark uses bounded primitive diagnostics, whereas the
real production route consumes worker-authored, sanitized SVG through the Catalog compositor.

## Immutable identities

- subject inventory: `imgscisubjectinventory_8473e2e4b608b99beaf1032f8da6b327`;
- subject inventory semantic SHA-256:
  `sha256:8535a0e629e75b75780317b63cc8acc0603d35f958cf8b1ce6dd23fc8dcfe3f0`;
- benchmark plan: `imgscisubjectbenchmark_8a4f3f03a22a40fe9cf8f28ea0c67868`;
- plan SHA-256:
  `sha256:98e34c03aada8a954d4edba6ff84b5dd0d8f79d6f5253a9959646170fd0093f6`;
- run: `imgscisubjectbenchmarkrun_b5ff907fa7cfba9df65f617fb4e3ce8f`;
- result semantic SHA-256:
  `sha256:5fa0677fc106fa160bf7a191aab049eaddfdd8fed6b15ebf6c966afc0a6775ca`;
- result Artifact: `artifact_488613d0142d46f794d829820c5bac9a`;
- result Artifact Revision: `rev_164000aaf8c44e7dafcbe150bfa02b68`;
- result member SHA-256:
  `sha256:fed507ecfdd169e28c850e519482fe8a6927ae5233f6c9e3506689506a58688a`;
- result file-set manifest SHA-256:
  `sha256:ae0da9b8491837e9fb850083067f91b255b82267737fad19c43297449b09e0c4`.

## Independent quality review

All seven contact sheets were inspected. The review classifies every one of the 87 subjects and
pins the exact inventory, plan, and result revisions.

| Status | Count | Meaning |
| --- | ---: | --- |
| `DIAGNOSTIC_ONLY` | 69 | route executed, but the production compositor was not exercised |
| `BASE_PREFERRED` | 5 | current base output was stronger; keep base-only |
| `ADAPTER_PREFERRED` | 7 | adapter was stronger at this seed; multi-seed and production canary still required |
| `NEITHER_ACCEPTABLE` | 6 | prompt, data, route, or composition needs refinement |

The seven provisional adapter-preferred subjects are air-cushion packaging, cloud/weather, fossil,
geologic rock, ocean water, plant organism, and volcano. Base was preferred for apple tree, burr
fruit, galaxy/nebula, landscape/terrain, and star field. Biodiversity, consumer science product,
microscopic tissue, non-human animal, safety equipment, and spacecraft were not acceptable in
either variant. Observed failures include semantic mismatch, pseudo-text, excessive technical
clutter, composition artifacts, and insufficient exam-style specificity.

- quality review: `imgscisubjectreview_9acf3bcd62e7321eaf20203c8bf6e579`;
- review semantic SHA-256:
  `sha256:50caf73efdd90f0c5116e47bd022546084d32f69016f71931463b81227e46c46`;
- review Artifact: `artifact_aebc6cf021c149a8bbbe170c7e214dd1`;
- review Artifact Revision: `rev_89652f7ba9554499aceefb55f9a0da71`;
- review member SHA-256:
  `sha256:b31a885ae135b627d181c6d91eec74ec99571eef55b914380cc8fdd25cc41dc8`;
- review file-set manifest SHA-256:
  `sha256:3d781efc05edfe3362252e970addff7aa3d345f704a29e35553853cebd5275f8`.

## Three-seed stability review

The 18 raster-generating subjects were rendered again with two additional fixed seeds, producing
72 new BASE/ADAPTER PNGs. Together with the initial seed, each subject therefore has three human
visual decisions. The successor plan, output set, and review are immutable Orchestrator-owned
Artifacts; no worker accessed PostgreSQL or NAS.

| Stability | Count | Decision |
| --- | ---: | --- |
| `STABLE_ADAPTER_PREFERRED` | 2 | plant organism and volcano may enter a separate bounded production canary |
| `STABLE_BASE_PREFERRED` | 2 | galaxy/nebula and landscape/terrain remain base-only |
| `NEITHER_ACCEPTABLE` | 2 | consumer science product and safety equipment require route/data/prompt work |
| `MIXED` | 12 | no adapter selection; refine and re-evaluate rather than cherry-pick a seed |

The result forbids global adapter activation. A favorable single image or seed is not an
activation gate.

- multiseed plan: `imgscisubjectmultiseed_78792e2ad9bf73ea19892fd3954b15bd`;
- plan semantic SHA-256:
  `sha256:e77599e69eebfd5a8a97c2045c60c7cbe6aeb907a289783c0d98670065d72731`;
- plan Artifact / Revision: `artifact_187fc040d12847c3b2dc9e9e2fd76641` /
  `rev_503c9609970a46f989fd4191dfc2e0a1`;
- run: `imgscisubjectmultiseedrun_e86f54f8ee98150d984e2dc254edcf36`;
- result semantic SHA-256:
  `sha256:b67a68a939eeaeaa79ac2ae85883985e802c41f734359827809d81655afb6824`;
- result Artifact / Revision: `artifact_e268bf5bfcf0438ab956bedbff4a0b8c` /
  `rev_b01b6ebed2944fdc8dcfb60f9fdc5b96`;
- result file-set manifest SHA-256:
  `sha256:c831c2d39c70cf0d0e5cd85d91bab27387eb931e2e21471cf439ced6af1d600f`;
- multiseed review: `imgscisubjectmultiseedreview_69b7f41e1f117279b7084b6fb37f3404`;
- review semantic SHA-256:
  `sha256:5e001944e6d3da5b00c77ee649900d2e6ead0afa55a63437ab5c07d6ae5f242b`;
- review Artifact / Revision: `artifact_4f4408a0a3304edc9e7cc38ee299ab80` /
  `rev_b2a69a5df00543e8b95fc1461e10bf9d`;
- review member SHA-256:
  `sha256:251652bce381b7f09822662ab733cc08d779091e0c158d3ff39d8a91af889944`;
- review file-set manifest SHA-256:
  `sha256:1ffa65502ec8852f7a974f349125f9c29173d1de439b39ae907cb09d8f74e72e`.

## Production SVG and HWPX boundary

The deterministic benchmark PNGs remain diagnostics. A separate focused regression now exercises
all 14 supported science-diagram primitives through the production safe-SVG sanitizer, pinned font
set, `rsvg-convert 2.58`, and 800×500 PNG validator. The 73 fixed `PYTHON_SVG`/`HYBRID` subject
definitions use 13 of those primitives; `TIMELINE` remains the supported fallback for timeline
observations. All 14 representative outputs were valid and byte-distinct.

The existing HWPX V2/V3 renderer regression was also rerun for one- and two-image documents. It
verified exact PNG bytes in package-internal `BinData` members, `isEmbeded=1`, no external file
path relationship, no image-placeholder text, and editable `(가)/(나)` text for two-image layouts.
This proves the production composition and packaging boundary; it is not a claim that all 69
diagnostic subjects have individually passed a human quality review.

## Next gates

1. Keep global production on the base-only binding. The three-seed review forbids global adapter
   activation.
2. Keep stable-base subjects base-only. Refine prompts, dataset coverage, or route selection for the
   12 mixed and two neither-acceptable subjects, then re-evaluate through an additive successor.
3. If plant and volcano are promoted, use a subject-gated successor binding and bounded Item,
   Preview, and package-internal HWPX canary. Do not reinterpret the current global binding.
4. Rollback must select the existing base-only immutable provider binding.

No benchmark or review result activates the LoRA adapter, changes a provider binding, rewrites the
520 accepted analyses, or requires one HWPX build per subject.
