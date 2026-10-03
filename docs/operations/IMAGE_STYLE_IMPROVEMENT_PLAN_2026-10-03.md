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

The private Orchestrator staging/dispatch adapter now creates only exclusive pinned-run workspaces,
checks every input against the command, preserves partial handoffs and addresses a fixed offline
systemd unit. The presentation script delegates admission, staging and dispatch rather than
reimplementing crop rules. Focused handoff/admission/micro/dependency checks passed 71 tests,
including 14 new filesystem/dispatch tests; Ruff and targeted strict mypy passed. Initial test
invocation/fixture-order issues were corrected before this final run. No GPU execution is implied.

### 2026-10-03 isolated runtime and live input preflight

Candidate provider/contract wheels from `6c90270a` were installed into the existing explicit image
environment with the optional offline SDXL unit only. Wheel/installed RECORD byte verification,
actual image-identity imports, CUDA availability and `pip check` passed. The protected V6 binding
hash remained `f96eda843dbcbf9bd4ba0b22e5da7ca7e4485b00cbbfb353f8631f6028eb5845`.
No group/polkit/operating-unit/control-policy change or restart was performed. The previous exact
`fc0b78c5` provider/contract wheels remain hash-verified rollback inputs.

All six proposed references were inspected: several retain gradients, photograph-like texture,
clipped contours or original redaction marks. Approved provenance is not homogeneous line-art
quality; these distinctions must be preserved in training selection and comparison records.
Live admission found three historical pilot receipts with one canonical terminal newline. The
new resolver now accepts that existing representation without rewriting bytes or hashes; compiled
SDXL provenance remains strict canonical JSON. Extra whitespace/double-newline still fails.
The 84-test final handoff/admission/resolver/publication/micro/dependency regression passed,
with Ruff and targeted strict mypy. This preflight discovery caused zero model calls; the already
committed compiled prompt policy is retained and replayed through its same publication identity.

The first fixed-systemd dispatch failed at command-file admission, before output-directory/model
creation (19:12:51 UTC; zero generated outputs and no worker result). The new descriptor walker
incorrectly required read/list permission on traversal-only `/srv/eom` (0711). It now uses Linux
`O_PATH` for no-link ancestor traversal and opens only the actual target for bounded I/O. Ancestor
permissions, worker privilege and production binding are not expanded. The failed unit/workspace
is retained; the corrected runtime is tested before a deliberately pinned successor experiment.
The 51 probe/model/acquisition/backend tests passed, including an execute-only ancestor regression.
Ruff format/lint passed; targeted strict mypy uses the image-test interpreter with silent checking
of unchanged imports. Broader imported legacy Pillow annotations exposed existing errors and are
not represented as a whole-package mypy PASS.

### 2026-10-03 first measured SDXL diagnostic

The corrected, deliberately new run `imgsdxlproberun_8b2b08110e6462366b1346dca1284a0a`
completed all six TRAIN subjects at seeds 104729/130363: 12 model outputs, 49,799 ms overall,
8,280,481,280 bytes peak GPU allocation. Actual worker runtime was Python 3.11.15,
Torch 2.7.1+cu128, Diffusers 0.35.2, Transformers 4.56.2 and RTX 5080/CUDA 12.8.
The fixed inputs used 30 steps, guidance 7.0 and adapter scale 0.8. Production binding and
service availability were unchanged; no LoRA was loaded or trained.

Canonical command: `artifact_fd83bbb76bca49fea6401bf06094560f` /
`rev_b00fe42acc524532908bbfd6fd7f33ad`,
`manifests/sdxl-lineart-probe-command.json`, raw member SHA
`sha256:1fe831027f688dbc607535bf29e35e2c3f156024978c8955645d41936442a695`.
Command semantic SHA is
`sha256:22ad53f2868eacdbaf11c5ae844d2e99dae2ee1256202f65d5e29d03d3923f1a`.

