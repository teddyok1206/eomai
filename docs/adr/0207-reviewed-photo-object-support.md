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
PASS. No model/GPU calls, training updates or production changes. This checkpoint
adds documentation only, not a worker, mask schema or dependency installation.

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
