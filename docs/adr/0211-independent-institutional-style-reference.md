# ADR0211: Separate institutional style reference from object geometry

Status: CPU capability probes and pure preparation contract, 2026-10-06 UTC.
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
values, not ambient defaults. Numerical preprocessing is still unimplemented.
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
Wheel build/import simulation remains pending at this source checkpoint.
The initial `python -m build` availability probe failed in the test environment;
use the existing release script's explicit API `pip wheel` rather than add a
dependency or mutate either environment. No build/install side effect occurred
in that availability probe.
