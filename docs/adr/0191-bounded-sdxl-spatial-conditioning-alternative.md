# ADR 0191: One bounded spatial-conditioning alternative after failed native and cleanup probes

Date: 2026-10-04 UTC

Status: CPU input-preparation source implemented and verified; actual lab execution
pending. ControlNet model/acquisition/comparison NOT_IMPLEMENTED; no controller
weight acquired or GPU run submitted.

## Evidence and hypothesis

The three same-source T2I strengths, single negative-clause ablation and fixed CPU
cleanup are closed. Native 72/72 and derived 6/6 remain own-REJECTED. Whitening
is not sufficient: scientific contours, roots and wheel-light marks must survive.
The approved plan's step 6 already allows a bounded ControlNet/IP-Adapter fallback.
Evaluate one spatial controller first, not a combined multi-model/parameter sweep.

Candidate: `diffusers/controlnet-canny-sdxl-1.0` with the existing full SDXL base,
fp16 VAE and the same reviewed LoRA. The [official model card](https://huggingface.co/diffusers/controlnet-canny-sdxl-1.0)
declares SDXL Canny conditioning and OpenRAIL++ weights. The
[upstream file list](https://huggingface.co/diffusers/controlnet-canny-sdxl-1.0/tree/main)
offers an fp16 safetensors file; do not fetch the whole repository or either pickle
variant. Read-only revision, size/SHA and configuration pins are recorded below;
applicable controller license-text proof remains PENDING, not inferred from the
label. Diffusers code licensing is separate from weight licensing.

The [pinned Diffusers 0.35.2 implementation](https://github.com/huggingface/diffusers/blob/v0.35.2/src/diffusers/pipelines/controlnet/pipeline_controlnet_sd_xl.py)
provides the SDXL ControlNet pipeline, LoRA loader and explicit spatial-control
parameters. This establishes an implementation path, not better exam quality.
Choosing it before IP-Adapter is our hypothesis: test direct edge preservation
without adding another encoder/conditioning factor. No claim of improvement or
16GB fit is made before actual measurement.

## Required design boundary

1. Responsibility: extend the existing isolated provider's evaluation backend;
   Orchestrator remains the sole source resolver, scheduler/lease owner and
   validated Artifact publisher. No new framework, queue or operating endpoint.
2. Canonical source: the same three admitted TRAIN targets/captions, frozen
   source history, SDXL base/VAE and LoRA revisions. ControlNet is a separate
   immutable model pointer; a Canny image is a recorded derivative, not a new
   source photograph. No VALIDATION/HOLDOUT pixels in this diagnostic.
3. Identity: new model/command/result revisions, per-case conditioning hashes and
   raw/native/optional publication-output hashes. Existing T2I/cleanup history
   stays immutable and is the comparison baseline, not renamed ControlNet output.
4. Resolution: validate source authorization/split/review/schema/media/lifecycle/
   SHA before pixels or weights. Pin the controller configuration, code/version,
   license/provenance and safetensors members. Offline runtime; no implicit
   `main`, pickle/code loading, network download or latest fallback.
5. Access patterns: bounded indexed metadata batches, keyed target/model lookup,
   ordered case/seed/arm iteration and terminal replay. Reuse current admission
   and numerical pair execution where their types/semantics genuinely match.
6. Structures: frozen typed model/command/result manifests, maps/sets for coverage
   and exact members; existing GPU inode lock and exclusive private workspace.
   No DB schema/index/cache change. Do not hide ControlNet under a T2I field name.
7. Complexity/scale: first diagnostic at most three cases and BASE/LORA arms,
   six new GPU images. Source/conditioning preparation is O(total pixels); one
   batch-one numerical session per arm with explicit cleanup. Preserve the
   fallback's existing overall ceiling of 12; the unsubmitted remainder is not
   an automatic license to tune after seeing results.
8. Transaction/concurrency: one frozen six-output command and one exclusive GPU
   lease; existing Orchestrator Artifact commit/idempotency. Check quiescence and
   rollback wheels before any lab install. No production install/restart/activation.
9. Dependency direction: pure contracts first; provider owns OpenCV/Diffusers/file
   adapters and Orchestrator owns application admission/publication. Existing
   Diffusers 0.35.2, Torch 2.7.1+cu128, PEFT 0.17.1 and Pillow 11.3.0 are retained.
   OpenCV is currently absent. If Canny requires it, pin a lab-only optional
   headless package and record license/hash/reason before install. Do not add it
   to API/core or upgrade numerical dependencies implicitly. Do not substitute
   an unverified Pillow edge filter and still call it Canny.
10. Failure/retry: schema/hash/media/runtime/resource/conditioning errors fail
    closed; preserve a bounded failed prefix and exact error. Query/replay a
    possibly dispatched identity; no new seed/key, automatic retry, looser
    threshold, CPU-offload fallback or reinterpretation as a success. Old
    successful numerical execution does not make rejected quality acceptable.
11. Simpler alternative: another T2I strength/prompt/cleanup sweep is already
    closed by recorded failures. A directly recorded spatial controller tests a
    different hypothesis while reusing base/VAE/LoRA, inputs and orchestration.
    Adding IP-Adapter, a new base or retraining at the same time would confound it.

## Ordered pre-execution gates

1. Define successor model/acquisition/comparison JSON Schema 2020-12 and frozen
   Pydantic models before backend behavior. Preserve every released schema byte.
2. Freeze Canny implementation/version/parameters and source placement. Inspect
   all three conditioning images before model acquisition: leaf veins/roots,
   fan hub/grille and wheel-light marks must be present. Failure stops here;
   do not consume GPU to compensate for missing input edges.
3. Complete exact model revision/configuration/safetensors/license/resource pins
   and optional dependency decision. Use supported bounded acquisition/install
   with no base/VAE/LoRA/dataset duplication. No remote inference/credits.
4. Validate the real backend arguments/shape/polarity, stale/hash/permission
   negatives, ordered partial failure, secure staging/claim/lease and transform-
   or model-free replay. Verify wheel RECORD and actual installed worker imports.
5. Before the one GPU dispatch, freeze source/prompt/seed/scheduler/steps/guidance/
   LoRA/controller strength/guidance range and resource ceilings. Same-case
   previous T2I outputs are reused; no fresh baseline generation. Measure actual
   peak VRAM/latency; no claim of fitting the 16GB device from parameter count.
6. Commit validated results, inspect all native candidates against source and
   previous output, and judge white canvas, clean strokes, exact parts and pose
   together. Publication cleanup cannot silently repair or excuse scientific
   details. Independent blind/heldout and Item Preview/HWPX activation remain
   distinct later gates and are not opened for an own-rejected candidate.

Runtime/library research and this proposal consume no model execution budget.
The acquisition/model contract, controller license-text proof and frozen numerical
quota remain pending. The completed CPU checkpoint is documented in
[ADR 0190](0190-pinned-sdxl-publication-derivatives.md) and the
[improvement plan](../operations/IMAGE_STYLE_IMPROVEMENT_PLAN_2026-10-03.md).

## Read-only metadata pins, 2026-10-04 14:54 UTC

The official Hub metadata API resolved an immutable candidate revision. Small
configuration/model-card bytes were fetched and hashed; no safetensors, wheel,
pipeline or GPU allocation was acquired by this preflight.

- Repository: `diffusers/controlnet-canny-sdxl-1.0`.
- Revision: `eb115a19a10d14909256db740ed109532ab1483c`.
- `config.json`: 1,309 bytes, SHA-256
  `81f9bfed178f666c332892cd568a78ed8918fe08aaee994d05428a75ab44f2ca`.
- `README.md`: 3,580 bytes, SHA-256
  `78be0e56618abb9aef9a880ce74a4ba7219c97a35d9f27a2763b23475004264c`.
- `diffusion_pytorch_model.fp16.safetensors`: 2,502,139,136 bytes, upstream
  LFS SHA-256 `b2e7d3921058a442cc80430d1ec8847f42599c705e2451c95e77cf4dcf8d6c25`.
  This is an expected download hash, **not a locally verified weight**.

The pinned [model card](https://huggingface.co/diffusers/controlnet-canny-sdxl-1.0/blob/eb115a19a10d14909256db740ed109532ab1483c/README.md)
has inconsistent `base_model` front matter naming SD1.5, whereas its instructions
name SDXL. Do not use the front-matter label to select a different base. The
[pinned configuration](https://huggingface.co/diffusers/controlnet-canny-sdxl-1.0/blob/eb115a19a10d14909256db740ed109532ab1483c/config.json)
declares `ControlNetModel`, `text_time` conditioning, RGB conditioning channels 3,
latent channels 4, cross-attention dimension 2,048 and projection dimension 2,816.
These support the proposed SDXL architecture; backend compatibility still needs
an actual local test. Do not treat its `_name_or_path` as a local source path.

The upstream `openrail++` label is recorded, but a corresponding controller
license-text source must be established before acquisition. Existing pinned
SDXL base `LICENSE.md` is 14,109 bytes, SHA-256
`19b6998b569b53ac1fc2158a8a3202c8699a9a4605b47075715d9c96be7fb6d0`, from
[base revision 46216598](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/462165984030d82259a11f4367a4eed129e94a7b/LICENSE.md).
It is not silently substituted as proof of a separate controller's license.

### Optional Canny dependency decision

Candidate `opencv-python-headless==4.11.0.86`, Linux x86-64 ABI3 wheel
`opencv_python_headless-4.11.0.86-cp37-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl`,
49,969,856 bytes, PyPI SHA-256
`0e0a27c19dd1f40ddff94976cfe43066fbbe9dfbb2ec1907d66c19caef42a57b`.
Reason: use the actual Canny implementation without Qt/X11/contrib dependencies,
not an approximate Pillow filter. It stays optional and lab-only; operating
API/provider/trainer requirements do not change merely because it is a candidate.
The [versioned package documentation](https://pypi.org/project/opencv-python-headless/4.11.0.86/)
distinguishes package scripts, OpenCV and bundled third-party licenses; preserve
the wheel notices and inspect them before installation.

Actual lab NumPy is `2.4.6`. This wheel's Python 3.11 requirement is
`numpy>=1.23.5`, so its declared requirement does not force a NumPy change.
Metadata compatibility is not a tested ABI claim: actual import/Canny execution
and `pip check` are still required. No automatic numerical upgrade/downgrade or
installation of another `cv2` namespace package is permitted.

Conditioning must keep the existing geometry: grayscale source, aspect-preserving
fit inside 800×500, white centering canvas 832×512, then OpenCV Canny with thresholds
100/200, aperture 3 and `L2gradient=False`; binary white edges on black replicated
to RGB. The thresholds are the official example's initial control, not an optimal
EOM claim. Freeze a successor policy rather than relabeling the released T2I
inversion. Required source details must be inspected before GPU acquisition;
do not try several thresholds until one happens to pass.

## CPU input-preparation implementation boundary

The first implementation is only `local-image-sdxl-canny-conditioning-command/1.0` and its
result. The command pins an admitted historical target-comparison command,
frozen recipe/runtime and bounded CPU budget. Reuse that command's full source,
authorization, split and target-revision admission before materializing at most
three exact TRAIN PNGs; do not stage LoRA/base/controller weights or other targets.
This is an explicit workspace boundary, not another canonical copy of the corpus.
The result records ordered conditioning members, source pointers, sizes/hashes,
binary polarity/edge counts, runtime and zero model/training execution. It is
UNREVIEWED input preparation, never illustration acceptance or TRAIN approval.

Reuse the existing exclusive workspace and fixed systemd dispatch adapter with
a separate CPU-only template. Orchestrator remains the only Artifact publisher.
The command/result are small frozen values; outputs acquire canonical identity
through the committed Artifact and immutable revision. No database/index/cache,
runtime activation, queue or scheduler change. Bounded source/metadata maps and
ordered tuples keep preparation O(total source pixels + metadata), replay O(bytes
verified) with no Canny transform, GPU lease or model path. Partial failures retain
their ordered prefix; orphan/stale/hash/runtime failures cannot replay as success.
Publication independently reconstructs the three declared edge maps under a
separate CPU verification quota before canonical commit. Scientific detail review
is still required. A loose operator script without typed admission/receipt/replay
would not preserve the provenance needed by the later ControlNet comparison.

Source validation: 278 focused/regression cases PASS; one explicitly excluded
pre-existing Catalog infrastructure import violation remains open. Strict mypy
on nine affected core files, formatter/linter, shell and fixed systemd template
verification PASS. Earlier fixture serialization and incorrect test-invocation
failures are retained, not treated as runtime defects. These synthetic tests do
not prove actual OpenCV import/Canny behavior or retained scientific details.
The optional wheel's exact size/SHA, 97 file RECORD entries and 51 directories
have been inspected. Its MIT notice SHA is
`09d719058e782ac7bc71ba21c944e1136cde2bb957c0e888121f0218d6b5f02c`,
third-party notice SHA
`4fc3c113d53e95da0f3c433655a67067b7310e53af31eb6d280e94cc6927a363`;
OpenCV Apache-2.0 and bundled LGPL notices are preserved. This optional library
download is not controller weight acquisition; no operating dependency changed.
