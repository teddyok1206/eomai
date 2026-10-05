# ADR 0204: Stroke-led native TRAIN pilot, separate from reference preprocessing

## Status and evidence

2026-10-05 UTC. Bounded experiment executed through existing released contracts.
Training and matched-transfer execution PASS; overall own exam-style review FAIL,
with one local improvement. No activation or broader-goal completion. The design
below was committed before dispatch; actual receipts are recorded separately below.

ADR0203's six novel-photo retained-region outputs still have gray relief and one
unwanted LORA object. Canonical TRAIN44 audit actually inspected all44 targets:
9 contour/6 fine-hatch/29 tone, with precise ink/flat-fill drawings as well as
soft raster, gradient and texture. This heterogeneity is observed; its causal
effect on failed photo transfer is NOT established. BASE also fails. Preserve
native44/200-update baseline and previously promising fan/beaker examples.

Twenty tagged-contour candidates outside the current training sample IDs were
re-resolved from the immutable95-source TRAIN pool and actually viewed. Some are
alternative frames of an already used subject; others contain connected leaders,
exterior text/arrows, soft rasters or intentional partial figures. A tag is not
admission. Their original pixels/labels/old deferrals remain unchanged. New source
framing/preparation is a separate task, not mixed with this training factor.

## Bounded design

1. Responsibility/boundary: existing native-training Orchestrator prepares one
   own-reviewed cohort and dispatches one isolated numerical worker. No new queue,
   training framework, registry, model, dependency, privilege or production path.
2. Canonical source: native44 command1.1 artifact_22c13da7e8c544b395f73b5f316520e9 /
   rev_ad049b679783422685f0458ba495a1ee, byte
   33e8ec620670c5347d8c38c79b86ac8ec1614fe119d26017892273d49e2bf0a5;
   TRAIN audit artifact_bac3d4a6cfc14960897763bb80a98bcb /
   rev_424d0a0fb4e446cbb3d2bc5bbddde200. Original target PNGs never changed.
3. Identity: new content-derived native-training command/run and terminal adapter
   revision under existing command1.1/result1.0/manifest1.0. Do not mutate old
   command, recipes, targets, captions or weights. Existing JSON Schema/Pydantic
   contracts already express an own-screened12–64-target pilot; no successor wire
   merely to encode a different valid frozen selection.
4. Resolution: exact artifact/revision/member/schema/media/SHA/access/lifecycle,
   source authorization, physical-frame nonoverlap, document TRAIN partition and
   command/target/caption closure before selected PNG reads. Missing/stale fails;
   no latest substitution, duplicated reframe or count by filename.
5. Access: ordered immutable24 samples, keyed target/batch lookup, sets for
   uniqueness and Counter concentration checks; selected-only bounded PNG staging.
6. Structures/scale: existing frozen samples/pointers/command, no DB/index/cache
   change. O(cohort+metadata+selected pixels), bounded16MiB target materialization;
   model/weights materialized only through the existing guarded model adapter.
7. Selection: audit ordinals2,3,4,5,6,7,9,10,12,14,17,20,22,23,26,28,31,35,36,
   38,41,42,43,44. Exact9 CLEAN_CONTOUR,4 FINE_HATCHING,11 RESTRAINED_TONE.
   Stroke-led does not mean binary ink: meaningful flat gray fills/hatching remain.
   Selection excludes soft/gradient-dominated examples without editing them;
   diagrams and existing labels are not recertified as scientifically exact.
8. Concurrency/transaction: one unique workspace/run, existing exclusive GPU lease
   and one terminal publication via Orchestrator. At most one training dispatch,
   200 updates,1 hour,16GiB allocated GPU. No automatic retry/resume/sweep; inspect
   the same handle if observation times out. Preserve failed/partial histories.
9. Adapter/dependency: same SDXL base, rank/alpha8, learning rate1e-4, fp16,
   gradient accumulator4, optimizer, seed20261005, VAE precision policy and installed
   numerical dependencies. Only cohort selection changes. Training source remains
   staged local inputs; no worker repository/DB/NAS/root-auth access.
10. Evaluation/failure: training SUCCEEDED is not quality PASS. If it succeeds,
   declare a new existing-contract configuration that pins this adapter, then one
   six-output same-photo/prompt/seed/initializer/full-control/retained-region pair
   against native44. At most6 generated outputs; no mixing prompt/controller/
   region changes or undeclared output postprocessing. Reserved validation,
   untouched final HOLDOUT, scientific fidelity and independent blind review stay
   separate required goal gates. No Item/HWPX canary before actual quality gates.
11. Simpler alternative: use the nine contour-labelled targets alone or threshold
   every target. Nine do not meet the existing pilot minimum/diversity and binary
   thresholding can erase useful science-bearing fills. The24 selection uses
   already reviewed canonical samples and unchanged valid contracts, tests one
   training-distribution hypothesis and avoids new crop/preprocessing confounders.

