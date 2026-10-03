# Science examination illustration improvement plan

This plan implements the user's approved local illustration-quality goal. Reference images supply
object shape and composition; LoRA supplies examination-style strokes and restrained tones.
Scientific labels, axes, units and exact geometry remain Python/SVG/native HWPX responsibilities.
Success requires semantic accuracy as well as style, not merely passing edge-density measurements.

## Verified baseline and limits

On 2026-10-03 the readable operating binding is SSD-1B V6, hash
`sha256:c77908be126161e5a08082958ebc06af63b6f64fda11ce8154f198a90058843c`.
The checked-in V7 institutional-style configuration is a candidate, not the active baseline.
The host exposes an RTX 5080 with 16,303 MiB. GPU/NAS were unavailable in the earlier restricted
execution context and became accessible after the interruption; that earlier observation does not
establish a service outage. Model directory listing requires the existing privileged adapter.
The 06:05 UTC read-only audit resolved the approved object and raster crop sets through the existing
Orchestrator control-Artifact resolver. Schema/Pydantic, approved revision, member hashes, PNG
decode/dimensions and linked authorization/review hashes passed. Each contains 24 members
(16 train / 4 validation / 4 holdout): object line art spans 20 PDFs / 19 exam groups, raster scenes
19 PDFs / 19 exam groups. These are not hundreds of new training examples. Existing partitions stay
unchanged. The 768-candidate review has 24 object-line-art eligible entries; its diagram/raster
categories cannot simply be relabeled as object line art to reach the full-training target.
The protected model-root inventory found the SSD-1B logical model directory, not an SDXL candidate
stack. A full installed-weight audit and runtime throughput measurement remain pending.
No quality gain or blind-review PASS has yet been measured.

## Implementation order

1. Record the current binding, model revisions and reviewed crop provenance. Reuse existing
   Artifact pointers instead of copying images to Git. Keep V6 available for rollback.
2. Implement the document/duplicate-group split contract in ADR 0175. Freeze source metadata,
   internal authorization and independent holdout groups before training. Default full-experiment
   targets are 100–200 train, 24–40 validation and 32 blind-test depictions; report shortages.
3. Add additive SDXL model-stack and evaluation-command schemas before provider behavior.
   Pin base, VAE, T2I-Adapter, line detector and LoRA revisions/hashes separately. Verify lineart
   polarity from the pinned upstream implementation. Do not claim SDXL adapters work on SSD-1B.
4. Extend the existing isolated candidate provider/trainer. Use fixed local weights, offline
   inference, the current GPU lock and bounded staged inputs. No new queue or external LLM API.
5. Begin with an evaluation-only micro LoRA: rank 8, alpha 8, 200 steps, batch 1, accumulation 4,
   frozen text encoders/VAE and fp16 where supported. Validate numerics and GPU compatibility.
   Only then compare up to three full-training candidates: rank 8 with low/current LR and rank 16
   with low LR. Exact learning rates and memory bounds must be pinned before execution.
6. Run six subjects through V7 at two seeds, Informative Drawings once, SDXL+T2I base at two seeds,
   and SDXL+T2I+LoRA at two seeds: 42 proposed outputs, not outputs already produced. If structural
   fidelity fails, add a bounded ControlNet/IP-Adapter comparison of at most 12 outputs.
7. Expand to 12 diagnostic and 32 independent same-depiction blind comparisons. Use the existing
   separate presentation-packet/answer-key contracts. Record prompt/reference/model/seed hashes,
   morphology/semantic judgments, pseudotext, latency, peak VRAM and output hash.
8. Only a passing candidate proceeds to a successor single Item Preview and HWPX canary. Verify
   package-internal PNG relationships, download SHA, labels and rollback. Do not activate a model
   merely because training or rendering succeeded.

## Proposed decision criteria

Require zero unresolved critical scientific contradictions and pseudotext in accepted images.
Pilot adoption targets are at least 90% usable, mean semantic/composition score at least 4/5 and
generated-origin identification no more than 65% across 32 depictions with three independent
reviewers. These are proposed operational gates, not a statistical proof of indistinguishability.
Each rejected image remains rejected regardless of the aggregate average. Independent reviewer
availability is a human gate; automated metrics and our own inspection cannot substitute for it.

