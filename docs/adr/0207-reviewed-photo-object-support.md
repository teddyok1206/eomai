# ADR0207: Reviewed object support before another style experiment

2026-10-06 UTC. Status: diagnostic design; no production activation or
institutional-quality acceptance. Overall illustration goal ACTIVE.

## Actual spatial-input evidence

The registered prompt-only comparison's source, control and initializer were
resolved by the existing bounded owner reader. Source RGB800x504; actual control
RGB832x512 with binary white edges on black; initializer all-white with its
expected RGB hash. Actual execution uses SDXL **ControlNet Img2Img**, not the
T2I lineart route. Polarity and initializer contamination are not found defects.

The retained rectangle contains32,441 edge pixels,27,921 inside the protected
rectangle; zero edges are outside retention. These are geometric counts, **not
semantic background counts**. Own inspection sees grass/ground, trees and the
vehicle behind the intended car surviving inside the rectangles. Rectangular
retention implements its declared policy; this is not a reproduced state-machine
or pixel-preservation defect. Background transmission is a bounded hypothesis,
not proof of the sole cause of pale lines or a reason to retrain.

Evidence: `artifact_62d23ca4b7d94fccaa47f4d2515ccbc2` /
`rev_56118c4b7d4148bcb97652137d3b3f93`, primary `reports/own-review.json`,
operations/plain-text-log/1.0, text/plain, raw SHA
`sha256:9ca6a4d12f4d4ec6e96a730868de4fba491df1f8adde2f75881865fa8c2c76a7`.
Eight members/1,974,995bytes were committed and reread equal. Original PNGs and
weights are referenced, not duplicated. CPU geometry guards:1 positive/5 negative
PASS. Existing subject-region, photo-style retained-region and white-initializer
unit suites:97 PASS in53.81s using the explicit source-test Conda environment.
Temporary diagnostic operators pass Ruff lint/format; documentation diff checks
PASS. No model/GPU calls, training updates or production changes. That initial
checkpoint added documentation only, not a worker or dependency installation.

## Boundary and design procedure

1. Responsibility: existing Orchestrator owns admission, staged inputs and commit;
   an optional provider preprocessor may return a local foreground support mask.
   This is not a new queue, service, DB aggregate or segmentation framework.
2. Canonical source: the unchanged normalized photograph and authored intent.
   Only explicit morphology-only references qualify; scientific scene context
   must not be removed implicitly. The wagon diagnostic has this reviewed intent.
3. Identity: a candidate support mask is a separate immutable derivation, pinned
   to source/control revisions and recipe/review bytes. A future registered mask
   has distinct logical ID, revision, Artifact revision and content hash. No
   reclassification or replacement of the source, TRAIN100, or old controls.
4. Resolution: source/control existence, permission, lifecycle, schema, PNG media
   and hashes are checked before reading pixels. Source800x504 coordinates and
   control832x512 coordinates are distinct. A binary mask must have the declared
   mode/size and nonempty foreground/background; no guessed resize/latest/path.
5. Access: bounded exact pointer lookup, ordered polygon vertices and one raster
   traversal. No scanning all targets, automatic-all-object search or sweeps.
6. Structures: frozen typed values, exact pointers and ordered tuples; a bounded
   binary pixel support map, O(N) space and bounded scanline raster work
   O(N + H*V), for N pixels, H rows and V vertices. Existing
   indexed Artifact lookup is sufficient; no index/cache/migration is proposed.
7. Scale: first inspect **one CPU-only polygon prototype**, with source and old
   control unchanged. It is a code-native control diagnostic, not a generated
   illustration, worker message, semantic model prediction or reviewed product.
8. Concurrency: canonical publication uses the existing owner/idempotency boundary;
   any later model prediction uses the existing isolated workspace/GPU lease.
   One admitted request, no automatic retry or new identity to bypass failure.
9. Dependencies: geometry/pixel diagnostics use current Pillow only. Contracts
   must not import model/filesystem adapters. A worker requires JSON Schema2020-12
   and Pydantic command/result definitions **before worker behavior**. Model
   loading is optional and must be removable without affecting production core.
