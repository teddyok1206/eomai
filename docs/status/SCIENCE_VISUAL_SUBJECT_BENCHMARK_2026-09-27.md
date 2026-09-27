# Science visual subject benchmark — 2026-09-27 UTC

## Outcome

`ROUTE_COVERAGE_PASS / VISUAL_QUALITY_PARTIAL / ADAPTER_ACTIVATION_FORBIDDEN`

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

## Next gates

1. Re-evaluate all 18 raster-generating subjects with additional fixed seeds through an additive
   successor contract. A one-seed preference cannot authorize activation.
2. Exercise representative deterministic subjects through the real worker-authored safe-SVG and
   Catalog compositor path. Route diagnostics must not be promoted as production fixtures.
3. Keep base-only production for base-preferred subjects. Refine prompts and augment reviewed,
   rights-approved training data for the six subjects where neither variant is acceptable.
4. Only after representative Item, Preview, and package-internal HWPX canaries pass may a successor
   provider binding be considered. Rollback must select the existing base-only binding.

No benchmark or review result activates the LoRA adapter, changes a provider binding, rewrites the
520 accepted analyses, or requires one HWPX build per subject.