Measure resource limits against fixed-input V6/V7 runs before choosing an operational ceiling.
Training data, validation selection and blind comparison populations must not overlap by source
PDF or reviewed duplicate group. Reference-conditioned composition preservation is evaluated
separately from free generation. Follow the existing internal-use authorization scope.

## Progress and evidence

Completed source checkpoint: JSON Schema 2020-12 and frozen Pydantic split contract, bounded
union-find grouping by PDF logical identity, PDF byte hash, exam group and reviewed duplicate
cluster, deterministic assignment and propagated pinned holdout groups. Input is limited to 10,000
samples; shortages remain `INSUFFICIENT`. Canonical/packaged resources and release inclusion maps
are aligned. Focused regression suites: 83 PASS, including 30 split tests and a 10,000-member
synthetic grouping case. Ruff format/lint, targeted mypy and release-shell syntax checks PASS.
An initial broader test collection used the API environment, which has no Pillow; it was rerun in
the explicit image-test Conda environment without changing the production API dependencies.

The additive SDXL stack contract in ADR 0176 now pins base/lineart adapter/fp16-fixed VAE roles,
upstream revisions/licenses, required sorted local members and component/stack hashes. It rejects
SSD-1B substitution, pickle/executable files and incomplete component sets, and permits evaluation
only (`activation_policy=FORBIDDEN`). Thirty additional protocol tests PASS; the five related suites
now total 113 PASS. Runtime implementation and architecture/tensor verification are still pending.
The first split checkpoint `80c65cdc` also passed the normal provider/contract wheel build; no
operating environment was installed by that build.

Public upstream metadata was read on 2026-10-03, without downloading weights:

- SDXL base: `462165984030d82259a11f4367a4eed129e94a7b`;
- TencentARC lineart adapter: `5f1f33b049b96fa599f0aa3d77b31dbef5095e97`;
- fp16-fixed VAE: `207b116dae70ace3637169f1ddd2434b91b3a8cd`.

These are acquisition candidates, not installed component/weight hashes. The first bounded
diagnostic can use already-approved lineart PNGs and explicit polarity conversion. Photo-detector
weights remain subject to provenance/license verification: the hub's aggregate `other` license
does not establish the individual weight permission merely because the implementation is MIT or
Apache-2.0. This narrow prerequisite does not stop the preprocessed-lineart comparison.

Direct inspection of the approved vehicle, plant and animal members shows different rendering
grammars (gray gradients, thin botanical contours, dense hatching). The animal crop still has an
original choice marker. Approval/identity validity is not a promise of text-free, homogeneous
training pixels. Keep these originals and historical partitions immutable; record text masking or
derived crop decisions and separate expression types before training. Do not count a recrop as a
new independent source document or move an old holdout into train.

Next is the bounded experiment command/result contract and safe isolated weight staging, then
six-subject comparison. GPU training, the 42-output pilot, blind-review decisions and live
activation are pending. No dataset split Artifact has been published by this source checkpoint;
the pure split function does not resolve permissions or publish bytes itself. Important
completion/blocker milestones go to Slack; routine progress is kept here.

The technical candidates and upstream sources are recorded in
[the research document](../references/SCIENCE_ASSESSMENT_IMAGE_MODEL_RESEARCH_2026-10-03.md).
Existing institutional comparison evidence remains in
[the candidate status](../status/INSTITUTIONAL_IMAGE_STYLE_CANDIDATE_2026-10-02.md).

### 2026-10-03 isolated diagnostic checkpoint

The bounded base-only command/result and compiled-prompt provenance schemas now have an offline
provider implementation. Staged reference/command/policy hashes, dimensions, exact model membership,
architecture, prompt capacity, finite numeric outputs, measured duration/VRAM, terminal partial
failure and zero-inference replay are checked. The shared prompt-capacity rule is reused by the old
SSD-1B backend, not reimplemented as a version-specific repair. Scientific labels and geometry
remain outside the model. The optional systemd oneshot keeps the existing private identity,
GPU lock, offline network and NAS/secret/repository restrictions. No new queue or daemon exists.