10. Failure: preserve rejected geometry/output and history. A reviewed support map
    may delete edges but must never invent edges, redraw/inpaint/reposition the
    subject or alter original source bytes. Hash/mode/dimension/context mismatch
    is an explicit error; no automatic repair or successful-status reinterpretation.
11. Simpler alternative: a manually reviewed polygon is sufficient to test whether
    removing irrelevant exterior cues is helpful for this single car. Do this
    before installing another model. A rectangle cannot express this silhouette;
    a generic mask model is unnecessary for the first diagnostic and is not proof
    of foreground correctness. Internal texture can remain under either method.

The polygon prototype is an operations diagnostic published through the existing
plain-text evidence contract, not a new production conditioning protocol. Before
any worker consumes an object-support mask, add a closed successor protocol and
tests for exact source/control/mask pins, geometry, edge-subset preservation,
idempotency and resource limits. **Do not reinterpret photo-style1.5's protected
interior promise**: object-support semantics are different and require an explicit
successor. No GPU dispatch is authorized by a diagnostic file alone.

## Optional model candidate, not installed or numerically ready

SAM2.1 tiny supports prompted segmentation; official code/model information is
at [Meta SAM2](https://github.com/facebookresearch/sam2) and the
[official model card](https://huggingface.co/facebook/sam2.1-hiera-tiny).
Candidate repository revision `de431c4043854a71d8101e17995dfe596bf101a5`;
`model.safetensors`155,908,064bytes, SHA
`sha256:48c14467e5cf9e51870511feb72c89688e82dd74523142c0538b663e193ac2a7`,
from [pinned official files](https://huggingface.co/facebook/sam2.1-hiera-tiny/tree/de431c4043854a71d8101e17995dfe596bf101a5).
This metadata observation is not a registered model manifest or download receipt.

Actual offline CPU probe using the explicit lab interpreter: Transformers4.56.2
imports `Sam2Model`/`Sam2Processor`; constructing the fast image processor fails
because torchvision is not installed. Import success is **not runtime readiness**.
Any numerical model option therefore needs provenance for weights and processor
configuration, role/sandbox verification and a scoped optional dependency. The
[official PyTorch version matrix](https://pytorch.org/get-started/previous-versions/)
pairs current torch2.7.1 with torchvision0.22.1; the CUDA12.8 wheel is a candidate,
not an installed dependency. Exact wheel/hash, compatibility tests and rollback
must precede installation. Do not upgrade torch, let a resolver replace the lab,
install torchaudio for this purpose, or import segmentation packages in core.

## Next gates

Own-view the CPU prototype for whole-car silhouette, both visible wheels, roof
details/antenna, orientation/position and excluded background. Geometric pixel
counts do not establish semantic preservation. If acceptable, freeze a successor
mask protocol, stage/verify it and admit only one matched BASE/LoRA pair changing
control support alone; use the original ink prompt, fixed initializer, adapter,
seed and numerical recipe. Do not combine the rejected prompt-only cue, change
training ratios or regenerate historical baselines. A failed mask review means no
diffusion dispatch; a clean mask still does not establish good generated ink.

Optional model inference is considered only if the simpler diagnostic is useful
and manual support needs scaling. It is not a style-model replacement: LoRA owns
exam style; the source reference owns structure; deterministic overlays own
scientific text. Independent blind review, untouched HOLDOUT, semantic/quality
and resource gates, Item/HWPX canary and activation/rollback remain unfinished.

## Closed mask-review boundary before worker consumption

The first CPU prototype is now actually inspected. It keeps the recognizable
whole-car silhouette, orientation/placement, both visible wheels and roof
protrusions while reducing exposed surrounding scene edges.32,441 prior edge
pixels become12,049, with20,392 deleted/zero added. Interior reflection/detail
edges remain. These are geometric counts, not semantic background or quality
scores. Own decision: suitable **input support for one bounded comparison after
protocol/admission**, not independent review or publication acceptance.

Fourteen evidence members/676,169bytes were committed and reread equal:
`artifact_e827d8e0f14342459fd3009499354b5a` /
`rev_24c4387a44b54b3e91cebf4182902e26`, primary `reports/own-review.json`,
operations/plain-text-log/1.0, text/plain, raw SHA
`sha256:bc2732cc6d2abca43dc22eb3f4aacf5d999a1b6cde3fb5aa1cba413e97920b33`.
New binary mask and candidate control are separate canonical derivations, not
copies of existing PNGs. Two workspace input materializations were explicit;
original source/control bytes were not duplicated in the archive. Synthetic
support guards:1 positive/19 negative PASS. Model/GPU/training/activation0.

Before implementing a consumer, freeze `photo-object-support-review/1.0` as an
additive JSON Schema2020-12/Pydantic contract. Its single responsibility is
binding this own input review to exact source, prior control, mask and candidate
control Artifact members, binary geometry, measured counts and own-review
provenance. Counts are immutable observations to **recompute against bytes**,
not trusted substitutes for pixel validation. Derive review ID/content hash
canonically; forbid implicit latest/paths/extra fields, mismatched schemas/media,
duplicate binary identities and a publication or independent-approval claim.

This contract is not a worker command and does not admit a GPU execution. Its
pure parser checks bounded canonical metadata/hash; the existing Orchestrator
must later resolve permissions/lifecycle/existence and an isolated pixel adapter
must verify PNG modes/dimensions, exact source/control relation and edge subset.
Keep that I/O out of contracts. No new DB/table/index/queue/cache or model
dependency is required. Ordered feature tags and exact pointer lookup are small
immutable values; validation is O(metadata bytes + feature tags). A plain-text
log alone cannot enforce source/mask substitution or canonical replay, which is
why this small closed contract precedes the comparison successor. Old schema
bytes and photo-style1.5's protected-interior semantics remain unchanged.

Implemented source-only boundary: public module `eom_image_contracts.photo_object_support`
and frozen wheel-owned schema SHA
`sha256:a872b6b5b855fcb72d00aa2fda5369d607a4b73f702af9957230718149ba6424`.
It explicitly restricts the source to licensed morphology photographs, not
corpus HOLDOUT. `eom_image_provider.photo_object_support_pixels` verifies four
already-resolved bounded PNG members: exact hashes/modes/dimensions/single frame,
binary tones, candidate=prior*mask, actual counts and non-noop deletion. It never
repairs/re-encodes input and returns small frozen observations, not image bytes.
No path/model/DB/storage operation or permission/lineage approval lives there.

Final focused suite:174 PASS in54.30s (48 metadata +29 pixel +97 historical
region/initializer tests). Ruff lint/format and targeted strict mypy PASS using
the explicit image-test interpreter for Pillow types. Initial source fixture
whitelist omitted `__future__`; the test was corrected. The first type invocation
used API site packages without Pillow; selecting the proper existing interpreter
fixed the invocation without a dependency install or error suppression. Schema
draft patch-application errors caused no runtime or Artifact mutation; final two
copies/generated model/registry SHA match. No released predecessor bytes changed.

Still pending: canonical typed-review admission, installed-role verification and
explicit photo-comparison successor with source/control/mask lineage; no model
dispatch, production install, new execution command or acceptance follows from
these source tests alone. The current mask is a single manually reviewed input
candidate, not a general foreground model or institution-quality product.

## Actual registered-source preflight found a namespace defect

The first development-owner typed-review preflight resolved canonical metadata,
then refused the real normalized source before workspace creation/publication or
model calls. `PhotoObjectSupportReview` incorrectly added `local-image-` to the
normalized-reference schema URI; its synthetic fixture repeated that error.
The authoritative public `VisualReferencePngArtifactPointer` uses
`eom://schemas/image-provider/normalized-visual-reference/1.0`.

Correct the implementation to require that exact canonical URI, not an alias or
fallback. Build the positive test pointer through the existing public model and
explicitly refuse the formerly mistaken namespace. Frozen review JSON Schema
bytes/hash remain unchanged; no accepted review or runtime activation existed
under the defective validator.175 focused/legacy tests PASS in54.36s, Ruff and
strict image-interpreter mypy PASS. Preserve the failed preflight's exact operator
and log; no failed execution is reinterpreted as success.

The primitive review1.0 pins four binary members and own-review provenance; it
does **not** assert full prior-plan/result or permission admission. Its future
comparison plan must separately pin the exact prior photo plan and result and
validate source/trace/context/chronology against them, including the unchanged
full controller recipe. Do not infer latest parents, weaken this separation or
hide parent hashes in a free-form log used as a worker instruction. Owner CPU
verification is not installed-role verification or permission to dispatch.

## Canonical typed review and actual owner CPU verification

With the corrected source URI, four **registered** source/prior-control/mask/
candidate PNGs pass the new pixel adapter: RGB800x504 source, RGB/L832x512
controls/mask, exact hashes, binary tones, candidate=prior*mask and recomputed
32,441/12,049/20,392/0 edge counts. The owner also matches physical source,
case/control trace, context and chronology against the pinned photo plan/result.
This development-owner check is not full native-source closure or installed-role
worker admission. No binary is copied into the new review Artifact.

The temporary registration operator then failed the existing publisher's sorted
member guard **before** publication lock/job creation. Do not weaken that guard
or rerun pixel/model work. A publication-only recovery uses the same prepared
review bytes, ID, semantic hash, timestamp and idempotency key, verifies an indexed
lookup finds zero preexisting jobs, sorts the members and names the primary member
explicitly rather than assuming it is first. Seven members/40,668bytes committed
and reread equal, including both exact failed operators/logs. Existing disposable
SQLite publication recovery/idempotency/identity tests:7 PASS in1.87s.

Canonical primary `manifests/photo-object-support-review.json`,
`artifact_7a5e4d24a7cb4b1d8b4782c06c668ad7` /
`rev_46075d67ff834101b5047703d4285231`, application/json,
local-image-photo-object-support-review/1.0, raw SHA
`sha256:7977a881c02d5db9d4bb249e0e955a2666687eef6731a74b9237da42bccb67e6`.
Logical review `imgphotosupportreview_bf0d602a460ec29a5e840b0002f2cb90`, semantic SHA
`sha256:c2bde052575db66ae68464a6856e36dafbd3a134bd8cdbee0857296715d0c8f1`.
Source implementation `32046673373d88831cf50708eda4ee94782f8567`.
Recovery adds zero binary reads/transforms/model calls; original owner check read
four canonical PNGs. Five services ACTIVE, production binding unchanged, model/
GPU/training/production changes0. The first metadata refusal and second publication
refusal remain failures, not reinterpreted historical success.

Next implementation: explicit photo-style1.6 plan/command/result successor through
the existing owner/provider composition. Its single-case support binding must pin
the typed review **and** prior photo plan/result; validate those parents and exact
physical source/control relation before staged bytes. It must not inherit the
retained-region protected-interior promise. Limit admission to one matched
BASE/LoRA pair, unchanged original ink prompt/seed/adapter/initializer/full
controller recipe, zero training/no auto retry. Compare with the existing original
per-arm outputs, not the rejected cue-only outputs as a changed second factor.
Schemas precede worker behavior; closed runtime codecs must not accept the new
family until the full owner/worker handoff and installed-role guards are ready.
No parent/latest inference, new queue/DB/dependency or production activation.
Independent review, HOLDOUT, final quality and Item/HWPX canary remain open.

### Single-factor preparation contract

The preparation-only status and test counts below record the earlier checkpoint;
the subsequent execution-integration checkpoint supersedes its source-codec
status, but does not imply installation, dispatch or quality acceptance.

The1.6 preparation plan pins five small metadata documents: support review,
its prior photo plan/result, and the original-prompt baseline photo plan/result.
The latter may contain several cases; select one exact immutable case and its
two existing BASE/LoRA outputs by keyed identity, never regenerate them. Exact
source, configuration, seed, full-white initializer, full control, native adapter
and evaluation hashes must agree. The successor case equals the selected baseline
case (including prompts); the support review may originate from another prompt
case only when physical source/control hashes and parent identities agree.

This is preparation-only, not runtime admission: keep existing plan/command/result
codecs closed to1.6 until complete worker integration. One case, maximum two
outputs/one dispatch/no retry; no retained-region protected-interior claim. Pure
metadata lineage uses bounded canonical JSON reads and case/trace maps, O(B+C+O)
time/space for bounded metadata bytes B, at most6 cases C and12 outputs O. It
does not resolve access/lifecycle, decode pixels, prove full native-source closure
or grant dispatch. Existing owners will combine those checks before staging.

Implemented preparation-only plan1.6 and pure parent-lineage validation, with
wheel-owned JSON Schema SHA
`sha256:d57d3bdc2a8051efe230866162076c3458042a0189936f6aeb13ab40f1ea432f`.
One shared plan/result relation function now protects both old execution validation
and new preparation, rather than copying the business rule.47 new tests cover
crossed/rehashed parents, altered prompts/seed/configuration, missing case,
canonicality, timestamps, identity, budget, schema resources and dependency
direction.339 focused/historical tests PASS in126.78s; Ruff lint/format, targeted
strict mypy(3 modules) and diff checks PASS. An initial test invocation guessed a
nonexistent subject-region filename and ran no tests; the corrected inventory
uses `test_sdxl_canny_subject_region.py`. No environment/dependency workaround.

Execution plan/command/result codecs deliberately still refuse1.6; tests assert
that boundary. A source-only preparation parser/schema is not a deployed worker
protocol. Next: actual five-document metadata preflight, followed by explicit
command/result and owner-stage/provider/result integration, installed-role
verification, then the bounded pair. Production model and frozen data unchanged.

### Actual canonical preparation preflight

The development owner resolved exactly five canonical metadata members/32,120bytes
and passed the new lineage check. Selected the original ink wagon case from the
existing three-case baseline; both prior BASE/LoRA output members are preserved,
not generated again. The separately reviewed control-provenance case can retain
its different prompt because exact physical source/control/native recipe agrees;
the proposed execution case itself keeps the original baseline prompt unchanged.

Preparation plan `imgsdxlphotoplan_a248d8257eb96f04b248da7bfe190a75`, semantic SHA
`sha256:54257672afc322dd99a61e43efc9b1b158e7feb20c8235c3418d2d64da4418a9`.
Primary `manifests/sdxl-photo-style-plan.json`, application/json, plan1.6,
`artifact_e3cb7fe89d484e2cb425715197fb91b4` /
`rev_2e03e871e9ab4a01a6a0a19b2c61624d`, raw SHA
`sha256:e3ae8834b9b1a49ff2947927171ceab7044615e17c5cdff18e6438b15f730346`.
Three members/17,410bytes were published by the existing owner and reread equal,
including the exact operator and small verification report. Source66f1cac9;
operator raw SHA
`sha256:97012174c95f82d84d480a000e3ba6addd53b8d8d6c5dbf266b3d614127b3a25`.

Status: `CANONICAL_PREPARATION_METADATA_LINEAGE_PASS_NOT_DISPATCH_ADMISSION`.
This check read no PNG, did no transform/inference/training and installed nothing.
It does not establish full native-source closure or installed-role/staging
admission. Five services ACTIVE and production bindingf96eda84 unchanged.
Runtime1.6 remains refused; command/result/owner-stage/provider integration and
installed verification precede the first pair. Overall quality NOT_ACCEPTED;
independent review/HOLDOUT/Item-HWPX canary/activation remain open. Goal ACTIVE.

### Execution integration ownership

Use the existing photo command/staging/provider/result lifecycle for1.6; no new
service, queue, DB schema/index, model dependency or scheduler. Canonical input
is the unchanged photo and five pinned preparation documents. Orchestrator
resolves their permissions/lifecycle/schema/hash before staging three additional
bounded PNG members (prior control, mask, candidate); the photo is staged once by
the existing boundary. The provider revalidates staged metadata, all four PNG
identities/geometry/counts and reconstructs the previous retained Canny control
from the unchanged source before applying the exact candidate. No latest lookup,
inpainting, regeneration of baseline outputs or mask-based semantic inference.

Keep the dependency DAG explicit: primitive support values -> photo plans ->
photo result contracts -> pure parent-lineage -> execution/source admission ->
owner/provider adapters. Preserve prior public result imports via re-exports.
Move coherent result contracts into their own module rather than introducing
local circular imports. Frozen plan1.6/review schema bytes must remain identical.
Execution results pin the support-parent digest, review/mask/control hashes and
recomputed small pixel observations; no image bytes or new lifecycle in DB.

Dominant operations are bounded indexed pointer resolution, batched reads,
five metadata parses/keyed case/trace lookup and linear image scans. One case,
two generated outputs/one existing GPU lease, no retry; no algorithmic change to
old families. Result/replay validation uses existing immutable hashes/output
closure. Invalid support fails before model resolution/GPU; terminal replay never
repeats inference or Canny transformation. Installed-wheel and role/transform
verification precede live dispatch. Source family support is not evidence of
installed or activated runtime support. Rollback selects existing lab wheels;
production binding remains untouched. The preparation-only alternative cannot
execute the reviewed mask, so these existing boundaries must now be extended.

### Source execution-integration checkpoint (2026-10-06 UTC)

Implemented the explicit1.6 command/result and existing owner-stage/provider/
validation/publication path. Frozen preparation-plan and review1.0 schema bytes
are unchanged. New command SHA
`sha256:6d03a685cd63a98d7a5adf2160bfdd92d07c7a026d7c060dc3ee77e753731556`;
result SHA
`sha256:e1b8611ac178696ce57bbec830ed7b85b7bb6f21d64ffca330eaa40429419152`.
The five parent documents must not only agree with each other: their configuration,
native evaluation and adapter semantic hashes must match this execution's admitted
native source. The source is staged once; three additional PNG inputs are bounded
and revalidated. Publication references the existing canonical candidate instead
of publishing its local conditioning materialization again. Previous photo families
and public result imports remain supported without a circular dependency.

Final combined source run:443 focused/historical cases PASS in190.92s, including
26 new mock-lifecycle cases. Ruff lint/format, strict mypy(11 source modules), both
release-script syntax checks and diff checks PASS. New cases cover succeeded and
failed/partial terminal replay without GPU/model/transform/write side effects;
altered metadata/pixels and incorrect prior-control reproduction rejected before
model/GPU; resealed misleading result observations/native-parent hashes; and
CPU-before-commit publication without duplicated canonical inputs. No GPU/model,
training or canonical Artifact mutation occurs in these tests.

Fixture corrections are not production guard bypasses: the old balanced fixture
declared100 TRAIN pointers without their dependency documents, and could not satisfy
full staged native metadata parsing. Added a complete synthetic100-target,
seven-batch closure and bounded source-crop commands; relative terminal timestamps
bind adapter creation to training completion. This synthetic canonical-store
adapter still does not establish real frozen-corpus permissions or independent
quality. Also corrected moved private monkeypatch targets and the expected existing
metadata hash-error code; no weakening of input/pixel/hash/budget guards. These
development failures were corrected before the final combined PASS.

Status: `SOURCE_EXECUTION_INTEGRATION_PASS_NOT_INSTALLED_OR_QUALITY_ACCEPTED`.
Installed lab release219b9d65 still differs; no deployment, real staging or dispatch
has been performed by this checkpoint. Next: actual canonical full-native metadata
read-only admission, immutable release wheels/RECORD and installed-role guards,
then exactly one matched pair. Production bindingf96eda84 and frozen TRAIN100
remain unchanged. Overall goal ACTIVE; blind review, HOLDOUT, final own quality,
Item/HWPX canary and activation/rollback acceptance remain open.

### Canonical native admission and built-wheel checkpoint

At2026-10-06T09:07:08.974683Z, a read-only development-owner preflight on source
`28324e853139af160d6d3451f5282cb600209a44` passed the real canonical full-native
and support admission:100 targets,8 batches,41 native metadata members;
77 total admitted metadata members/1,102,038bytes. The original preparation plan
and its five parents were reused unchanged. No PNG staging, command registration,
Artifact write, worker dispatch, model/GPU call, training or runtime installation.
This closes the earlier missing real full-native metadata evidence; it does not
claim installed-role, staged-pixel, GPU or quality acceptance. Production binding
file SHA f96eda84 was checked unchanged by the operation. Exact operator
`/tmp/eom-photo-object-support-native-preflight-20261006.py` raw SHA
`sha256:59efd2d4b7db6bb0e9a712d2c9ab45710a22accf49673cb08291d78bf5381119`.

The existing trainer release builder produced three immutable-source wheels;
all three raw SHA/ZIP member uniqueness/bounds and every RECORD row's SHA/size
were verified. New contract/schema/provider modules are required by both builder
inventories. Temporary build directory (not installed or committed to Git):
`/tmp/eom-image-trainer-build/28324e853139af160d6d3451f5282cb600209a44.IB3POO/dist`.

| Distribution | Wheel SHA-256 | Verified members |
| --- | --- | ---: |
| eom_image_contracts0.1.0 | `00c7871c6c4348c5b847726eaeab40010d2a92eea220bec1cc925958f9032e0b` | 282 |
| eom_local_image_provider0.1.0 | `8170158fc4a74926bd323996185d60e09e8f32817c6edfe822eecf2b3de8f44c` | 53 |
| eom_local_image_trainer0.1.0 | `2dd1531698b30a87bd48f1384ae4102372492a5bb62bbccb94881b9ba1f256b3` | 34 |

Remaining next gate: quiescence/rollback review and isolated lab install/role
verification, then one paired masked-control execution. Preserve original baseline
outputs and training data; no new prompt/seed/control/adapter sweep. Goal remains
ACTIVE and overall quality NOT_ACCEPTED.

### Installed lab, actual masked pair and own review (2026-10-06 UTC)

This successor closes the earlier not-installed/not-dispatched checkpoints;
those historical assertions remain scoped to their own timestamps. At09:13:12UTC
the protected operator installed only the two contract/provider wheels from
source28324e85 into the isolated image-trainer environment. Wheel/raw RECORD,
installed-role imports, pip-check and unchanged numerical dependency versions
PASS. Trainer wheel, production provider environment, units and permissions
were not changed. Existing source219b9d65 rollback wheels were verified before
overwrite; numerical dependencies and production binding f96eda84 are unchanged.
The initial local import-check invocation error was fixed before installation.

One frozen command was registered:
`imgsdxlvalcmprun_09ff5de94dfd583c438beac220877a01`, semantic SHA
`69c4fa6c821b5db22db2e652f3332821d3fe99618790ddc712d8711eb9056dd3`;
Artifact `artifact_5b07ce746fbd4d2db86831e9cd87147a` /
`rev_11deaab5f55a4d078a460cd0a06ac467`, command1.6 raw SHA
`85882297f9151afe22ae8fc03fd561527d3f8fc22cf1d307b590e0d2aacf5147`.
The unchanged preparation plan admitted77 metadata members and83 total staged
members. Actual installed UID984/-I CPU validation reproduced the prior Canny
hash from the pinned photo/canvas and verified source/control/mask/candidate
pixels, parent metadata and white initializer. CPU validation loaded no model,
GPU, SQL or repository. Both offline tokenizers passed all4 actual capacity
checks (positive62/negative37, maximum77); no truncation or prompt modification.

Exactly one existing systemd/GPU-lease execution ran09:21:28.980681–
09:21:49.243928UTC:20,263ms,2 actual BASE/LoRA outputs, peak10,763,033,600bytes
on RTX5080. No training, sweep, automatic retry, new execution identity or
production activation. Frozen source/original ink prompt/negative/seed/adapter/
initializer/recipe/TRAIN100 were reused; only reviewed object support changed.
GPU returned idle afterward. Prior outputs were resolved, not regenerated.

Canonical result1.6: `artifact_9ce48c19683b42e08b87e892b4e1ce51` /
`rev_6cdedfd124894eb0a9786bedcfa2bf53`, primary
`manifests/sdxl-photo-style-result.json`, raw SHA
`9f1f96860d1009bfda04851d3d7aef99028d99afeb98c5c18ff96a26a6d18ff4`;
semantic SHA `aeebbe8c7d893b113d7d7b28c2425cdf41010c3f25e4976716f8ea1245fbd42c`.
All6 result/initializer/raw/final members reread byte-equal. Existing canonical
conditioning is referenced, not copied into another result Artifact. Actual
installed-role terminal replay verified the same result with model/GPU lease/
Canny/transform/write paths blocked, unchanged workspace files and no torch/SQL/
repository imports. Owner publication independently verified staged pixels and
result transforms on CPU before committing. All5 pinned source/old/new final
images were read through the canonical resolver at the display boundary.

Own inspection opened the labelled comparison and both new full-size final PNGs.
The contact contains4 model outputs:2 historical above,2 newly generated below,
zero source photographs. A separately exported source photograph is explicitly
NOT a generated output. Trees/grass/rear vehicles visibly decrease; main-car
orientation, placement and two visible wheel positions are broadly retained.
This is promising single-case spatial-input improvement, not semantic proof.
Gray body panels/reflections, multiple hatched contours and wheel/body halos
remain. Masked LoRA's fine-detail metric77milli vs BASE206milli is descriptive,
not an institutional-quality score. Own disposition: **NOT_ACCEPTED** for the
requested crisp sparse exam-line style. Independent blind review, untouched
HOLDOUT, population/four-family coverage and Item/HWPX canary remain open.

Operation failures are preserved, not worker failures or repeated generation:
the group-writable temporary preparation script was rejected before dispatch;
its exact bytes were preserved and mode restricted0600, retaining the reader
guard. A publication-only check mistakenly required a completed oneshot's
in-memory start timestamp after systemd unloaded it. Exact persisted journal
result equality now proves the observed execution instead. journalctl JSON
omits long MESSAGE fields by default, so bounded --all reading was required.
All those failures occurred before publication, with no second GPU dispatch.
Temporary owner operators pass Ruff lint/format; no core source changed after
the preceding443-test run, and that run is not claimed as newly repeated here.

Own review, diagnostic contact, execution/install/replay evidence, exact operators
and failed-preflight logs were committed through the existing Orchestrator:
`artifact_64e559d7fcfc4eb4900603b7580f617a` /
`rev_30c3f54d41a847c5b2867dd9ebe72afc`, primary `reports/own-review.json`,
operations/plain-text-log/1.0, text/plain, SHA
`a1b0ce1d59be81e7562dc556b694c7b50a3cc83cbee0ef9d43f0319106982726`.
All23 members/625,906bytes reread byte-equal. Original source, historical and new
individual PNGs are pointers, not duplicated in the evidence archive; the contact
is an explicitly derived diagnostic. Local sample views:
`/tmp/eom-photo-object-support-execution-20261006/{matched-contact,masked-base,masked-lora}.png`.

Next: read the existing rejected global-blur/control-end and style-only/native
training evaluations before choosing another bounded factor. Separate residual
photographic interior control from learned sparse-ink style; this result does not
authorize a parameter sweep, segmentation dependency, more training or activation.
Overall goal ACTIVE. Production unchanged; five main services ACTIVE.
