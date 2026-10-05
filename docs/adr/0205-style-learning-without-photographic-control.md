# ADR0205: Separate style learning from photographic control

2026-10-05 UTC. Bounded diagnostic executed through existing geometry1.4, not a
new worker/contract/framework or quality acceptance. Overall illustration goal ACTIVE.

## Fresh diagnosis and corrected output meaning

The actual registered TRAIN24 photo result's3 control/6 raw/6 final PNGs were
resolved after full metadata admission and measured, without inference. Each final
is the byte-exact existing publication crop/grayscale transform, mode L800x500:
all6 are achromatic. Raw LORA trilobite has channel spread>4 in39.086% of pixels;
this is a model-style observation, NOT evidence of color leaking into final PNG.
Do not create a new color-removal gate or rewrite past immutable observations.
Prior raw cream/green notes remain correct; clarify their presentation boundary.

Actual retained controls contain23664/6395/32441 white-edge pixels for trilobite/
ammonite/wagon, with4141/1131/5899 four-connected components. Tiny-component pixel
fractions699/681/664 per1000 are descriptive, not a semantic classifier. Current
control still encodes rough surfaces and nearby/background texture inside the
retained rectangle; the model produces faint tonal relief. The source-free backend
uses full-noise white initialization and30 actual scheduler steps, not photo tone
initialization. BASE and LORA both fail. Causation between control density, short
style training and faint strokes is NOT proven; do not repeat the already rejected
global blur or end0.65 experiment.

## One bounded style capability diagnostic

1. Responsibility:Orchestrator freezes/stages/dispatches one existing native
   geometry1.4 command, isolated provider returns raw outputs, Orchestrator commits.
2. Canonical source:TRAIN24 successful native command/result/manifest, exact fan
   sample imgsourcecrop_1f4b0375c1c545ccbc95a994c008e6ef and its reviewed caption.
   The photo path's geometry declaration was metadata-only; leave it undispatched.
3. Identity:new content-derived command/run with immutable adapter/result pointers;
   do not execute/relabel the earlier metadata-only declaration or replace latest.
4. Resolution:full original TRAIN/baseline/crop authorization and command1.1/result/
   manifest closure, expected schema/media/hash before selected weights. Source
   PNGs are not numerical inputs. Verify installed wheel RECORD/role and unit.
5. Access:bounded pinned metadata, one sample keyed lookup, four ordered outputs:
   BASE/LORA × LEGACY832x512/PORTRAIT768x1024. Caption/negative/seed pins stay exact.
6. Structures/cost:frozen typed commands/pointers/tuples and keyed maps/sets;
   existing7-member staged closure;O(metadata+bounded weights+generated pixels),
   no DB/index/cache/queue change or copied training dataset.
7. Scale:one dispatch/at most4 generations,30 steps/CFG7/seed104729, LoRA strength1,
   T2I residual scale0, synthetic black input, no image initializer/postprocessing,
  10 minutes/16GiB peak. No training, photographic input or reserved-source reads.
8. Concurrency:existing exclusive workspace/GPU lease and canonical publication;
   preserve failed prefix and observe the same handle on ambiguous dispatch.
9. Dependency:existing contracts/application/provider/filesystem adapters; no new
   install/dependency/worker privilege or production model/config/service change.
10. Failure/replay:no auto retry/parameter sweep/seed replacement. Supported
    terminal replay verifies outputs without models/GPU/weights/writes. Save raw
    failures and honest counts; numerical success is not style superiority.
11. Simpler alternative:more photo conversions cannot separate style capability
    from dense input control. This existing contract removes source conditioning
    entirely; it is a diagnostic of available style, NOT a photograph composition
    preservation test. Geometry also changes aspect/noise/size conditioning, so
    do not claim geometry is the only causal difference.

## Decision / remaining gates

Inspect all4 unmodified RGB images at native resolution for crisp strokes,
controlled tone, white paper and literal full pedestal-fan components. Compare
BASE/LORA within each size separately. Own review is not independent blind review,
unconditioned morphology is not reference preservation, and four fan outputs do
not satisfy population/reserved/four-family gates. If both arms remain photograph-
like, prioritize actual style-learning/data/recipe diagnosis, not another controller
sweep. If style is available without control, prioritize separating morphology
from photo texture while preserving essential marks. Either result preserves the
full objective, previous adapters/receipts, and unchanged production binding.

## Actual bounded execution and disposition

One distinct command was registered and dispatched once:
artifact_58f98a11162645caa3064ffd6afdcf7a /
rev_13203f6f19604dc68a18692896ee1aa6, command byte SHA
adc50c4169808f2cae57d8565b5cf6555641bc84de350dba574d5661acd34c30;
run imgsdxlloraevalrun_f4fd691243930e63bbeffa7358f8b7e4.
The old photo geometry metadata declaration remains undispatched.