The Orchestrator validated the terminal result against that separately pinned canonical command,
then committed the result and 30 PNG members (6 conditioning, 12 raw, 12 final) to
`artifact_0b6df6892e134d0e8839395c691dfb4d` /
`rev_c7a262df52c04925b9af8dbde00b7f5b`. Result member is
`manifests/sdxl-lineart-probe-result.json`, raw SHA
`sha256:cf1a9cd6dd45cb41a0f9ef215e41a5eedde2efeb27c8bc01d0928f5521114cd5`;
its separate semantic result SHA is
`sha256:98d4890292a7aa2d8445a7a6b7f49262bf671b000f996b494d40c06ff9e14fcc`.
An inspection invocation initially used the semantic hash as the member hash and correctly failed
closed; the corrected read-only invocation did not rewrite evidence or rerun inference.

Technical receipt/PNG integrity passed. **Our own inspection rejects all 12 for exam style**:
gray backgrounds, grid/banding, shadows, dark filled surfaces/white contours and inherited
redaction marks are visible. This is not an independent blind review or a scientific-accuracy
approval. Existing raw-canvas raster metrics measured foreground below 245 at 922–1000 milli,
border foreground at 945–1000 milli and midtone at 742–876 milli. These are descriptive measurements,
not newly invented acceptance thresholds; reference foreground was 199–333 milli and source
resolution/whitespace differ. Temporary inspection copies are not canonical training data.