The evaluation-only stack was installed into the existing protected model store with 24 pinned
members (7,266,590,927 bytes). Identity is `imgmodel_88a4de9207f4da7ab4e77de2478cd64e`,
revision `imgmodelrev_f0cf22164fb6a9171ddbcd13c88270da`, manifest
`sha256:abde5fe212767a675bf91b9d3a2e5c85a96950e186bd2b950607c8387d148280`.
These are installed hashes, not merely upstream candidates. Production binding remains V6.
This checkpoint does not mean the candidate runtime was installed or GPU inference/training ran.

Six proposed TRAIN-only diagnostic subjects are a microscope, burner/vessel, protective glove,
radio, deciduous tree and trilobite. Existing Catalog prompt policies 1.7 and 1.8.1 both fit the
two real 77-token encoders (positive 36–54, negative 63–67 tokens for these subjects). No prompt
truncation was needed, and no production prompt was changed. References still require visual
inspection before final selection, and HOLDOUT/VALIDATION stay unused for tuning.

Focused source checks at this checkpoint: 125 tests PASS (including split regression), Ruff and
targeted strict mypy PASS; shell syntax and systemd template verification PASS.
The first broader image suite overlapped a schema/fixture edit and recorded 4 failures / 179 PASS;
the final-source rerun passed all 191 tests after aligning the command's 1,800-second cap with the
1,830-second isolated timeout. This is not a GPU or operating incident.
The original corpus permission explicitly allows internal SSD-1B LoRA only. The user has been
asked to extend it to internal SDXL comparison/training. Until that reply is recorded, no approved
exam crop is submitted to SDXL and the prior permission is not reinterpreted. Sudo authentication
permits protected installation, not an implicit expansion of the corpus-use scope.

### 2026-10-03 Orchestrator admission checkpoint

The new read-only input preparation use case resolves the exact approved crop/prompt-policy
revisions through the existing Orchestrator resolver. It verifies original authorization,
inventory/review, campaign plans/results and TRAIN-only membership before materializing any PNG.
Wrong source revisions, hashes, dimensions, duplicate references/depictions and reserved partitions
fail explicitly. It returns at most eight ordered staging members; it does not dispatch a worker,
write DB rows or publish image bytes. Compiled policy/command metadata publication reuses the
existing idempotent Orchestrator publisher, not a second NAS writer or queue.

Admission and the existing resolver/publisher/corpus/split/stack/dependency/environment regressions
passed 152 tests, including the final timestamp-edge test; Ruff and targeted strict mypy passed.
This is synthetic source evidence, not a live corpus submission. The earlier diagnostic wheel also
passed 74 tests using only extracted
wheel packages, without source-path imports. The provider wheel and optional SDXL unit are not yet
installed. GPU inference, micro LoRA, expanded data, blind review and production canary remain pending.
The explicit SDXL corpus-use extension is still awaiting the user's reply; no historical approval
or existing production binding has been changed.

### 2026-10-03 SDXL scope extension

The user replied `승인할게` to the explicit internal SDXL comparison/LoRA question, recorded at
2026-10-03 18:35:22 UTC. This approves `INTERNAL_SDXL_COMPARISON` and
`INTERNAL_SDXL_LORA_TRAINING` for the same internally approved exam material. It does not authorize
raw-source export, external processing or automatic operating-model activation. The original
SSD-1B authorization stays immutable; the new scope/time/user-message hash is pinned separately in
each SDXL provenance/command. The preceding pending statements describe earlier checkpoints, not
the present approval status.

### 2026-10-03 SDXL micro protocol checkpoint

The additive micro command, adapter manifest and result families pin the SDXL stack, new corpus-use
approval, original crop revision/captions, exact 16 TRAIN members and reserved 4/4 partitions.
They record derived-pixel hashes separately and forbid operating activation. Existing object-line-art
partition validation is reused without changing released schema bytes. The three JSON Schema
2020-12 resources are mirrored in contract wheels and release verification maps.
The selected protocol/admission/split/dependency regressions passed 132 tests; Ruff format/lint,
targeted strict mypy, release-shell syntax and diff checks passed. These are synthetic source
checks only: the SDXL-specific training backend, GPU micro-training and measured quality remain
pending. No adapter or operating binding has been replaced by this checkpoint.
