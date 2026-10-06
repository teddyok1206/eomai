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

## Bounded installed conditioning parity check

Before another training recipe change, run the opt-in integration diagnostic
test_sdxl_conditioning_parity.py against the current installed wheels and the exact
registered TRAIN24 command. Existing Orchestrator resolution admits the full
native authority closure before staging only the small immutable command and
hash-pinned test into an isolated local eom-image workspace. The numerical role
has no DB/NAS/repository access. No dataset PNG, reserved input, LoRA/UNet/VAE
tensor, optimizer, image generation, GPU lease or production write is required.

This CPU-only test loads the2 existing pinned text encoders, calls the actual
trainer caption-encoding function, and compares hidden and projected pooled
outputs to the actual installed T2I pipeline encode_prompt for all24 captions.
Only device routing is patched from CUDA to CPU; embedding/tokenizer/pooling
computation is not mocked. Require exact fp16 tensor equality, finite values,
both tokenizer capacities and all realized native time-ID geometries. A real
pipeline is constructed with text modules only; configuration-only UNet shape
checks are explicitly distinct from UNet inference. Default invocation must SKIP
unless explicitly opted in. Limit one execution,10 minutes CPU/2 threads, with
the same terminal handle observed rather than repeating on observation timeout.

This diagnostic can reject a text-conditioning mismatch, but cannot certify
CUDA numerical parity, optimizer/loss correctness, trained style improvement,
fidelity or full model/production quality. Keep those gates separate. Preserve
the executed test/operator/log and report actual two text-model loads, not zero
model calls merely because no images are generated. No new wire protocol,
framework, dependency, install or released recipe reinterpretation is introduced.

### Actual parity result and fresh TRAIN diversity evidence

Source test commit dcbf8df36d5ae08727a555e681c6504a8a495e81. Default focused run
42 PASS/4 expected opt-in SKIP; test formatter/Ruff and scoped mypy PASS. The
installed eom-image CPU run genuinely executed4 tests and PASS (PID308971,
2026-10-05 23:22:19.461348–23:23:52.680954 UTC, returncode0). All24 exact captions
have byte-equal hidden[1,77,2048] and pooled[1,1280] fp16 tensors between the actual
trainer and installed T2I pipeline; maximum deltas0, all finite. Maximum actual
token length56 of77 in both tokenizers. All3 native time-ID geometries agree.
Two real frozen text encoders loaded; no GPU/generation/training/dataset pixels.
Installed3-wheel RECORD/role/dependency preflight PASS, installs0, staged files
unchanged. This is CPU device-routed text parity, not CUDA/optimizer/loss quality.

The first owner invocation rejected group-writable source-test mode664 before
runtime/model/workspace creation. Tightening permissions only on the newly created
task file to600 retained identical source SHA. Preserve that first log and the
separate successful R2 log; no runtime/core pointer guard was weakened.

Existing campaign/source lineage was then re-resolved before fresh PNG reads.
Current pool:503 TRAIN candidates/49 documents,39 documents absent from native44.
First20 new documents × largest3 candidate boxes yielded60 display views from47
pages (26292027 bytes), exact schema/media/SHA/dimensions verified. All5 contacts
were actually viewed at their native1920x1380 display resolution. These are
ORIGINAL institution crops, NOT GENERATED images or admitted native targets.

Own exhaustive routes:12 native-reframe candidates,17 text/table regions,
29 primarily code/graph/map/exact-count regions,2 photograph-reference regions.
The12 ordinal candidates are4,6,14,16,18,22,24,25,30,34,47,55:apparatus bodies,
tree, thermometer, bus/person scene, sky scene, students, biological structure and
clouds. Their full original/native576 frames and literal captions still need
supported review. Newly admitted samples=0. Scientific symbols stay in canonical
sources; no automatic pixel erasure or accepted-state mutation. Largest-area
sampling favors whole questions/text;12/60 is NOT corpus-wide illustration yield.
Inspect original pages/smaller candidates, not the largest-box heuristic as if it
were a style extractor. Preserve useful scenes, gray fills and reference/code data.