## Execution gates and rollback

Before dispatch: schema/Pydantic/canonical command and complete metadata admission,
installed wheel RECORD/dependency/source-free worker role, selected input hashes,
no active numerical image unit, exact systemd template and GPU lock preflight.
Core code is unchanged; existing native admission/lifecycle tests apply, and this
specific command must pass live readmission. Do not cite old tests as this pilot's
numerical or quality acceptance.

After terminal result: validate exact result/manifest/weights, supported no-model
terminal replay and immutable publication. No deployment or activation involved;
rollback is leaving the preserved native44/production binding selected. Do not
overwrite failed results, reset leases, patch DB rows or silently reinitialize.
Any new comparable evaluation input/configuration requires its own frozen command
before generation. Broader goal remains ACTIVE regardless of this pilot outcome.

## Actual bounded execution, 2026-10-05 UTC

One24-target native pilot completed200 optimizer updates in472773ms, allocated
peak6166987776 bytes; result SUCCEEDED. Exact source-closed command1.1 byte SHA
451427f18626563557c9dc651359026ae159c049e710efa5c7f25a786dae2b5f,
artifact_52e5cbb42d884723955a4c1e8166130a /
rev_0188f6e9a9084c7b8d205e82072796ea. Registered result/manifest/configuration/
weights:artifact_707dfc07965040ffbb4cf62c4fb1b35f /
rev_3eb77c9dbac24387b50f697213f38c31;4 members reread with identity/hash checks.
Source-free installed trainer replay verified all64 workspace SHA/stat snapshots
unchanged without Torch, model/decode/backend training or writes.

One six-output photo-style1.4 comparison then completed in35946ms, peak
10763033600 bytes. The exact command run is
`imgsdxlvalcmprun_65584e748c2a0ba2a9091ebb6410006d`; no additional dispatch or
retry. Registered19-member result artifact_2dde475ef64e4bef8bfb71b7cb115d1d /
rev_bd8748cdeea44e87ba6b26a120d40d9d; result bytes SHA
ec637091d60e55ef56ca7a3466beca23a7e4145b48f81a23443b7149e3201378.
Native geometry1.4/reference1.2 successor configuration was metadata-only,
never dispatched or claimed as independent geometry acceptance.

CPU proof preserved all3 conditioning/white-initializer hashes and exact
photo/case/prompt/negative/seed/control/region reviews/base/runtime. Both tokenizer
capacity12-row proof was reused only after matching exact prompt/base/tokenizer
provenance, not because the changed adapter configuration SHA was identical.
The15-member registered old44/new24 matched comparison has identical BASE pixels
in all3 cases and changed LORA pixels in all3. Fixed updates with a smaller cohort
also change repeat exposure; do not claim a pure causal test of contour proportions.
Installed photo terminal replay verified95 workspace SHA/mtime snapshots with no
model, GPU lease, transform or write side effects.

All6 unmodified native832x512 RGB outputs and the labelled matched contact were
actually viewed. Ammonite's invented far-left spiral disappears; border foreground
per1000 falls47→4. Trilobite gray relief/cream-green cast and wagon grain/background
remain. LORA midtone per1000 is342→353 /260→261 /135→96 respectively. Metrics and
lower loss are not scientific correctness or quality acceptance. Decision:
PARTIAL_LOCAL_IMPROVEMENT_NOT_ACCEPTED_FOR_EXAM_STYLE. No general superiority or
independent blind review claim; exact morphology remains NOT_VERIFIED.

Immutable44-member evidence artifact_5ddb64d447da47f99beab79a1bdc5041 /
rev_3447cddccb1649ffa16135606e49889f, reports/own-review.md SHA
3e76f51a2705b689e3817b71464a53af31a1371b5030742161ab37aa036ba2c2,
views/matched-comparison.png SHA
d66053ca04d9e218934285b0325ea399d79fdd355b240cc2825f598632f96f9f.
All44 archived members reread byte-equal. Includes the twenty-candidate own review,
exact executed/corrected inspection operators, metadata/dispatch/replay/publication
receipts and logs. Original source PNGs/weights are not duplicated in evidence or Git.

No core/schema/DB/dependency/installed runtime/production changes. Installed
contracts/provider remain437280d3, trainer3625b079; wheel RECORD/dependency/role
preflight PASS. Experiment design source was0fe42641; a later documentation commit
does not retrospectively change runtime/source pins. Production binding SHA
f96eda843dbcbf9bd4ba0b22e5da7ca7e4485b00cbbfb353f8631f6028eb5845 unchanged;
five production services active at archival. No reserved validation/HOLDOUT reads.
Local operator formatter/linter checks PASS; previous core tests are not relabelled
as newly executed tests. Next isolate the actual control/style-transfer bottleneck
(BASE fails too) before another frozen factor; do not indiscriminately expand data,
training duration, prompts and conditioning together. All broader goal gates remain.
