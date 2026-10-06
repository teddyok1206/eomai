# ADR0211: Separate institutional style reference from object geometry

Status: CPU capability probes, preparation contract, tested resolver and pixels, 2026-10-06 UTC.
No new model installation, pretrained inference, experimental-budget approval,
production activation or visual-quality acceptance is recorded by this ADR.

## Evidence and hypothesis

The native1.3 candidate failed its fixed own visual comparison. The subsequent
TRAIN100 audit and actual six-original views found correctly described apparatus,
legitimate gray planes, hatching and authored scenes, not a missing-caption bug.
Another contour-weight/seed/threshold sweep is not justified by those results.

[InstantStyle's official implementation](https://github.com/instantX-research/InstantStyle)
uses selected SDXL attention blocks to reduce style/content entanglement. Its
global-feature subtraction and style-only layer routing are different techniques;
this proposal uses routing only, not an unimplemented subtraction claim.
[Diffusers' versioned documentation](https://huggingface.co/docs/diffusers/v0.35.1/en/using-diffusers/ip_adapter#style-and-layout-control)
exposes style-only routing while allowing separate structural control. This is a
testable hypothesis for our art, not an institutional-quality guarantee.

Actual installed Diffusers0.35.2/torch2.7.1 CPU probe created a random tiny UNet
with11 IP processors. Public `set_ip_adapter_scale` activated only
`up_blocks.0.attentions.1.transformer_blocks.0.attn2.processor`; other IP scales
were zero and self-attention processor identities were unchanged. An independent
synthetic attention calculation had exact text-only parity at scale0, a finite
numeric effect at scale1 and exact replay after returning to0. Network/CUDA were
forbidden during the probe. This is not real pretrained SDXL/LoRA compatibility.
Installed loader SHA `2b8c3e362cebe9834eab864ec87de84e8dc2754223e37d9c4c5ed7fe75958292`.

The actual ControlNet Img2Img public signature accepts both IP images and pinned
image embeddings. Installed slow `CLIPImageProcessor` converted a synthetic white
224x224 image into CPU `[1,3,224,224]` without torchvision or model weights.
No new numerical dependency is currently justified. GPU observation: RTX5080,
16,303MiB total,2MiB used; this is not a combined-stack peak-memory measurement.

## Model candidate, not acquired

[Official IP-Adapter model card](https://huggingface.co/h94/IP-Adapter)
distinguishes global ViT-H features from Plus patch features. Start with the
global SDXL ViT-H variant, not FaceID, Plus, BigG or a simultaneous retraining.
Public metadata revision `018e402774aeeddd60609b4ecdb7e298259dc729` pins:

| Member | Bytes | SHA-256 |
| --- | ---: | --- |
| `sdxl_models/ip-adapter_sdxl_vit-h.safetensors` | 698,391,064 | `ebf05d918348aec7abb02a5e9ecef77e0aaea6914a5c4ea13f50d45eb1681831` |
| `models/image_encoder/model.safetensors` | 2,528,373,448 | `6ca9667da1ca9e0b0f75e46bb030f7e011f44f86cbfb8d5a36590fcd7507b030` |

Total prospective weights3,226,764,512bytes. Prefer these safetensors; do not
download pickle binaries or clone the complete multi-variant model repository.
The Hub declares Apache-2.0 but contains no own LICENSE member. Official code
license revision `62e4af9d0c1ac7d5f8dd386a0ccf2211346af1a2` is Apache-2.0.
The declared encoder origin's [LAION model card](https://huggingface.co/laion/CLIP-ViT-H-14-laion2B-s32B-b79K)
declares MIT and emphasizes research/task-specific testing. Record both notices;
Hub-repack equality to original LAION weights has not been established. This
does not approve unconstrained product deployment.

The encoder folder lacks `preprocessor_config.json`. Explicitly pin processor
configuration before numerical use rather than fetching an unrelated/latest
processor. Whole-reference fit/padding versus default central crop must be decided
and frozen before outputs, with source and derived-input hashes distinct.
Weights, encoder, preprocessing and style reference are independent identities.

## Boundary and implementation procedure

### Preparation contract decision (no acquisition authorization)

One additive `local-image-sdxl-ip-style-model-manifest/1.0` describes only the
optional global ViT-H adapter/encoder plus their exact six-file notices/config
closure, not another copy of base/VAE/controller/LoRA. Logical identity is the
provider/repository pair; revision identity includes source revision, whitelist,
license provenance and explicit preprocessing. Manifest content hash additionally
pins creator/time/state. Changing any of those is not a latest-revision lookup.

Freeze whole-reference RGB bicubic fit into224x224 white letterboxing. Then use
CLIP normalization/rescaling with processor resize and central crop disabled.
This retains the full style-source framing, including meaningful gray; it does
not binarize, erase tone, crop out components or mutate canonical source PNGs.
Pillow11.3.0/Transformers4.56.2 and the exact CLIP mean/std/factor are contract
values, not ambient defaults. Full-frame RGB pixel preparation is now tested
(checkpoint below); normalized CLIP tensors/embeddings remain unimplemented.
Both later OFF/ON arms must use the same resulting embedding and model stack.

This manifest is an evaluation-only metadata contract; it neither approves a
source image nor starts a worker. JSON Schema is defined before provider behavior.
Pydantic adds exact whitelist, UTC, logical/revision/content-hash checks. Source
and wheel-owned schema copies/hash are checked mechanically. Future file resolver
must use existing descriptor-based I/O for missing/stale/hash/ownership/closure
checks before model load. No downloader/installation is implied by schema PASS.

1. Ownership: existing Orchestrator resolves/stages/commits; isolated provider
   consumes local input and returns local results. No direct worker/NAS/DB writes.
2. Canonical source: frozen licensed morphology reference and existing approved
   TRAIN institutional style source. Do not use VALIDATION/HOLDOUT for tuning.
3. Identity: separate style-model logical/revision IDs and Artifact/hash; pin
   base, existing controller, LoRA, morphology and style source independently.
4. Resolution: existence, permissions, lifecycle, schema/media and hashes before
   pixel/weight load. No URL/path supplied by worker, implicit latest or mixed
   native adapter lineage. Include original PDF/group lineage for style source.
5. Access: a fixed ordered two-case/four-output matrix; keyed member lookups and
   one reusable style embedding per pinned source/config, not corpus scanning.
6. Structures: frozen typed plan and ordered output tuple; map for case/member
   lookup, set for uniqueness. O(cases+members), bounded pixel/model work. No
   new DB index, cache, queue or registry is needed for this small experiment.
7. Concurrency: existing exclusive GPU lease and terminal replay. Both arms load
   the identical model stack; only style scale0 versus1 changes. Record model,
   seed, scheduler, prompt, initializer/control and preprocessing pins.
8. Direction: JSON Schema2020-12 then Pydantic before provider worker behavior;
   extend existing candidate preparation/staging/publication owners. Do not
   reinterpret old photo1.7 or support-review semantics, or add runtime Git use.
9. Failure: no automatic rerun/new identity; preserve failed/rejected output and
   same-key replay. Unknown commit/dispatch is reconciled before more effects.
10. Resources/rollback: local offline safetensors only, exact role/RECORD audit,
    combined-stack measured VRAM within frozen limit. Optional adapter removal
    restores old lab path; production binding remains unchanged throughout.
11. Alternative: prompt-only and dark-cell changes already lacked matched gains;
    style-reference routing adds distinct information. It may still leak depicted
    content or soften geometry. It is not an automatic scientific accuracy fix.

## Proposed bounded execution gate

The old ControlNet fallback12/12 budget remains exhausted. A new four-output
budget and protected acquisition were asked through the user question interface;
no answer is recorded here. Do not dispatch or treat research as that approval.
Protocol development and CPU tests may proceed without model acquisition.

Before any new output: freeze two existing licensed photograph inputs and one
appropriate already-approved TRAIN style reference per case, exact prior LoRA
and structure control, original content-team prompt policy, seed and dimensions.
The older CPU interior-detail prototype is not approved conditioning and is not
combined into this experiment. Four outputs = two cases x style OFF/ON; no sweep,
new fit, unrelated prompt change or automatic retry. Same installed stack for both
arms gives a valid matched comparison; zero-scale CPU toy parity alone cannot
establish actual pretrained output parity.

Open exact institutional originals and morphology references beside each fixed
output. Record contour hierarchy, unnecessary echoes/texture, meaningful tone,
object layout and missing/invented components. Reject content copied from the
style example. This own review is not blind acceptance; independent diverse
subjects/HOLDOUT and subsequent Item Preview/HWPX gates remain OPEN. No canary
or activation follows unless the full requested gates actually pass.

## Executed capability evidence

Existing owner archive: `artifact_fc9be1432efd474f911bd8afe1bec9cd` /
`rev_5b439e63d76b44668fdb56d4358576f1`, primary `reports/own-review.json`, SHA
`45505bc6920d04e8e6fa700a758c0f4f49202f668e4e542fdb3643c360b6ee73`.
Seven text members28,073bytes committed and reread equal; no PNG/model copies.
The archived design is the pre-publication snapshot, not this later receipt.
CPU report and public metadata are evidence, not registered model/worker inputs.
Temporary metadata string-wrapping lint corrections and pre-publication relative
path error were retained; the latter was corrected before any publisher call,
with the prior local review reused only after exact expected-value comparison.
No repeated CPU model calculation, GPU inference or production mutation.

## Preparation implementation checkpoint

JSON Schema2020-12 was drafted before any new provider behavior; the closed
Pydantic manifest, frozen file whitelist/preprocessor/notices and exact logical,
revision and content hashes now implement the preparation value contract.
Schema hash `972d7dab906959d8041b939bee78b80cbb690dfe8026cb744567a521e2648d4a`;
source/package copies and generated-model parity are tested. Existing build
owners require the new model module/schema in their wheels. No new worker,
downloader, resolver, installer, dependency or production route was added.

Focused manifest/controller/dependency regression:105 PASS in5.07s; existing
lineart-stack/native-LoRA/contour/evaluation contracts:136 PASS in4.68s, total241.
Strict mypy
for all three touched core Python files/Python3.11, Ruff/format and diff PASS.
Tests cover modified hashes/IDs/versions, malformed/extra/duplicate/unordered
files, pickle/Plus substitution, timestamp/provenance/preprocessor expansion,
immutability and pure dependency direction. These are protocol tests, not actual
installed-file, CUDA, model-quality, claim/persistence or human acceptance tests.
Wheel build/import simulation was pending at that initial source checkpoint.
The initial `python -m build` availability probe failed in the test environment;
use the existing release script's explicit API `pip wheel` rather than add a
dependency or mutate either environment. No build/install side effect occurred
in that availability probe.

The existing image-trainer release builder then completed from clean immutable
source `b9f3534b879c797618f7ff415f75cbfcfdc1a115`. Three wheel RECORDs verify all
382members (294 contracts,53 provider,35 trainer). Importing the contract wheel
with repository paths removed validates schema/model/pointer without importing
torch/diffusers; this is a pure non-editable contract simulation, not provider or
trainer execution/installation. Contract wheel SHA
`bb87607915e7f29a2b86fc50eaa435664c9ae2c49809460e761a033b2d8459f4`, provider
`52a8ccbaea2f90bfb2e049afff33fe92c423d211abcb83cd8769285a9c0e8afe`, trainer
`3b212ae74bc600425e2c05c2cd9a9edd1c028fb3d9b026053a85c494715997eb`.
Build-only location:
`/tmp/eom-image-trainer-build/b9f3534b879c797618f7ff415f75cbfcfdc1a115.c57FeZ/dist`.
Installed lab remainsd3c03751; production is unchanged. No protected acquisition,
GPU inference, new training, HOLDOUT exposure or independent review. Execution
budget approval is still not recorded. Next: existing-owner file resolution and
closed comparison preparation/consumer; do not submit old contracts or promote
this optional metadata-only component as a ready new inference path.

## Resolver design: six-file descriptor snapshot

The existing provider filesystem adapter owns local resolution; contracts remain
pure. Resolve one exact model/revision/manifest pointer, never scan for another
revision. Build a keyed directory-entry map from the fixed six-file manifest and
open nested directories relative to verified descriptors with no symlink traversal.
Check owner/non-writable modes and exact directory closure, including empty/hidden
extra directories. Read/hash the four bounded metadata files once, validate them,
then stream/hash the two weights once without materializing tensors/weight bytes.
Return a frozen manifest/root result for the protected immutable model store.

Access is one indexed path lookup and ordered six-member traversal. Structure:
directory map/set plus ExitStack-owned descriptors; O(files*path-depth + bytes)
time, O(metadata + 4MiB streaming buffer + directory entries) space. No cache,
new DB/index/registry or duplicate large files. Existing staged-file I/O supplies
safe bounded reads and streaming hashes; exact closure checks are this component's
responsibility, not a second generic filesystem framework.

Metadata admission precedes weight reads. Recheck file/directory identity and
closure before returning to catch replacement during validation. Immutable
root-owned/non-writable runtime storage remains required; this does not grant
numerical libraries a capability to open arbitrary worker-supplied paths.
Reuse stable existing MODEL_INVALID/HASH_MISMATCH provider codes; missing/stale
locations fail explicitly, no latest substitution or recovery. No write, model
download, tensor load, lease, job/worker execution or lifecycle transition occurs.
Tests use tiny bytes with a test-only replaced whitelist; they cannot establish
actual pretrained/safetensor validity or installed-role acceptance. Acquisition,
installation, comparison contracts and runtime behavior remain separate gates.

## Resolver implementation checkpoint — 2026-10-06 15:08 UTC

The provider's `sdxl_ip_style_io` adapter now implements this read-only boundary.
No consumer, acquisition/installer or numerical worker route is implied. Tests
first exposed five missed mutation cases (manifest replacement/permissions and
revision/model/store permissions); they now fail closed. Initial fixture failures
were separately caused by parent-directory umask, not model or production faults;
the fixture explicitly fixes its own modes. No production rows/files were changed.

Before opening files, reject special files, links, writable modes and wrong owner;
then validate/hash once using the existing I/O owner. Manifest and six member
snapshots include inode, size, mtime, ctime, owner, mode and link count. Descriptor
and pinned location checks cover directory substitution, exact nested closure and
permission changes during reads, while allowing unrelated sibling revisions.
No protected store is allowed to be worker-writable. This is a validated snapshot,
not a guarantee against an authorized owner later changing storage or a numerical
library reopening paths; the later model-load boundary remains to be implemented.

New tiny-file tests88 PASS; combined focused manifest/controller/resolution,
legacy SDXL/LoRA contracts and dependency regressions343 PASS in8.59s (the88
are included, not added again). Python3.11 strict mypy four core modules PASS;
Ruff/format, shell syntax and diff checks PASS. Both existing release builders
require the new provider module in their wheels. Official pinned config/card/code
license/encoder notice were reread (four members23,217bytes), matching every
existing size/hash and the new metadata validator. No weight bytes were acquired.
These are not real safetensor loading, installed-role, CUDA or quality tests.

Build/non-editable resolver simulation remains pending at this source checkpoint.
Acquisition/four-output approval is still NOT_RECORDED; old12/12 is unchanged.
Installed lab staysd3c03751; production binding remains unchanged. Full goal
quality is NOT_ACCEPTED. Next safe work is closed comparison preparation; actual
OFF/ON outputs require the pending explicit budget/acquisition approval.

The existing three-wheel builder then completed from clean source
`8402ce9a44690e7050235c107df7d3ec517ec0a0`. All383 RECORD members verify
(294 contracts,54 provider,35 trainer). Repository-free contract/resolver imports
and missing pinned revision refusal PASS without torch/diffusers/transformers
imports. This is build-only import/refusal simulation, not a successful real
weight resolution or installed-role execution. The temporary smoke operator's
overlong description was wrapped to pass lint; no behavior changed.
Contract/provider/trainer wheel hashes respectively:
`07c1612f504c68c5f245de6785146a0745e5b2de50efbfbd29c8334a9ce009aa`,
`d85749b0884c518f109b7cdb71100a1ed20b61a9f93039a3daf7d2cc7267ebb2`,
`00a0dc2bc4d4ce2eee93aa85611de311015328ba819d7161d685827f6336464d`.
Build-only location:
`/tmp/eom-image-trainer-build/8402ce9a44690e7050235c107df7d3ec517ec0a0.3LCnEW/dist`.
No wheel installation, model-weight acquisition, GPU, training, HOLDOUT or
production activation. Do not reuse this as a numeric or visual-quality PASS.

## Pixel preparation boundary

The existing provider pixel adapter implements the already-defined preprocessing
policy, not an execution command or authorization. Its caller must first admit the
style sample's exact TRAIN/source-document lineage through the existing native
metadata owner. The pixel function accepts one frozen native sample and pinned
preprocessor, checks the PNG hash and exact native geometry before decoding, and
fits the complete RGB image into224x224 with bicubic interpolation and white
letterboxing. No central crop, threshold, tone erasure, morphology/control input,
canonical write or network/model load belongs to this boundary.

The returned frozen internal value carries source pointer, profile, placement and
RGB byte hash; the small224x224 RGB materialization is an explicit numerical input,
not a new independently persisted Artifact or cross-service payload. Later worker
results reference trace hashes, not these bytes. One prepared value per source is
shared by the matched OFF/ON arms. Linear pixel work and bounded native image
memory need no cache/DB/queue. File/metadata admission and CLIP embedding creation
remain separate owners. Native samples have at most1024x1024 pixels; reject media,
mode, frame, dimensions, byte-bound, hash or pinned Pillow-version mismatch.

Synthetic geometry/gray/edge tests and direct own views of existing TRAIN sources
plus their224-pixel derivatives are preparation evidence only, not generated
institutional-quality examples or blind/model acceptance. Do not promote the
previously rejected LoRA, count derivatives as GPU outputs, or alter HOLDOUT.

## Executed pixel checkpoint — 2026-10-06 15:27 UTC

Source `01a3d85bb6d6b76930524e03dd9a23f8933284e1` implements only this
preparation function, not the planned numerical comparison consumer. New21 unit
cases are included in364 focused regression PASS/zero skips in9.47s. Strict mypy
for the new core module/Python3.11, Ruff/format, shell syntax and diff PASS.
The first four unit failures identified the test environment's actual Pillow12.3.0
versus the recipe's11.3.0. Synthetic units explicitly substitute distribution
metadata and are not pinned numerical acceptance; no environment/dependency was
changed to hide that mismatch. A separate actual11.3.0 lab execution follows.

The current Orchestrator owner read the exact existing native TRAIN command
`artifact_8c7a653efe0e446e8d5e904aa6941162` /
`rev_2398f9eb27d6436eb534e1cf08181164`, command bytes SHA
`fdf230a6f836c16094f3c0cfb602b3e68b5c2743e3df3bb80fccdc21c00f47d0`,
and admitted its42 metadata members. Six existing first-two-per-expression
calibration examples were selected, each with exact TRAIN partition, source
document/group and source PNG hash checked. No VALIDATION/HOLDOUT reads and
no second copy of canonical source PNGs. This does not authorize future worker
input by a source path or sample's self-declared membership.

The pinned11.3.0 lab interpreter imported the new contract/provider wheels with
repository paths removed. All384 RECORD members validate (294/55/35). Six sources
were prepared twice, exact repeat equality PASS; six224px diagnostic derivatives,
zero embeddings/models/GPU/training or activation. Whole-frame geometry placement
is preserved; no central crop or threshold. Final normalized CLIP tensor/embedding
and combined pretrained stack have NOT been executed. No runtime wheel install.
Wheel hashes contract/provider/trainer respectively:
`a689ad61ab75ea980b3c3be9bf06686cffecf1161a39555afffa42a33d15de0f`,
`0aaaefa007dd95114158cb5937495a7ab71150ab5b142cd617bd11a3d1e6d475`,
`554c787ed66f9c16f07efcf7d47d9d3c5e8a2a0e18dccd0909c3c99f3e825403`.
Build-only location:
`/tmp/eom-image-trainer-build/01a3d85bb6d6b76930524e03dd9a23f8933284e1.KFvC82/dist`.

Actual own views opened three source/derivative pairs: inclined cart/track,
bacterium cutaway and heart cutaway. Complete framing and meaningful gray remain;
fine biological strands visibly merge at224px. **Keep whole-frame style prep,
but do not use this low-resolution style input to guarantee scientific detail.**
Geometry/control/labels retain their separate ownership; future OFF/ON comparison
must still test content leakage and actual style improvement. Three own views are
not six visual verdicts, blind review, generation or educational-quality acceptance.

Existing owner committed/reread all9 evidence members510,373bytes as
`artifact_b69c97f3a9aa4ce9ba86380aa8bbb891` /
`rev_db040fa388e04ae6994c48079e3e920b`; primary `reports/own-review.json`, SHA
`82e0818514055bc9284b23474f0925f072f2331ddd7a490cd6e92ca0bbf28343`.
One labelled1200x2400 RGB diagnostic contact sheet uses the existing operations
image-comparison-contact-sheet/1.0 value format, not a new worker input/schema.
It clearly labels sources versus224px preparations, **none model-generated**;
view-fit contact rendering is documentary and separate from pinned preprocessing.
Temporary six individual derivatives are scratch, not independently registered
canonical sources; reconstruct from the pinned source/profile/RGB trace if needed.
Temporary script string/comment lint corrections happened before archive; no
numerical GPU rerun or hidden recovery. Old histories/12-of12 budget are preserved.
Full quality remains NOT_ACCEPTED and goal ACTIVE; new acquisition/four-output
approval is still NOT_RECORDED. Next safe work: closed comparison command/result
and existing-owner staging/consumer, then actual bounded execution when authorized.

## Matched preparation plan boundary

Add one preparation-only IP-style comparison plan, not another released photo
recipe or a worker dispatch command. Pin an existing balanced photo1.5 command
and result, the exact native1.3 TRAIN source command, and the separate style-model
manifest pointer. Select exactly two photo case IDs and their immutable
conditioning/initializer hashes from that result; select style sample IDs and
prepared RGB hashes separately. Prompts, seed, base, LoRA, control and geometry
stay inherited from the pinned photo documents, with no override fields in this
plan. Both new arms load identical stack/embedding; only IP scale0 versus1 differs.
Do not reuse historical BASE/LORA arms as style OFF/ON or their consumed budget.

The existing preparation/source metadata owners will resolve exact pointers and
validate source status, time, schema/media, hashes, licensed photograph closure,
TRAIN/document/group membership and pixel hashes before staging or GPU load.
Plan schema/model validity alone does not prove those dereferences, membership,
actual stack compatibility or execution authorization. In particular a self-sealed
pointer or a sample ID is not independent source authority. The four-output budget
is a proposed ceiling, not an approval record. No worker accepts this plan yet.

Dominant accesses are key lookup and ordered fixed-matrix traversal: keyed maps
for admitted photo traces/native samples; sets for case uniqueness; frozen tuple
for two selections. O(photo/native metadata + two selections), bounded metadata
memory, no DB/index/cache/queue or binary duplication. Existing immutable Artifact
publisher owns any future registration; existing exclusive GPU lease and terminal
same-key replay own eventual execution. No transaction/state change is introduced
by this value. Missing/stale/hash/status errors stop resolution, never latest
substitution. Simpler extension of BASE/LORA comparison is insufficient because
it toggles LoRA weights and would conflate the factor under test. Preserved photo
protocol bytes/semantics are not reinterpreted by the independent style plan.

## Matched plan checkpoint — 2026-10-06 15:47 UTC

The preparation-only schema/model/parser is implemented; it is deliberately not
accepted by the existing worker command loader. New68 cases are included in365
focused regression PASS/zero skips in76.05s. Strict Python3.11 mypy for three
core modules, Ruff/format, shell syntax and diff checks PASS. Source/package and
generated-schema parity plus registry hash are tested. Schema SHA
`73cf671537019f9e9a9eb678d63a8c6bb4af14643d27fb533cc0ce3ed6c1255c`.
These tests do not admit real source membership or authorize numerical execution.

Existing Orchestrator metadata ownership resolved photo1.5 command
`artifact_22cb3015474c41a4955fa33db8fbd2b0` /
`rev_ec50b74bdb5543408fe6150c16275e48` and result
`artifact_a759c8975e6146cfad36d345ac9468b3` /
`rev_c18fec600dac432882af20cdf2cca8af`, checking canonical bytes, source lineage and successful numerical
parent-result semantics. Its77 metadata members include100 native TRAIN samples
and three eligible photo cases (enrolled trilobite, partially sectioned ammonite
and parked wagon). No source PNG/PDF/weights were opened. Probe SHA
`88476b0d71d0927bd26779cb7d884c6033108e8aab00e9dee0ebf089677810ec`.
Production binding SHA remains
`f96eda843dbcbf9bd4ba0b22e5da7ca7e4485b00cbbfb353f8631f6028eb5845`.
This is a read-only parent check, not a registered two-case selection, approved
IP model, consumer, staging, new output or visual acceptance. The earlier
numerically successful photo result remains quality NOT_ACCEPTED.

## Recurring actual-original calibration

User requested actual institutional originals be reopened regularly. Perform this
at completed training candidates, fixed output comparisons and major changes to
prompt/control/style/publication policy. Do not replace opening the artwork with
loss or pixel statistics. Idle training observation remains30-minute cadence;
do not repeatedly reopen an unchanged sheet merely to claim more coverage.

At this checkpoint the existing labelled six-source contact sheet was actually
reopened. It contains original TRAIN extracts and224px preparations, not generated
outputs; its canonical view remains in `artifact_b69c97f3a9aa4ce9ba86380aa8bbb891`
/ `rev_db040fa388e04ae6994c48079e3e920b`. This is a repeated calibration view,
not six new independent examples or a new blind-review result. Apparatus/heart
use meaningful gray faces and bold directional marks; biological examples can
contain dense internal structure or tonal backgrounds. Therefore retain contour
hierarchy, necessary tone and scientific components while reducing unnecessary
texture/echoes/exaggeration. Do not equate institutional style with universally
thin, thresholded, detail-free black outlines. The224px style input visibly loses
fine internal detail and cannot own scientific geometry.

Full quality remains NOT_ACCEPTED. No new acquisition/four-output approval is
recorded, no model/GPU/HOLDOUT or production change occurred, and the previous
12/12 budget is not reset. Next safe work is the existing-owner source admission
and numerical comparison consumer; a valid plan alone must never start a worker.

The existing builder subsequently produced all three wheels from clean immutable
source `c68f5009fa4e7ad5883912cf15cc68fb8f9f8ebb`. All386 RECORD members
verify (296 contracts,55 provider,35 trainer). A repository-free synthetic plan
round-trip and refusal by the legacy worker loader PASS, with no numerical-library
imports. Synthetic pointers are not a registered plan or real source admission.
Contract/provider/trainer wheel SHA respectively:
`f6286dd0b6e2ba84c6f089880e35e3db2c98ecf4fd6671a60826674ca7dec731`,
`460f65abcfe0a16e03aa56f27825359084989e53d8680fae4b965a3a26546f2b`,
`d599fe994541cac790727e8cbbbdbe0d52e4f1052b8ef91a00489afbcfb879fb`.
Build-only directory:
`/tmp/eom-image-trainer-build/c68f5009fa4e7ad5883912cf15cc68fb8f9f8ebb.YtOtI3/dist`.
No installation/dependency/model/runtime change. Core mypy/format/shell checks
were reconfirmed; the68 plan tests were rerun PASS in2.03s, not added to365.

The existing owner committed and reread all six text evidence members24,771bytes:
`artifact_b4767ef823c446dea398f542beabc7a5` /
`rev_cef812198293478c88106c3603338249`; primary `reports/own-review.json`, SHA
`516100f305b5f089dc17186e72acb1a4cfc3a94f1213478d23f04722598e393d`.
It references the earlier canonical diagnostic sheet instead of copying its PNGs.
The temporary publication operator had an import-spacing Ruff warning, distinct
from the passing core checks and executed owner/readback. Its archived bytes are
preserved; no inference, publication retry or failed-history rewrite followed.

## Selection metadata ownership

Implement a read-only bridge in the existing Orchestrator input adapters. Resolve
the three pinned parent documents with the existing bounded Artifact resolver;
check schema/version, canonical bytes and chronology before lineage traversal.
Require the exact successful photo1.5 result, then call existing photo/native
source owners for licensed morphology and canonical TRAIN/document/group checks.
Native1.3 supplies approved style source PNG pointers only: its rejected trained
weights are not selected. The held LoRA remains the exact photo1.5 parent stack.

A pure contract selector joins case/trace and sample/region by immutable IDs,
checks missing/duplicate references and selected conditioning/initializer hashes,
and returns two frozen rows. It cannot claim that the planned224px RGB hashes
match actual pixels; that requires pinned preprocessing after source admission.
Style model resolution, embedding, GPU admission and execution approval also
remain separate. Nothing writes, registers, queues, claims or dispatches here.

Canonical sources are the three immutable Artifact revisions and their validated
source closures, not self-declared sample IDs. Keyed maps/set uniqueness and
ordered tuples give O(parent metadata + cases + TRAIN samples) time/space at
bounded photo<=6 and TRAIN<=200. No new DB/index/queue/cache or binary payload.
The two existing source owners independently validate distinct parent histories;
bounded metadata rereads are preferable to a new shared authorization cache.
Contracts remain pure; infrastructure adapters alone own DB/NAS reads. Missing,
stale, hash, chronology or membership errors fail explicitly with no latest
fallback/retry/mutation. Existing resolver permission/lifecycle rules are reused,
not reimplemented. A successful parent is numeric history, not quality approval.
The simpler sample-ID-only lookup is insufficient because it permits unrelated
or non-TRAIN inputs and silently changes the matched comparison factor.

The read-only bridge and pure selector are now implemented. New33 tests are
included in224 focused regression PASS/zero skips in41.56s. Source-selector tests
use concrete synthetic TRAIN provenance; owner-order units deliberately stub the
legacy source owners/selector and are not real canonical admission. The initial
failures exposed revalidation against only the base region model, rejecting valid
candidate-backed region fields; revalidation now explicitly preserves the two
supported selection families and rejects unknown subclass extensions. A fixture
result-hash failure was separately caused by omitted default trace dimensions,
not numerical or runtime failure; the fixture now includes its canonical values.
No old source/released schema bytes were changed to make tests pass.

Strict mypy is PASS for two contract modules at Python3.11 and the new Orchestrator
adapter at Python3.12. The initial attempt to check the adapter graph as3.11 failed
on an existing3.12 type-parameter syntax; its actual application target remains3.12,
not a new interpreter/dependency upgrade. Ruff/format/diff PASS. Actual two-case
canonical metadata execution is still pending at this implementation checkpoint;
pixel RGB hashes, installed model stack and quality are not proved by these units.

## Actual selection checkpoint — 2026-10-06 16:10 UTC

Source `6734f582228af38c290bbfa9f5ede092d2f5e979` then ran the bridge on the
canonical photo1.5 parents and native1.3 style-source command. The closed two-case
preparation selects enrolled trilobite with the earlier bacterium TRAIN style
sample, and parked wagon with the inclined-cart TRAIN style sample. Each exact
sample/PNG revision/document/group and conditioning/initializer hash matches the
admitted source. Photo metadata77 and independent style metadata42 PASS; no
PNG/PDF/model bytes or HOLDOUT read. Planned224px RGB hashes reference the earlier
actual11.3.0 preparation report, not recomputation by this metadata probe.

The held LoRA is still photo1.5's native training1.2 command SHA
`f9335bee943558c7e9ef20a21909626b71453fde802a55c37d494bef32bfe869`.
Native1.3 here supplies original style-source identity only, not its rejected
weight candidate. The prospective style-model metadata is unacquired/unregistered;
the two-case plan is an operations preparation value, not a published worker input
or execution approval. Source checks do not validate pixel RGB/CLIP tensors,
style embeddings, actual pretrained combined-stack behavior or output quality.

The first read-only probe finished lineage resolution but failed its documentary
module-hash read: the newly authored repository file had umask-derived664 mode.
Only that newly created module was normalized to644; the safe reader was not
relaxed. The original failure log is retained. With no prior output file or write
side effect, a second read-only query produced the report; no GPU/model/publication
retry, DB row edit or failed history rewrite. Actual API interpreter3.12.13 was
confirmed read-only. Production binding SHA is unchanged from the earlier pin.

The existing three-wheel builder/non-editable synthetic parse/refusal simulation
also PASS from that clean source, all386 RECORD members (296/55/35). These wheels
do not include the Orchestrator application package; the actual source-owned
bridge query is not an installed Orchestrator release test. No runtime install.
Contract/provider/trainer hashes:
`62e928c43f41bb84e784a30599e1d28ebd8d92fb0e0d4a905a4bf7817fb4a8dc`,
`55f69e00b9c261a698c5d9c844988a221885cf8410e852176bfdf96eb8ca2fe2`,
`27f54b7da4ecc6613f3ec600d6aa8ef0041e296484ee65936528a253c0aa0b9d`.
Build-only directory:
`/tmp/eom-image-trainer-build/6734f582228af38c290bbfa9f5ede092d2f5e979.tSP1EO/dist`.

Existing owner committed/reread all seven text members30,771bytes as
`artifact_5945532222414379985d35d40e2c4592` /
`rev_b7a549e40f0d4a23acda2dfe1f338f41`, primary
`reports/selection-metadata.json`, SHA
`043735c8f9d18c24a125b0ded897c808cb2e2b7c458dcabd4b039b07e91e3580`.
The first failure, second read-only result, wheel simulation and exact operators
are separate members; original source PNGs/weights are not duplicated. This is
an evidence Artifact, not a registered IP model or worker-plan Artifact.
Full quality remains NOT_ACCEPTED/goal ACTIVE, acquisition/four-output approval
NOT_RECORDED and old budget12/12 exhausted. Next: pinned CLIP numerical preparation
and comparison consumer isolation, then bounded actual outputs when authorized.

## CLIP numerical input boundary

The optional provider numerical adapter consumes already-admitted, whole-frame
224px RGB pixels, the exact native sample and planned RGB hash. Revalidate small
profile/source values and byte/hash bounds before importing numerical libraries.
Use pinned slow `CLIPImageProcessor` directly with resize/central crop/RGB conversion
disabled, explicit rescale/mean/std, channel-first output and NumPy return type.
No `from_pretrained`, network, model weight, encoder, diffusion, CUDA or lifecycle
operation belongs to this function. The existing manifest already specifies this
processing; no new wire schema or worker command is introduced.

Return a frozen internal record of source/profile/RGB hash and immutable little-
endian float32 NCHW bytes/hash. Exactly one bounded1x3x224x224 numerical batch is
an explicit encoder-input materialization, not another canonical image, Artifact
or cross-service blob. A later encoder boundary converts it for its model device;
metadata/results carry pointers and trace hashes only. This does not validate
scientific geometry, independent source permission or learned style improvement.

Dominant operation is one bounded linear CPU raster pass: O(224*224*3) time/space,
one source lookup and one hash, no DB/index/cache/queue or global model state.
Reject source/profile/plan hash, unavailable or mismatched versions, unexpected
processor dtype/shape and nonfinite output before returning. No fallback to latest
processor, fast preprocessing, changed normalization or automatic retry. The
pure alternative of writing our own CLIP normalization would duplicate the public
library's rounding/layout behavior; using its pinned slow processor is smaller
and independently checked against the explicit arithmetic in a real lab smoke.

NumPy2.4.6 already exists and is pinned by the isolated trainer; declare that same
version as an optional provider `sdxl-ip-style` extra because this adapter validates
the public processor array and emits canonical float32 bytes. No new package is
installed and core/production dependency requirements remain unchanged when the
optional extra is unused. Torch/Transformers/Pillow are existing numerical runtime
dependencies. Unit fakes in the light test environment are not pinned processing
acceptance; actual11.3.0/4.56.2/2.4.6 CPU execution must be reported separately.

### Numerical implementation checkpoint — 2026-10-06 16:27 UTC

Light-environment regression PASS:326 cases including23 new numerical-input
cases; a separate214-case sweep covers the older image tests restored to the
authoritative environment manifest. The first regression had325 PASS/one failure:
manifest completeness exposed12 previously omitted direct image-runtime test
modules plus this new module. Restore the sorted13 entries, do not weaken the
completeness guard. The two final sweeps are disjoint; the23 new cases are a subset
of326 and must not be counted again. No GPU or real encoder weights in either.

Strict Python3.11 mypy, Ruff/format, shell syntax and diff checks PASS. The exact
optional Transformers import uses only an import-not-found annotation because
the light test environment intentionally has no Transformers/Torch; this is not
a global type-check relaxation or package installation. Pillow12.3.0 test units
mock the pinned version and public processor; they do not prove lab11.3.0/4.56.2
execution. The next real CPU smoke imports built non-editable wheels, repeats
normalization of the two already-selected TRAIN PNGs, checks exact independent
arithmetic and inversion, and forbids network/CUDA. No embedding/quality claim.

### Actual CPU numerical checkpoint — 2026-10-06 16:28 UTC

Built source `b3c52872984b2a1a9b9d3021e5ad67e119746532` then passed the
repository-free pinned-wheel CPU smoke using actual Pillow11.3.0, Transformers
4.56.2 and NumPy2.4.6. Exactly the earlier two TRAIN selections were reused: source
PNG hash/document/group and224px RGB hashes match the frozen canonical selection.
Two pixel preparations/four normalizations (two per source), exact float32
arithmetic and byte-for-byte replay PASS. Shape1x3x224x224, immutable602112byte
buffers, inverse error at most0.000030517578125 in0–255 units;7436/7316 mid-gray
pixels remain in the two inputs. This verifies normalization, not preservation of
fine features lost during the earlier224px resizing, learned embedding, geometry
or institution-grade output. Original pixels/PNG and numerical buffers were not
persisted or duplicated. Network/CUDA attempts, encoder/model weight reads,
new outputs, VALIDATION/HOLDOUT and production changes all0.

All387 wheel RECORD members (296/56/35) were checked. No runtime install. Wheel
SHA-256s for contract/provider/trainer:
`ad11d7c01501238d6575ecb8573129135afa38d2bbbab46db1bca2c67ce86ab5`,
`d40bc573c593a03bd36f0d5eb6250a1290d612cff162d6873d12516473d4298f`,
`7821980a55f2246db28b396a137aa5dcca27079dcca943df1c7ebf622e97ae39`.
Build-only directory:
`/tmp/eom-image-trainer-build/b3c52872984b2a1a9b9d3021e5ad67e119746532.pfmb5Y/dist`.

The existing Orchestrator owner re-resolved the earlier canonical selection
evidence, committed four text members18,885bytes and reread all members equal as
`artifact_5e138eb71d684c748a1b8994b31e499e` /
`rev_dc60a851848b4c07a155b5db3fd9bfc5`, primary
`reports/clip-numerical-input.json`, SHA
`0d3c8241d923dd4002437fc99c90fa9b603ca35b382a3ae37cc671842c483ae4`.
The CPU operator, exact result/log and owner operator are retained; source PNGs
continue to reference their earlier canonical revisions. No worker plan/model
was registered, acquired, loaded or dispatched. Overall quality NOT_ACCEPTED,
independent review NOT_PERFORMED, goal ACTIVE; old fallback budget12/12 remains
exhausted and separate model-acquisition/four-output approval NOT_RECORDED.

No additional own-view coverage is claimed in this numerical checkpoint: the
unchanged source/224px pairs were already viewed and compared. At the next new
output/prompt/control/style candidate, reopen institutional originals alongside
matched outputs and record line economy, tone/hatching, frame/composition and
scientific semantics separately. Do not let repeated views of unchanged sheets
inflate coverage or stand in for independent blind/HOLDOUT review. Next safe
implementation boundary is comparison consumer OFF/ON state isolation and exact
encoder-load ownership, before bounded actual inference when authorized.