The pinned [TencentARC model card](https://huggingface.co/TencentARC/t2i-adapter-lineart-sdxl-1.0/blob/5f1f33b049b96fa599f0aa3d77b31dbef5095e97/README.md)
and the [official conditioning example](https://huggingface.co/Adapter/t2iadapter/resolve/main/figs_SDXLV1.0/cond_lin.png)
confirm white contours on black. The downloaded example's actual SHA is
`d6fa8c2936da8e279e567375736a8f62c53ed48ae046f7d33e86a1b57f9e9b5f`;
the example URL is mutable, not an immutable model revision. The
[detector implementation](https://github.com/huggingface/controlnet_aux/blob/v0.0.7/src/controlnet_aux/lineart/__init__.py)
extracts a learned contour map before inversion. Our declared
`FIT_GRAYSCALE_INVERT_832X512/1.0` instead inverts the original gray surfaces. Correct polarity
does not make those two preprocessing algorithms equivalent. No polarity bug is established;
the source of the artifacts is still being isolated. Detector-weight authorization remains
separate, and no detector weights were acquired by this inspection.

Before spending training time, run only four strength controls: microscope/radio at seed 104729,
the same stack/reference/prompt/steps/guidance, adapter scale 0.0 versus 0.35. Each has an exact
new command and two outputs, using the existing schema, Orchestrator admission, exclusive
workspace, fixed unit and GPU lock. These are intentional diagnostic experiments, not failure
retries or a new acceptance cycle. The previous 0.8 evidence stays immutable and rejected.
Do not silently change the released conditioning policy to an edge detector; changed preprocessing
requires a successor contract if the evidence warrants it. The installed Diffusers adapter
constructor has no `add_watermarker` argument; the ignored keyword was removed with a regression
assertion (31 probe/backend tests, Ruff and targeted mypy passed), not a new configuration flag.

SDXL training/backend implementation, clean training selection/expanded document split,
the complete four-arm 42-output comparison, independent blind review and Item/HWPX activation
remain pending. No technical success is relabeled as quality acceptance.

### 2026-10-03 conditioning controls and numerical backend

The two controlled runs completed, without a new operating release or input-policy substitution:

| Adapter scale | Run | Result Artifact / Revision | Model outputs | Duration |
|---|---|---|---:|---:|
| 0.0 | `imgsdxlproberun_4a85f7f25f66fb0285cda3d4ab529004` | `artifact_638757f0fb5f468a883c092080594a50` / `rev_5503cac0209245399f355dce8c09d1cc` | 2 | 14,332 ms |
| 0.35 | `imgsdxlproberun_d700a9df194bba18398d04759e4fa5d0` | `artifact_65bc46ef0cef4dbfb6e053618b5cd1df` / `rev_2764f9bb4dc2433191c37ec24c1bacb8` | 2 | 13,812 ms |

Both used the same microscope/radio source, prompt, seed 104729, stack and generation settings.
Each result was independently compared to its committed command and all six PNG members before
Orchestrator publication. Own inspection rejects all four: the 0.0 images still have gray/dark
surfaces, a wrong microscope structure and radio pseudotext; 0.35 still has grid/scene additions,
heavy strokes and multiple unintended objects. Inference: the adapter's current gray-surface
conditioning is not the only source of style defects, and strength tuning alone is insufficient.
This does not prove the relative causal contribution or that LoRA will succeed. The 0.8 run's
evidence and failed first handoff remain immutable. Follow-up comparison budget used is 4/12.
Total SDXL model calls are 16; 42 stored PNG members include conditioning/raw/final variants and
must not be confused with the planned four-arm **42 generated-output** comparison, still pending.

All 16 original TRAIN source PNGs were inspected without modifying them or using reserved pixels.
They include white/gray/hatch exam imagery but also original letters/numbers, cut-off objects,
table-frame lines and existing redaction marks. The micro trial remains a bounded technical/style
direction test, not evidence of a homogeneous or expanded independent training population.

The existing numerical training backend was factored into one shared frozen-input UNet-LoRA
implementation. The released SSD wrapper keeps its actual command, bundled VAE and pinned
checkpoint load/save; the SDXL wrapper uses its actual stack, separately pinned fixed VAE,
200-step recipe and no checkpoint/implicit resume. No SSD pointer cast, copied training loop,
new framework, dependency, DB table or queue was added. Loss, gradient norm, latent and final
adapter nonfiniteness plus resource bounds fail before accepted adapter publication.
This is source implementation: the SDXL micro workspace application/CLI/handoff and actual GPU
training are still pending, and the installed trainer has not been replaced.

The final focused source run passed 87 tests, including CPU-fake accumulation/optimizer accounting,
frozen parameters, resume and failure-before-save cases, plus old trainer/micro/checkpoint/contract
and dependency regressions. The fakes are not CUDA numerical evidence. Two earlier invocations
failed the explicit image-test inventory gate while the new files/ordering were being added;
the final sorted manifest is complete. Ruff, targeted strict mypy and release-script syntax passed.
The complete non-live image-runtime suite also passed all 213 tests. The 12 bounded, sanitized
operator logs are durably archived through the Orchestrator as
`artifact_bb025e48f4d44032bcef8e13a2cbb503` /
`rev_238a506019a24c678d335bce6c776bbc`; raw log bytes are audit attachments, not new worker messages.
An initial archive invocation correctly refused group-writable temporary logs before any DB write;
only these completed task logs were made private (0600) before the successful archive. No record
or Artifact was deleted. Slack milestone `devreport_136a750f49c846c5bff6e667b7b08ae8` was delivered.

The clean source checkpoint `e0f1eea9dbc42fb3135563f3f4eb56da6f9a7b2c` built and inspected all
three release wheels from its immutable archive. This is build evidence only; none were installed:

- contract wheel SHA-256: `c0ac893af9f5e37a9c975407b91b31cd4f9dc03c94b990d583899f02fa2a57d3`;
- provider wheel SHA-256: `f40ea0d08d48d319ce31956a55b421ee3d4ab7c84ff8632192ca54cfd61e9d00`;
- trainer wheel SHA-256: `6c390e2d75c5d3bb6ea4c39a3c616527752e40786f445ff20d7970e02d0b1c2e`.

Archive location: `/tmp/eom-image-trainer-build/e0f1eea9dbc42fb3135563f3f4eb56da6f9a7b2c.TZQrmc`.
At 20:18 UTC the API, Web, Catalog/HWPX application runners and Workflow runner remained active;
GPU was idle (2 MiB allocated). No service restart, policy activation or operating trainer update
is implied by the successful build. Next implementation is the SDXL micro application and fixed
handoff/CLI, using the admitted original 16 TRAIN sources with explicit derived redactions; actual
micro training, held-out evaluation and candidate canary remain subsequent gates.

### 2026-10-03 SDXL micro application and handoff checkpoint

The SDXL micro command now has an application-owned workspace runner, a fixed
`sdxl-micro-probe` trainer entrypoint and offline `eom-image-sdxl-lora-micro-probe@.service`.
The Orchestrator reuses one complete historical source-lineage validator for diagnostic and
micro inputs, then checks all 16 original TRAIN declarations before PNG materialization. Only
command, crop-set, authorization and 16 TRAIN PNGs are staged (19 members); the four validation
and four holdout IDs remain metadata only. The same exclusive private handoff, readonly inputs,
shared GPU lock, approved-artifact publisher and fixed systemd dispatch are reused. No new queue,
DB schema, model dependency, worker privilege or activation path was introduced.

The runner checks exact source hashes/dimensions/captions, realizes declared white redactions
without modifying the originals, records separate derived pixel hashes, rejects duplicate/blank
realizations and accepts only an exact validated two-file PEFT adapter. Success requires all
200 optimizer updates, actual pinned dependencies and frozen duration/VRAM budgets. SIGTERM
produces cancellation evidence; the previous handler and GPU lock are released. Terminal replay
revalidates stored bytes and does not retrain; unreceipted intermediate outputs are not overwritten.
The unit allows the 3,600-second maximum application budget plus 60 seconds for terminalization.

Focused source/contract/old-checkpoint regressions: **137 PASS**; dependency and existing
publication regressions: **9 PASS**; full non-live image-runtime suite: **244 PASS**. Ruff,
targeted strict mypy (five changed production modules), diff whitespace and release-shell syntax
passed. The first application tests exposed a JSON-array/tuple mismatch in adapter manifest
construction; it was fixed at that boundary. Invalid synthetic identities, the test publisher
stub shape and one incorrect test-file invocation were corrected before the final run. These
failures are not GPU executions or historical result replacements. CPU stubs do not establish
actual SDXL training or quality acceptance.

Read-only installed trainer preflight reports Python 3.11.15, Torch 2.7.1+cu128, Diffusers 0.35.2,
Transformers 4.56.2, Accelerate 1.10.1, PEFT 0.17.1 and bitsandbytes 0.47.0. New wheels/unit have
not yet been installed at this source checkpoint. Next is a bounded trainer-only update with
exact rollback artifacts, followed by one independently pinned 16-TRAIN/200-step GPU micro run.
The inference environment and production V6 binding are not part of that update. Full grouped
dataset expansion, four-arm comparison, independent blind review and Item/HWPX canary remain open.

### 2026-10-03 actual SDXL micro training acceptance

The tested source `da1fde0ef5ccced19beb600396e9620258e8f1fc` was built from a clean immutable
archive at `/tmp/eom-image-trainer-build/da1fde0ef5ccced19beb600396e9620258e8f1fc.PIFUQb/dist`.
Wheel SHA-256 values are:

- image contracts: `dc01129fdfe72de8681d2115bea90a6055a4e313b4ac856f05dda51a8c0e2330`;
- provider: `7a92342344e6cb8ca562dabc260afc14fed6b991929fc4562a5247ab8a6aaa18`;
- trainer: `67508e5c7a3fd5b5056e74bf0a0186be94009a8dc1bcd7528ca871f1d996a6e8`.

Only the existing **trainer environment** and new optional offline micro unit were updated.
All wheel RECORD entries, installed member bytes, actual `eom-image` imports/CUDA and `pip check`
passed. No inference-environment install, production binding change, group/polkit change, service
restart, DB migration or model activation occurred. Exact installed-predecessor wheels from
`efa5e9bdfb253d98fb3966734a92645ed7d7f31e.oqaW1I/dist` were checked against both their archive hashes
and installed bytes before replacement. Rollback inputs remain:

- contracts: `ee4c22f1fb7015ed7a0028a6adfd6a008ca329fb31befad667ba86248f442977`;
- provider: `cfeef996af9c34adb581aec0b46295028782dd599e1e510721414f801f73219f`;
- trainer: `3d04c96b834e50b41a6cdd8f7dafcd64be284d7cff392306cc0995f4aae48294`.

The Orchestrator admitted/published/staged one new command and dispatched only
`eom-image-sdxl-lora-micro-probe@imgsdxlmicrotrainrun_2dd52d6f74119674e2fbccdd7fdef3ca.service`.
Command Artifact / Revision: `artifact_16942489d5694ebe9fb571953444cb6b` /
`rev_0f5da5f12a72485ea14e4d8b58067186`, member `manifests/sdxl-lora-micro-command.json`.
Raw command SHA: `sha256:e68a6b46243357aac0782f42ffe84b61a1e1196b73560d333c3e2d61b8869e45`;
semantic command SHA: `sha256:9f1558c83511460dabdaf3f46bd4b8a0612f675f8162dbc58de73c7db9e2c0d5`.
Its explicit masks affect five TRAIN samples (13 normalized boxes): original letters/numbers,
adjacent inset and layout-frame regions, not source PNG/caption identities. Only 16 TRAIN PNGs
were staged; the four validation/four holdout IDs did not materialize as trainer input.

The real GPU run completed **SUCCEEDED**, with all **200 optimizer updates**, **474,435 ms**
application duration, **5,704,160,768 bytes** peak Torch GPU allocation (5.312 GiB) and final
loss **0.013273741118609905**. The actual dependency/GPU fingerprint matches the command:
Python 3.11.15, Torch 2.7.1+cu128, Diffusers 0.35.2, Transformers 4.56.2, Accelerate 1.10.1,
PEFT 0.17.1, bitsandbytes 0.47.0, CUDA 12.8, RTX 5080, compute capability 12.0.
Systemd separately records successful terminalization at **2026-10-03 21:02:37 UTC**.
The pinned library's `torch_dtype` deprecation warning is not a training failure; no retry,
unreceipted-output overwrite or fabricated runtime fingerprint was required.

Before canonical publication the result was checked against its committed command, all 16
derived RGB 768x512 PNG hashes/dimensions and the exact validated PEFT file set/manifest.
Orchestrator result Artifact / Revision: `artifact_e4cca31093f1467f8742384ba404dcd4` /
`rev_02b106d8920f479e8dc7aa453d304ef2` (20 members: result, 16 derived PNGs, adapter manifest,
config and safetensors). Primary member: `manifests/sdxl-lora-micro-result.json`.
Raw result SHA: `sha256:6220ae31e36a3c263c2785ea218a5c6c7d73ae0fb6bcaf72ed1531358fea7a15`;
semantic result SHA: `sha256:86fb9d6d4824b839be897afeade1a1139fde33a1c2b5d0b4b05a204e1a8e643c`.
Adapter identity: `imgadapter_b133f7fe8b93686687afbbc46937c116` /
`imgadapterrev_87887be637f79587d932166c302e44f4`;
manifest semantic SHA: `sha256:971cb7a7b14d1259f3239a762bdb7ce81803ebcb9f996bfd3695c1fbaefb156f`.
The adapter remains **EVALUATION_ONLY / automatic activation FORBIDDEN**.

Own inspection of all five mask-affected derived samples confirms removal of the selected
letters/numbers and most frame lines, but still shows gray surfaces, existing redaction holes,
a furniture-frame fragment and small objects on large white canvases. The watch's redaction also
removes face detail. These are explicit dataset limitations, not a clean-full-dataset claim.
Low training loss is **not** evidence of morphology, composition, generation quality or educational
correctness. No post-LoRA image was generated in this training phase; the 16 earlier comparison
outputs remain rejected by own inspection. Independent blind review remains NOT_PERFORMED.

Nine sanitized build/preflight/install/handoff/journal/publication/Slack evidence attachments are
durably archived as `artifact_1c2e2ecfc4de48f3be863ab5c71955ec` /
`rev_240783417edd4306a923fe3a8b9b3519`. Slack start/completion receipts
`devreport_1e99d22e85544edabba6640e03b576a8` and `devreport_311814b3eaf1433eaa0cf6b6b2128084`
were SENT (HTTP 200); the completion report explicitly refers only to the micro training phase.
API, Web GUI, Catalog/HWPX application runners and Workflow runner remained active. GPU returned
to idle (2 MiB). The overall image-quality goal remains active.

**Next authorized work:** add the smallest additive evaluation contract that pins this accepted
SDXL adapter, its training result and exact base stack before provider loading. Keep released
inference probe 1.0 and its original prompt/reference/result semantics intact. Compare the same
compiled content-team prompts, source references, seeds and generation settings, with explicit
LoRA strength and output budget. Do not call an unpinned local adapter path a reproducible model,
silently cast it to an SSD adapter, retrain this successful micro run, or activate it from loss alone.
Expanded document/duplicate-group training data, remaining four-arm outputs, independent blind
review and passing Item Preview/HWPX canary are still required before full-goal completion.