Evidence artifact_003f69df380b42cca1ce8ba244b3f2a6 /
rev_57a8abccba6d48d69da8f37137b6180c,20 members reread byte-equal:
reports/own-review.md SHAfa6711cb57a1956630a1a42dc3cea2acdb2b013a18ba91ad940b104928cbacd5;
logs/conditioning-test.log SHA29b65d32eebfd5a29fcee12e20ed7e55decbe39d1de41808e5ffc8abb2e1f1eb.
Archive includes exact test/operators, first failure, R2, source report and5
original-not-generated contacts, not duplicate canonical47 page PNGs or weights.
Production binding unchanged and five main services active at archival.

Training exposure is also a confound:both prior pilots used200 optimizer updates
and gradient accumulation4, so the normal successful loop implies800 micro-steps.
That is about33.3 passes for24 samples versus18.2 for44 samples. This follows the
inspected loop/configuration, not a newly captured per-sample training trace or
proof of overfitting. Freeze exposure/cohort together when planning the full
100–200 TRAIN successor; do not equate equal optimizer-step count to equal epochs,
increase steps blindly, relax released limits or duplicate samples to reach100.

Next action is supported native source eligibility/framing expansion and explicit
training-exposure planning, NOT a caption/pooling patch or another repeated small
pilot. Full learning, reserved/four-family32-depiction/independent blind gates and
successor Item/HWPX canary/activation/rollback remain OPEN. Overall goal ACTIVE.

### Native source framing inspection boundary

At source f018a2978deeecdf4765e77021a942b589206c44, twelve original coordinate-context
views were admitted and actually inspected (eleven TRAIN pages,6131869 bytes).
Source-region review1.2/native PDF command-set1.0 owners rendered eleven regions
from six new documents at576 DPI:4554384 pixels,7669149 unique PDF bytes, six
terminal isolated CPU requests and read-only canonical closure replay PASS.
No new protocol/migration/dependency/queue/runtime installation was needed.

Actual native output inspection rejected clipped solenoid/power-supply/cloud frames
and retained annotation/code/reference distinctions on the remaining scenes.
Successful extraction and correct file hashes do NOT imply clean training data.
Corrected preliminary names:ordinal22 is an aircraft temperature display, not a
thermometer; ordinal47 is a pressure/mountain diagram, not a cloud illustration.
Original candidates/reports remain immutable. Gray fills, real winding strokes,
intrinsic controls and authored scenes are not categorically excluded.

Practical rule:actually inspect the proposed frame overlay on the unchanged
original page BEFORE native command registration; inspect actual native pixels
BEFORE target admission. Translate display origin/ruler margins explicitly rather
than estimate display pixels as page coordinates. Extend existing owners; do not
add a crop framework or infer a renderer bug from an imprecise reviewed box.

Seven overlay views were produced, four actually viewed(4,14,16,55). Cloud frame
[480,1465,735,1645] was corrected and rendered once:the complete1020x720 native cloud
was actually viewed, its table border is gone, two original dotted guide lines
remain. First clipped set preserved; no guide-free target or extra independent
sample claimed. Corrected set artifact_fd066b1279fd47a1b3678611ffa11106 /
rev_38f63f6f4e304e28915c1088816daf51, manifest SHA
2141dc7448e7ba1e049b1a173a6378130878d6689f7a94a5ee134c4bb62b5255.

Focused source suites actually99 PASS in13.44s. Detailed per-frame findings, exact
operator lint limitation and contact-only permission failure are preserved in
evidence artifact_a73207e4045c4eed98c6c2ee9023adf8 /
rev_c80dcbc25a9e4963ba94a1ff8aaa269f:46 members reread byte-equal;
reports/own-review.md SHAce00a415f2693c7482ff14d2c99694cdc0644814befcef36dfcc13da8db96e86.
Seven CPU requests/twelve region renders/eleven unique illustrations;
new target admission/training/GPU/reserved reads0. Production binding unchanged,
five main services active. Continue complete framing, coherent native target
eligibility and independent TRAIN expansion; all full quality/activation gates
above remain OPEN. Own inspection is not independent blind review. Goal ACTIVE.

