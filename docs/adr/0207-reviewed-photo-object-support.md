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
