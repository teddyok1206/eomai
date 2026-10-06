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