### Reviewed apparatus targets and current preparation pool

At source d9fa3760823e6c7328c8d1a6d48e657298d03a8f, four corrected apparatus
frames from two TRAIN documents were inspected on original pages before two
native CPU requests. Existing target1.2 owners prepared three1024x768 PNGs;
the coil remains deferred because a touching annotation cannot safely be removed.
Complete principal bodies, intrinsic meter/polarity marks, gray fills and short
original connection fragments were inspected and retained, not fabricated away.
These are institution-original-derived TRAIN candidates, NOT generated samples or
independent blind quality approvals. No new protocol, dependency or core patch.

Target result artifact_b96e26a4518c4746bd07d5f1f80c1421 /
rev_129901364ffc45918a3803667529abf3, manifest SHA
8d8753ce290f34166fc9bc80b53b56a8de80556d422fb6deab24ae5fa19c4a5e.
Actual installed numerical-role terminal replay returned the same result with
zero transforms/writes; four committed members reread byte-equal.

Metadata-only inventory now finds54 unique prepared samples from33 documents and
30 exam groups, with nine preparation results and max6 targets/group. This pool
is NOT a frozen training cohort:released selection limits remain <=8 batches and
max4/group. Of the separate95-source selection,53 still lack prepared targets.
Prioritize new exam groups and larger coherent batches; do not pad to100 or relax
FULL100–200 admission, which remains NOT_ACHIEVED. Newly trained updates=0.

Four focused suites actually passed in two bounded invocations(62+68=130).
The initial combined invocation ended143 after partial progress, not PASS; its
cause is unknown. Detailed own review, operators, results and contacts are in
artifact_1dfec15fa3734a8787b909e6af2c9dae / rev_e83f2cc1a8b24d5a82cad170ae72e320:
29 members reread byte-equal; reports/own-review.md SHA
0f4b8feb75d355e0be9a3a2d01f1c44b9a4de77150353339785dc216d4f1a19c.
GPU/reserved reads/production changes0; binding unchanged, five services active.
Full learning, independent quality and Item/HWPX activation gates remain OPEN.

### Remaining-source expansion and caption semantics

At bb37bf00, all53 pending source candidates were actually inspected on original
contexts and native576-DPI outputs:38 unique document requests, two <=32-region
commands, canonical replay0 renders. Existing CPU owners prepared20 targets and
deferred33; two installed role units terminal success, both real terminal replays
writes/transforms0,22 committed members byte-equal. Actual focused suites110 PASS.

Literal source inspection corrected current target captions:the historical
BOXING_GLOVE and BOXER images are a baseball glove and catcher. Historical source
keys/artifacts stay immutable; use reviewed captions, not names alone as truth.
Gray fills, natural portrait/scene frames, original raster limitations and intrinsic
marks remain explicit. Detached annotation removal is a separate supported exterior
recipe, not automatic erasure or categorical source rejection.

Fresh metadata pool74 prepared IDs/45 documents/40 exam groups includes12 new
documents,11 preparation results,max4/doc,max6/group. It is NOT a frozen cohort;
retain <=8 batches/max3/doc/max4/group and deduplicate actual overlapping subjects,
not merely IDs/hashes. FULL100–200 admission and independent quality remain OPEN.
Next:26 supported annotation-repair candidates plus new TRAIN object/nature groups.

Evidence artifact_55d29ac253fb4c26835411b871b89265 /
rev_6eb5ef9d095d448587d09a5f3c668188,63 members byte-equal;
reports/own-review.md SHAfdc903e1c98b9f929e6e845177ee2f0afaad5b9243c7985aea6399aff3967837.
Archive preserves the first metadata-only shard-order operator rejection and its
correction without a core patch. Production binding unchanged,five services active;
new GPU/training/reserved reads0. Full objective ACTIVE, not completion.
