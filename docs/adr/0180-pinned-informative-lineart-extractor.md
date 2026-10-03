# ADR 0180: Pinned learned lineart extraction for the SDXL diagnostic

Status: accepted design; initial manifest contract only, not an installed extractor.
Date: 2026-10-03 UTC.

## Evidence and decision

The SDXL pilot and matched LoRA evaluation retain their rejected quality verdicts. Their
`FIT_GRAYSCALE_INVERT_832X512/1.0` preprocessing converts gray surfaces as well as lines. It is
not the learned contour extractor in the upstream adapter example. Do not rewrite that policy,
rerun an old identity with new semantics, or attribute every defect to conditioning.

The original author's
[MIT-labelled Space](https://huggingface.co/spaces/carolineec/informativedrawings/blob/bd4b4299be505803e036203a39c02024b4cfee11/README.md)
provides the actual extractor weights. At pinned Space revision
`bd4b4299be505803e036203a39c02024b4cfee11`, `model.pth` is 17,173,511 bytes with SHA-256
`c686ced2a666b4850b4bb6ccf0748031c3eda9f822de73a34b8979970d90f0c6`. The Hub metadata for
`lllyasviel/Annotators` revision `982e7edaec38759d914a963c48c4726685de7d96` lists exactly
that SHA and length for `sk_model.pth`. The coarse counterparts also match
(`30a534781061f34e83bb9406b4335da4ff2616c95d22a585c1245aa8363e74e0`), but are not selected
for this first experiment. Byte equality is a provenance observation, not model-quality evidence.
Use the author's pinned distribution and attribution, not the aggregate mirror's `other` label.

The pinned author's `app.py` raw SHA is
`4e989aff7a9f4491e9bf463dff0b7c35f84b52b34a0bf4ca918b525fa7d593d0`; README raw SHA is
`7cb79f3b0f9354c7f47a1ab56b09c0e3bd6c8d96243555be5e28ea79d6e6c8a7`.
The architecture is a 3-input/1-output InstanceNorm generator with three residual blocks and
sigmoid output. We will port this small numerical architecture, with MIT attribution. No remote
Python, Gradio app, hub inference endpoint, or `controlnet_aux` download-on-call is executed.

## Responsibility and canonical source

The existing acquisition/installation owner may fetch the approved public model. It must verify
the pinned upstream length/hash before restricted `torch.load(..., map_location='cpu',
weights_only=True)`, reject unexpected keys, shapes, dtypes and non-finite tensors, and produce
one local safetensors revision. The original `.pth` is untrusted acquisition input, never a
worker-readable runtime file. Installed derived bytes and their manifest, not a path or a Hub
`main` branch, identify the extractor. This is a non-training preprocessing component within the
approved internal SDXL comparison; it neither expands corpus permissions nor replaces LoRA.

Only the Orchestrator resolves approved corpus pointers, stages local inputs and commits validated
results to NAS. The isolated provider implements numerical extraction. Contracts remain pure and
do not import Torch, Pillow, filesystem, SQLAlchemy, subprocess or network code.

## Identities, pointers and resolution

`imgextractor -> imgextractorrev -> manifest -> four local file hashes` separates logical identity,
revision and manifest SHA. The additive `local-image-informative-lineart-manifest/1.0` and pointer
pin this relationship. The file set is exactly `LICENSE`, `config.json`, `model.safetensors` and
`upstream.json`. Runtime model roots stay protected and read-only; executable and pickle files are
not admitted. Before resolution, validate exact revision, schema, permission, evaluation-only
lifecycle, member size/hash, config/architecture, canonical manifest and tensor membership.
Missing, stale, unsafe or mismatched targets fail explicitly; no implicit latest or weight fallback.

The manifest does not prove that acquisition, numerical validation, corpus admission or image
quality succeeded. Those are separate application/runtime gates. Merely matching a safetensors
filename is not sufficient; actual tensor/architecture checks remain required before inference.

## Access patterns, scale and concurrency

This is one immutable model revision and at most six indexed diagnostic inputs. Keyed file lookup
uses a dict; exact file-set membership uses a set; source/result order is a tuple sorted by case ID.
Manifest validation is O(files) time/space, with four files and a 32 MiB weight ceiling. Image/tensor
work is bounded by the declared dimensions and model architecture, never a corpus-wide scan.
No DB schema/index, registry, queue, persistent cache or new daemon is needed.

Installation validates in an exclusive staging directory before publishing an immutable revision.
Execution will reuse the existing offline worker identity, GPU lease, privileged staging adapter
and terminal receipt/replay pattern. It will use a new extraction command/result identity; the old
SDXL command/result and gray-inversion receipt bytes stay unchanged. A subsequent SDXL comparison
must explicitly pin the extraction result and original case identity instead of disguising derived
PNGs as original approved crop members.

## Failure, retry and deployment boundaries

Acquisition failures do not publish an installed model. Terminal numerical failures preserve their
receipt/partial output and are not relabelled as success. A receipt replay validates all recorded
bytes without re-inference. Unknown execution state is queried, not resubmitted with a new key.
No operating model binding, Pack, policy, service dependency or automatic activation changes here.
Rollback of this optional evaluation component is to stop its unit and retain the existing V6.

The simpler alternative is another strength sweep on grayscale inversion. The existing 0.0,
0.35 and 0.8 controls already expose defects; that alternative does not test the upstream learned
lineart input distribution. Importing the entire upstream app or silently changing policy 1.0
would weaken isolation/reproducibility and add unnecessary dependencies.

## Follow-up gates

1. Pure JSON Schema/Pydantic manifest, identity, sorted membership, bounds and old-schema regression.
2. Restricted acquisition/conversion and exact architecture tests before installation/inference.
3. Additive extraction command/result, original TRAIN admission and replay tests before dispatch.
4. Inspect six raw lineart outputs, then compare bounded matched SDXL inputs; retain rejected images.
5. Separate own inspection from independent blind review and scientific correctness. A passing
   sample, low loss or successful extractor run does not permit operating activation.