Result artifact_1b44685d186e46a2b9ec160f0d6cef9c /
rev_ef58d0577be543b8805883c94a372ce7, primary byte SHA
2696712272f723b77db172e5fb92d8147b611858b1d448523b4726998c2f36be:
SUCCEEDED,4 actual generations,25559ms, peak9217375744 bytes. All5 registered
result/raw members reread byte-equal. Full native authority closure and installed
3-wheel RECORD/role preflight PASS. Installed-role terminal replay verified12
SHA+inode/size/mtime entries unchanged with models/GPU/weights/writes=0.

All4 original RGB images and the labelled contact actually viewed:

| Arm | Own observation | Publication disposition |
|---|---|---|
| BASE832x512 | Strong black strokes,3 fans, right subject clipped, unnatural bases | Reject:count/framing |
| BASE768x1024 | Strong guard wirework, zoomed guard/hub, whole base absent | Reject:full-object framing |
| LORA832x512 | Two fan icons, large arrow, detached capsules and gray panel | Reject:count/layout/background |
| LORA768x1024 | Repeated pale spoke/flower motifs on dark full background | Reject:object/style/background |

Decision:INK_CAPABILITY_AVAILABLE_BUT_LORA_COUNT_LAYOUT_PATTERN_FAILURE.
All4 cells are genuinely newly generated; source_images_in_contact=0. The contact
is a display derivative, not altered canonical output. No LoRA superiority or
reference-preservation success claimed. This one-caption/one-seed result does not
establish a data contamination cause or a current runtime implementation defect.

Evidence archive:artifact_8cd31326d20a40b095d4fc7bbcdc8897 /
rev_85a04b6d0cd14af3a5f07e3fa1d981bd,24 members verified byte-equal:
reports/own-review.md SHA19ff7a95978309ce5500501e69c506a5c2b86fd0d8681fc670b176599caa0455;
views/generated-fan-style.png SHAf4e98f960f2f7ababd4b30f0dfdb800bcc97079b677832da9f8936456b001138.
This archive preserves the first CPU operator's wrong raw-schema pointer failure
before binary reads; guards stayed intact and R2 corrected the pointer only.
It also preserves the exact executed submit operator with an E501 import-string
warning and the later lint-only split of that same string; no repeated submission.
Publication/contact/archive operators formatter and Ruff PASS. No core source
changes or newly executed core pytest suite are implied by those operator checks.

## TRAIN eligibility reinspection and next decision boundary

The existing6 TRAIN44 audit contacts were actually reopened after the generated
failure, using the pinned prior audit artifact_bac3d4a6cfc14960897763bb80a98bcb /
rev_424d0a0fb4e446cbb3d2bc5bbddde200, reports/target-audit.json
SHA8240de4d4eecdd53e57fb806d55617699bed1411dcd9bed99dd2dbfcf8ae76ba.
Current24 membership remains pinned by the TRAIN24 command; no original/target
pixel, caption, expression, framing, partition or accepted history was changed.

Confirmed distinctions, NOT a new automatic exclusion rule:

- Object/illustration targets include fan3, rabbit7, sedan12, students14/26,
  plant20/31 and skeleton17/38. Existing crisp strokes already provide useful
  style evidence. Gray fills are not inherently bad or grounds to discard data.
- Authored scenes swimmer6, two boys35 and television42 have correctly explicit
  multi-object captions; they are not falsely labelled single objects. Scene
  composition is a separate learning/evaluation responsibility from object style.
- Bacterium9 and leaf tissue41 contain legitimate repeated biological structure.
  Preserve those data, but do not confuse dense anatomical detail with a simple
  single-object style benchmark or indiscriminately delete small components.
- Exact-count/semantic diagrams include particle beakers10/28 and3 cell panels44;
  meter5, scooter36 and bell jar43 also carry meaningful scientific symbols.
  Separate their code/overlay/count and illustration responsibilities before
  selecting a successor GPU-style cohort. Original institution data stay preserved.

The24 targets do not visibly contain the generated large transformation arrow:
do not report that arrow contamination has been proven. The caption properties
are populated, not missing because absent from serialized JSON. Native fan target
is a single full fan, not the failed generated multi-fan panel. Check actual
training/inference text conditioning, loss/normalization and full native source
eligibility before attributing the error solely to dataset selection or longer
training. Use existing typed owners, with TRAIN-only native object/scene diversity
and document/group deduplication; do not pad samples to reach100 or alter released
pilot limits. Previously rejected global-blur/control-end sweeps stay rejected.

Production binding f96eda843dbcbf9bd4ba0b22e5da7ca7e4485b00cbbfb353f8631f6028eb5845
unchanged; five main services active at archive. New training/reserved reads=0.
Independent blind review NOT_PERFORMED. Full-data learning, reserved generalization,
four-family32-depiction quality/fidelity/resource review and successor Item/HWPX
canary/activation/rollback remain open. Overall goal ACTIVE, no completion claim.
