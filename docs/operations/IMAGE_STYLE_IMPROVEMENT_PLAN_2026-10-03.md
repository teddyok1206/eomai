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

### 2026-10-03 matched-input SDXL LoRA evaluation source gate

The additive `local-image-sdxl-lora-evaluation-command/1.0` and result family now pin the
baseline command, accepted micro command/result/adapter-manifest Artifacts, separate logical
adapter/revision/semantic hash and explicit strength. Baseline prompts, source PNGs, seeds,
conditioning, sampler and dimensions are reused unchanged. Shared pure evidence/coverage
validation and the shared generation loop preserve the released base-only 1.0 schema bytes;
no old receipt is relabelled as a LoRA run. Metadata admission now precedes materialization so
training/source provenance can be checked without re-reading the corpus or staged PNGs.

The fixed optional offline evaluation unit uses only `eom-image-trainer`, the existing GPU
lease and root-owned read-only inputs. No new dependency, DB/index/migration, queue, inference
environment update, production binding, permission/group change or automatic activation is
included. Bounded safetensors loading verifies exact finite rank-8 UNet targets and alpha 8
through the installed public Diffusers/PEFT API. Evaluation does not add the training caption
trigger to only one arm: doing so would confound the matched prompt comparison.

Source gates: **127 focused contract/admission/handoff/replay/dependency tests PASS**,
**273 full non-live image tests PASS**, strict mypy of nine changed production modules PASS,
Ruff formatting/lint PASS, release-shell syntax and diff whitespace PASS. The twelve pure
evaluation contract tests also pass in the explicit API environment without Pillow/provider
imports. Initial fixture time/publisher shape/expected resolver exception and test inventory
invocation issues were corrected before these final gates; these are not model executions.
A read-only operator lookup used the wrong column name; its failed log was preserved and the
follow-up uses the existing typed resolver, not direct SQL. No DB row was changed.

The accepted adapter manifest member's raw SHA is
`sha256:42cb8c200f83e87a1e21155aee8742cf12f538e641e983a6f6f28572081144bb` (1,232 bytes),
distinct from its semantic SHA. Config SHA is
`sha256:bca3e61a9357e06a5ee21c3c0855375786b9a54a8124eee20953f704738b921e` (202 bytes).
Safetensors SHA is `sha256:0b4f6f511157af989fe6391c7b9ee5665d74314e5bb0138a23ff308f781300e6`
(46,607,400 bytes, 1,120 F32 tensors). The successful read-only preflight is
`/tmp/eom-sdxl-lora-eval-preflight-20261003.r2.log`; the first failed lookup log is retained.

Next: build/install the exact tested trainer-only compatible wheel set with predecessor
rollback inputs, run one bounded six-case/two-seed LoRA evaluation against the original
baseline, publish validated PNGs/receipt, then measure and inspect all twelve outputs.
This source gate is not CUDA evaluation or illustration-quality PASS. The full goal remains
active; full grouped-data expansion, four-arm acceptance, blind review and Item/HWPX canary
are not closed by this implementation.

### 2026-10-03 actual matched-input LoRA evaluation — technical PASS, own quality REJECTED

Tested source `cc2f32e76ad872147f954580a1bdca00855bc65b` built from a clean archive at
`/tmp/eom-image-trainer-build/cc2f32e76ad872147f954580a1bdca00855bc65b.q1pQyU/dist`:

- contracts wheel SHA `dea935ffe52521ab990e5fda1df9fe07b83a2db3f7be8629f73b1512b23da085`;
- provider wheel SHA `e705316d2c27c10bc95e061c3e5766523cb57274d6cfea8e08dd04e9167b40fb`;
- trainer wheel SHA `ab54190eef0585460db4cb964bd5c05fdb2781f8e5e1a342640ac280381975b2`.

Only the trainer environment and optional `eom-image-sdxl-lora-evaluation@.service` were
installed. All wheel RECORD/installed bytes, worker identity imports/CUDA, `pip check` and
unit validation passed. The predecessor three wheels at `da1fde0e...PIFUQb/dist` were checked
against their exact hashes and installed bytes and remain rollback inputs. No inference
environment, production V6 binding, groups/polkit, migration or operating service was changed.

The Orchestrator submitted **one** command for six original TRAIN depictions and seeds
104729/130363, 30 steps, guidance 7.0, T2I conditioning 0.8 and LoRA strength 1.0. Run:
`imgsdxlloraevalrun_754ffbe1373f65ec96875ad71cf6b36d`.
Command Artifact / Revision: `artifact_bfd265c836974054b8d06ab67ab9fc5c` /
`rev_716fc2b516b744c2b8915c574e72395e`, member `manifests/sdxl-lora-evaluation-command.json`.
Raw command SHA: `sha256:1f0a699dae6c38ef5a7131192ec0b30704d5f212aab0a89e564cd935f7b2ac1d`;
semantic SHA: `sha256:9a907e5beae0b1b9e7a0db89b0568d90cf2ebcfacb9e7eeabec5713e9bc03b6f`.
All 14 staged members passed admission. Neither held-out pixels nor new prompts were used.

The actual isolated GPU run returned **SUCCEEDED**, **12 outputs**, **58,428 ms**, peak Torch
allocation **8,328,740,352 bytes**, RTX 5080 / CUDA 12.8 / compute 12.0 / Python 3.11.15 /
Torch 2.7.1+cu128 / Diffusers 0.35.2 / Transformers 4.56.2. Systemd also terminalized successfully.
This is actual numerical evidence, not a CPU fake or an assertion that illustrations are good.
All six conditioning records (including byte SHA) are exactly equal to the original baseline.
The baseline result remains `artifact_0b6df6892e134d0e8839395c691dfb4d` /
`rev_c7a262df52c04925b9af8dbde00b7f5b`; no historical output was replaced.

After command/result/adapter/baseline and PNG dimension/hash checks, the Orchestrator committed
the new result plus 30 PNG members to `artifact_b8fd18412d9d44638d0ce2828ef77c2e` /
`rev_b940a28d33f04cbaa9ba6a0202034445`. Primary member:
`manifests/sdxl-lora-evaluation-result.json`.
Raw SHA: `sha256:809b5b56f50263a828329b24d5f69f8c92ac16c0f064171c6203bcc686f20cfd`;
semantic SHA: `sha256:1f6b201f0fef87cab5374f46f4dd1146f839cd0b2ed029f5bdb79abde546a0de`.
The two early publication invocations failed before writes: incomplete operator import paths,
then a transcribed wrong baseline logical ID. The typed resolver refused it. The original
publication record supplied the exact logical ID for the same pinned revision/hash; there was
no fallback to latest, data repair or extra GPU execution. Failed logs remain preserved.

Own inspection viewed **all twelve PNGs**, not a selected best seed:

| Subject (two seeds each) | Concrete own observations | Own adoption decision |
|---|---|---|
| Microscope | gray background, dark fill, extraneous vertical borders/frame-like lines | REJECTED |
| Heated vessel | gray background and shaded liquid; second seed breaks the upper vessel outline | REJECTED |
| Protective glove | grid, shading, redaction-like panels and pseudo-symbols | REJECTED |
| Radio | shadow, dense speaker textures and fabricated brand/text-like marks | REJECTED |
| Deciduous tree | gray trunk/background, bottom panel and stray vertical marks | REJECTED |
| Trilobite | gray grid and highly textured solid rendering rather than restrained exam strokes | REJECTED |

Descriptive native-canvas foreground range is 946–1000 per mille (baseline 922–1000);
mid-tone range is 836–988 (baseline 742–876); border foreground is 854–1000. These
same-resolution measurements corroborate the gray-background/tonal problem, not science
accuracy or a statistical quality score. Presentation-normalized borders are white by
construction and must not be cited as successful original-background generation.
No accepted illustration, independent blind review, educational correctness or generalization
PASS is claimed. This is TRAIN-only diagnosis with a 16-sample micro adapter, not held-out testing.

Inspection copies (explicit temporary materialization, not canonical sources) are in
`/tmp/eom-sdxl-lora-evaluation-samples-20261003`, both seeds for all six subjects. No PNG was
retouched to make the sample look successful. Ten sanitized build/read/install/handoff/journal/
publication/Slack logs are canonically archived as `artifact_646ffd5a0a8243d58dcf55ab5a91a154` /
`rev_45754e9a259e43419964823b7530c306`. Slack milestone
`devreport_f0711e634c0b4ffc88003ab674530e66` was SENT (HTTP 200), reporting technical PASS,
own quality REJECTED, no activation and whole-goal still active. Operating services remained
active and GPU returned to idle (2 MiB). Neither rejected predecessor nor new result is deleted.

**Next:** before any larger training run, separate the learned style effect from T2I gray-surface
conditioning using the existing bounded-control budget and already-pinned microscope/radio
control inputs. The baseline-strength-only controls used 4/12 follow-up outputs; the new twelve
LoRA images are the planned LoRA arm, not twelve additional controls. Reuse their original
compiled prompts, source/seed/base settings and the accepted adapter; do not silently redefine
the released conditioning policy or acquire unverified detector weights. A changed contour
preprocessing policy needs its own successor/evidence. Full grouped-data expansion, unfinished
V7/Informative Drawings arms, blind review and passing Item Preview/HWPX canary remain open.

### 2026-10-03 LoRA/no-T2I control and licensed extractor prerequisite

The existing additive evaluation path dispatched one two-output control, without changing installed
packages, the original compiled prompts, the adapter or operating V6. It pins the previously
accepted microscope/radio strength-0 baseline at seed 104729 and uses the same LoRA strength 1.0.
New run: `imgsdxlloraevalrun_2fad38bef1859690207ced1f7aee0210`.
Command Artifact / Revision: `artifact_9fc72f19b4e14061b808bfd36c9ef637` /
`rev_ebca0e0eedd246808cbaae8e8a678477`, member
`manifests/sdxl-lora-evaluation-command.json`, raw SHA
`sha256:fefc1b97791c013a5456a3995aafcc5353fd192ce18cfba46dd71d4831b5262c`, semantic command SHA
`sha256:b4fd4e810bb35d5e56dfa6d65c15b756bb3281d1731c466487d51b034e48ed14`.

The isolated unit's journal records SUCCEEDED at `2026-10-03T22:14:32.888597Z`, two outputs,
15,658 ms and peak 8,328,740,352 bytes; semantic result SHA
`sha256:1f55170e1e6dd08023b2dcfe86b2e42cc5c3fa5a762567edec326fdc5c6e9144`.
This is terminal runtime evidence, not yet canonical result publication or visual acceptance.
At the 22:37 UTC checkpoint, the direct non-interactive sudo route required authentication;
protected result-byte validation, canonical commit, sample materialization and own inspection were
pending. This did not establish that the tmux authentication route was unavailable. The publication
operator is `/tmp/eom-sdxl-lora-control0-publish-20261003.py`; it pins the existing baseline revision
and validates the full result and all seven members before Orchestrator publication. It submits
no model work. Do not regenerate these two outputs simply because observation/publication waits.

There have now been 30 actual SDXL model outputs: base 12, original strength controls 4, matched
LoRA 12 and this control 2. The last two lack own visual verdict; previous rejected images remain
rejected. Follow-up controls consume 6/12 outputs. The complete four-arm comparison, independent
blind review and activation criteria have not passed.

Primary-source research located the original author's MIT-labelled weight distribution and verified
that fine/coarse model hashes equal the two weights used by the upstream lineart detector. See
[the research addendum](../references/SCIENCE_ASSESSMENT_IMAGE_MODEL_RESEARCH_2026-10-03.md#2026-10-03-추가-확인-선화-추출-가중치의-원-배포처)
and [ADR 0180](../adr/0180-pinned-informative-lineart-extractor.md). This resolves the narrow source
provenance prerequisite through an actual author distribution; it does not imply installation,
numerical correctness or improved images.

An additive evaluation-only manifest contract now separates extractor logical/revision/manifest
identity, pins fine/style-1 upstream/license/code/weight hashes, permits only four sorted runtime
members, bounds weight/metadata sizes and forbids activation or runtime pickle/code files. JSON
Schema 2020-12 and frozen Pydantic mirrors are aligned; 36 new pure contract tests pass inside the
API environment without Torch/Pillow. The four focused contract suites total 110 PASS; the existing
image suite remains 273 PASS; new contract plus dependency-boundary checks total 42 PASS. Ruff,
targeted strict mypy, release-shell syntax and diff checks pass. These counts are separate suites,
not additive independent coverage. No weights, migration, new dependency, worker protocol or
service installation were introduced by this source gate.

Next: finish the pending control's protected publication/inspection after authentication; then
implement restricted weight conversion/tensor checks and a separately pinned learned-extraction
command/result before dispatch. Preserve original TRAIN crop/provenance admission and original
SDXL receipt semantics; do not use derived PNGs as though they were original approved crop members.

### 2026-10-03 control publication/own review and extractor source build closed

The approved `EOM:3.0` operator route completed protected publication without any inference rerun.
Control result: `artifact_6501e0cf9d6340d1a60a2170b59413a2` /
`rev_b466e4fee4994c478cb9359d06de5ef7`, member
`manifests/sdxl-lora-evaluation-result.json`, raw SHA
`sha256:61e36ec90d3fc81337a055705776fb0b927d0cdb27e085da86143817607c44f3`, semantic SHA
`sha256:1f55170e1e6dd08023b2dcfe86b2e42cc5c3fa5a762567edec326fdc5c6e9144`.
All seven result/conditioning/raw/final members, original baseline conditioning hashes and original
runtime fields passed validation. Baseline pinned raw result SHA was resolved/verified as
`sha256:84d31ae4ad6c3e54e21c07665e085bf1c81dea9811b38dc9d38c4c9bdcb9fead`; its known semantic
identity and exact Artifact/Revision were preserved.

Both actual final images and both matching original baseline images were opened at original
resolution. Own visual outcome is **REJECTED for both**, not independent blind-review acceptance:

| TRAIN subject | Main observed defects | Native foreground / midtone, milli |
|---|---|---|
| MICROSCOPE | Gray background, glossy beam/shading, implausible cropped microscope structure | LoRA 785/687; base 800/596 |
| RADIO | Extra microphone, gray panels, dense speaker texture, pseudo text/numbers, shading | LoRA 742/583; base 597/246 |

Removing T2I does not remove all style defects; this LoRA alone does not satisfy the fixed-prompt
exam-style requirement. This two-TRAIN-case control does not establish each causal contribution,
generalization, a future model's failure, or independent reviewer judgment. The training style
prefix remains absent from both matched arms; its effect was not tested here. Gray inversion,
training style distribution and prompt/trigger selection remain distinct hypotheses.

Inspectable temporary copies: `/tmp/eom-sdxl-lora-control0-samples-20261003/microscope.png` and
`/tmp/eom-sdxl-lora-control0-samples-20261003/radio.png`. They are local viewing materialization,
not canonical replacements or accepted product illustrations. All 30 actual SDXL outputs now have
own REJECTED verdicts; follow-up control use remains 6/12. No extra generation occurred during
publication, review, documentation or evidence repair.

Extractor source checkpoint `39e15a3c2412cffefc651bdf6213d977e64c5c8f` passed both provider and
trainer release builds. Common contract wheel SHA:
`1d80a26a19d5a3da1161220f9802fdfb97bcc3769218d436ca7dcd4ff770a9ef`; provider wheel SHA:
`9da47fa82c1ff4dfe36ecf4cc3e2de662aba36d285b6e8ec74fbe87ec0f87b13`; trainer wheel SHA:
`501cb4a2db8ac1f38cead020ddab3e0e28154aa5fa38b823339ba9604570979b`.
Build archives are `/tmp/eom-image-trainer-build/39e15a3c2412cffefc651bdf6213d977e64c5c8f.q7hjGu`
and `/tmp/eom-image-provider-build/39e15a3c2412cffefc651bdf6213d977e64c5c8f.H8RBJT`.
A wheel-only import/resource check used the API interpreter with the contract wheel ZIP as its
import source, verified the 2020-12 schema and confirmed Torch/Pillow and runtime source imports
were absent. None of these candidate wheels or extractor weights was installed. Existing trainer
runtime remains `cc2f32e7`, inference runtime/binding remains the previous V6.

Slack milestone deliveries were SENT/HTTP 200:
`devreport_4a62121077a54468a86c27283c770419` (source prerequisite) and
`devreport_6db4137330c74b43a65edc1de2286010` (control publication/own review).
Nine explicit sanitized evidence logs are canonically archived at
`artifact_fc82a812903349ac938449b9392cfc4b` /
`rev_db1745a05a044e5da5ea0c678dcb790f`, primary `logs/lora-no-t2i-own-review.log`.
The first evidence publication correctly rejected group-writable generated log inputs before
DB/NAS publication. Only these validated local evidence files were restricted to mode 0600; the
original failure log was preserved and included in the successful archive. No validator/source
policy was weakened, and no worker/model operation was retried to repair this operator error.

Next remains restricted extractor conversion/tensor validation and additive learned-conditioning
command/result implementation. Full-data expansion, remaining comparison arms, independent blind
review and a passing Item Preview/HWPX canary remain open. The whole image-quality goal is ACTIVE,
not complete; rejected model outputs never authorize activation.

### 2026-10-03 learned extractor acquisition and actual CPU acceptance

The source implementation now has separate restricted acquisition, public pinned HTTP and
offline exact-revision resolution responsibilities. The CLI delegates these rules; there is no
new queue, database schema, daemon or dependency. The existing manifest schema bytes and old
gray-inversion policy are unchanged. See ADR 0180 for the boundary and packaged MIT notice.

An actual acquisition in the explicit `eom-image-trainer` environment fetched and verified the
author's pinned README, architecture source and 17,173,511-byte weight. Restricted CPU loading
converted 24 F32 tensors / 4,290,945 parameters to 17,165,948-byte safetensors. Every tensor and
the synthetic before/after CPU forward were bit-identical. Seven real numerical acceptance tests
passed; a separate one-test CPU-construction gate also passed under a non-CPU default-device
context. Wrong shape/key/dtype/device/layout/non-finite tensors and corrupt inputs were rejected.
CUDA initialization was guarded against; no actual exam-image extraction, GPU generation,
training, HWPX render or production configuration change occurred in this phase.

Source gates: final focused contract/runtime/dependency/old-SDXL regression **166 PASS**, complete
isolated image unit gate **318 PASS**, strict type checker six production/CLI files PASS,
formatter/linter/shell syntax/diff checks PASS. These suites overlap and must not be added as one
unique-test total. Normal API-side collection skips the eight real numerical tests without the
explicit opt-in; it does not import Torch/Pillow or fetch public model files.

Acquisition materialization: `/tmp/eom-informative-lineart-acquisition.an987FIa/model`.
Extractor logical ID `imgextractor_1de9b4ea4cbdd167a6ba88f0b45f91d3`; immutable revision
`imgextractorrev_93c4e6202a52e2d5a76f33f517b05e62`; semantic manifest SHA
`sha256:aa2ad3750048e0ab118fad3353b98d6811dc2b26db01379bd5b85cf63fa6b62d`; derived weight SHA
`sha256:597e257afa95df3e989460590d62a7c6ba487c2b7afd63cf10145712a043963c`.
This is staging, not a protected installed model or an inference receipt. The original `.pth` was
not written into the model directory; remote executable source was not executed or retained there.

The focused source gate initially exposed a new factory's UTC string/hash normalization error;
it was fixed at canonical construction, not by weakening the manifest validator. Later, a broader
regression invocation omitted the identifiers package source path and failed collection. Its log
is retained separately; the corrected full-source invocation passed. Developer test failures do
not reinterpret historical runtime failures, and neither issue required service changes.

Next: build and verify this immutable candidate, archive exact model/evidence through the existing
Orchestrator publisher, then add the extraction command/result and original TRAIN admission before
dispatching six learned-contour inputs. Do not make derived PNGs impersonate original approved
crops. The previous 30 rejected SDXL images remain rejected; independent blind review, full-data
expansion, remaining comparisons and quality-passing Item Preview/HWPX remain open. Goal ACTIVE.

### 2026-10-03 acquisition candidate build and canonical evidence closed

Implementation source `9045b7e3ab290e09f689fe89ace7f474709b37ba` passed both immutable release
builds. Common contract wheel SHA
`2d8b050d84a0716da23b9994e5e1f48373192872be9b43d310cd97d63247b6cd`; provider wheel SHA
`f0ec003b8f9f803f2dd56049a2a0287e39a68613cbf6d98440fa68f02b10989f`; trainer wheel SHA
`60c9feed87dcb4106da5b2531ece579882a11ffd482a69f4a213c6de08aa287f`.
Build roots: `/tmp/eom-image-provider-build/9045b7e3ab290e09f689fe89ace7f474709b37ba.ubb2DY`
and `/tmp/eom-image-trainer-build/9045b7e3ab290e09f689fe89ace7f474709b37ba.JDXsCQ`.

A wheel-only check outside the repository verified all three wheel hashes and every RECORD
entry, imported the new model/contract code from the wheel ZIPs, resolved the packaged MIT
notice and loaded actual converted weights for a finite bounded synthetic CPU forward. It did
not install wheels, access corpus images, acquire CUDA, call network inference or change an
operating binding. This additional synthetic check is not a generated exam-image sample.

The existing Orchestrator `ControlFileSetPublisher` committed the primary typed extractor
manifest, its four exact model members and ten sanitized logs (including the source-path
collection failure) as **15 members** to:

- Artifact `artifact_a588ec0385d148eea65bd37163fc6113`;
- Revision `rev_f0946b1223654ac9bb321232462a67c6`;
- Primary `manifests/informative-lineart-manifest.json`;
- Primary raw SHA `sha256:0106db12c5ad95a520213c10eadbfcf92b6ae1c11f1da932850a48f5ad2953e9`;
- Extractor semantic manifest SHA remains
  `sha256:aa2ad3750048e0ab118fad3353b98d6811dc2b26db01379bd5b85cf63fa6b62d`.

Opaque model-member format tags are governed by that primary manifest's exact `ModelFile`
records and numerical acceptance, not presented as JSON worker-message schema validation.
Canonical publication used the existing resumable application boundary; no worker wrote NAS,
no binary entered PostgreSQL or Git, no direct row update, protocol rewrite or migration occurred.
The approved `EOM:3.0` route was verified and succeeded without another password request.

Slack checkpoint `devreport_70dc8d3659794d3b8268ed39fb89959e` was SENT / HTTP 200 at
2026-10-03T23:44:43.867538Z. Read-only checks found the five real API/Web/Catalog/HWPX/Workflow
services active. V6 production configuration raw SHA is still
`f96eda843dbcbf9bd4ba0b22e5da7ca7e4485b00cbbfb353f8631f6028eb5845`.
Installed trainer remains `cc2f32e7`, inference provider remains `67fd3190`; this new candidate
and extractor are **NOT INSTALLED**. Acquisition/CPU source gates are closed, but corpus
extraction/admission, matched image quality, full-data/independent review and product canary
remain open. The whole goal remains ACTIVE. Next: additive six-case extraction command/result.

### 2026-10-04 original-provenance learned extraction: actual six-case checkpoint

Implementation `2e5ebffe2279f6ff126626d666f796c16c38e655` adds the pure 2020-12/Pydantic
extraction command/result, original TRAIN source admission, a bounded indexed Artifact-member
batch read, the existing exclusive workspace handoff and an offline fine-generator adapter.
ADR 0181 defines the responsibilities, immutable pointers, concurrency and failure boundaries.
No new DB schema, queue, daemon, dependency, worker privilege or implicit-latest resolution exists.
The old original-crop/gray-inversion and SDXL/LoRA contracts keep their previous meaning.

Final focused source/old-contract/dependency regression: **239 PASS**; complete isolated image
unit gate: **346 PASS**; strict types for nine production/CLI files PASS; formatter/linter,
shell syntax, systemd syntax and diff checks PASS. These overlapping suites are separate gates,
not a summed unique-test count. Initial source fixtures were rejected for group-writable file
permissions; fixtures now obey the same safe-I/O rules as the actual root-owned handoff. A wrong
backend call signature was caught by strict types before installation/GPU use and fixed at the
call site. A later regression invocation named a nonexistent test file; its failure log remains
in the evidence archive and the corrected regression passed. Validators were not weakened.

Immutable release build:
`/tmp/eom-image-trainer-build/2e5ebffe2279f6ff126626d666f796c16c38e655.Fbyllb`.
Contract wheel SHA `cae74d9807e29d59a55809b7c3e13cdc03c1d8d97b98f616d77774fc7f8b44d5`;
provider SHA `0e6cda5e17f66c6c9a93940d7d0db6a6c9793d3344ca53e0bcd2d14698c8eaf7`;
built trainer SHA `d52dd4147c8d98fc5bf6ca873787bacd1080e9df5f9056cc6ab199a43e8e958e`.
Only the contract/provider wheels were installed into the numerical trainer environment. All
wheel RECORD entries and worker-identity import/model-read/CUDA capability were checked. The
trainer distribution itself remains the earlier `cc2f32e7` wheel; the operating inference
environment remains `67fd3190`. The new trainer wheel was built, **not installed**.

The converted exact extractor revision is now installed as EVALUATION_ONLY under the existing
protected model store, with root ownership and image-group read permission. Its previously
published manifest/weight hashes are unchanged. One optional, fixed oneshot template uses the
existing image identity, offline/protected filesystem sandbox and physical GPU lease. The
operator update held that same GPU inode while checking quiescence/installing; old contract and
provider wheels from `cc2f32e7` were verified as rollback inputs. No operating services were
restarted; no Polkit/group/secret/production binding was changed.

Actual extraction command:

- Run `imglineartextractrun_abb6468621e4f0b6c0b2276da6350633`;
- Artifact `artifact_db82d6f97daa410f8f007c5952928072` /
  `rev_c7514bf952eb444fbae02ee7a628e532`;
- Primary `manifests/informative-lineart-extraction-command.json`;
- Raw SHA `sha256:4e9594c6541e17b7faeec50c9c416cb9455032456d593ad7c0d3971c68552fca`;
- Semantic command SHA
  `sha256:9c0df3e32a76671c896dd279b5a22c1f390ef87eb5e2a9dad4cabe9fa9a190ae`.

It pins the existing six-case baseline command, canonical converted extractor manifest and
original case IDs. Nine bounded inputs were staged; there was one dispatch, no reconstructed
crop registration or new SDXL/training request. At 2026-10-04T00:31:57.673420Z the installed
provider completed all six cases: **2,553 ms**, **376,991,232 peak allocated GPU bytes**.
The Orchestrator independently validated original hashes, coverage, canonical receipt,
12 PNG sizes/media/modes and exact raw/inverted conditioning pixels before committing 13 members:

- Artifact `artifact_d723b6accb4b414d9d26709806b2194f` /
  `rev_7621e6945eb847aa823b47a47d2703a9`;
- Primary `manifests/informative-lineart-extraction-result.json`;
- Raw SHA `sha256:6785d874102293acf85d95e0a4fb3e6f89601a3df6c41de613143b44ce490a3c`;
- Semantic result SHA
  `sha256:6d9a1de1459ab3bf277c716a6dd3292840f6f4fbc8aacdec1b89c09f0c0b5152`.

An actual image-worker-identity replay verified the same 12 members and unchanged receipt with
model resolution and GPU acquisition entry points deliberately denied. Model/GPU/inference
calls were zero, and Torch was not imported. This is actual installed replay evidence, not just
a source fixture. The original inference was neither resubmitted nor concealed as replay.

The primary agent inspected all six original fitted references and all six raw outputs at
832x512 resolution. Broad gray fills/shadows were reduced while keeping the original geometry.
However, **all six are REJECTED AS FINAL PUBLICATION IMAGES**: rough/broken/nonuniform contours,
dense fossil/speaker/mesh texture and source crop artifacts remain. Microscope frame separator,
tree annotations, glove label-erasure blocks and incomplete vessel contour are original-source
issues, not proof that extraction invented or corrected them. Native paired metrics corroborate
lower midtone but increased fragmented/fine detail; those metrics are not quality acceptance.
Independent blind review remains NOT_PERFORMED.

Explicit local viewing materializations are in
`/tmp/eom-informative-lineart-extraction-samples-20261004/`, with `*-reference.png` and
`*-lineart.png` for deciduous_tree, heated_vessel, microscope, protective_glove, radio and trilobite.
These are derivatives for inspection, not newly authored final exam illustrations.

The existing Orchestrator publisher archived the own-review report and eleven sanitized gate
logs as 12 evidence members at `artifact_b28307af2303498f87c9360a8d9b548e` /
`rev_bb6bce2140954114b3f57f14a6dfbca1`, primary
`reports/lineart-extraction-own-review.md`, raw SHA
`sha256:571451bd2f82281e751987bf07fdea7957a59987ef31c0c8c4d458377b6ce47e`.
This evidence publication performed no inference and did not duplicate the canonical PNG set.

Slack milestone `devreport_16ee33b9a86b4b0cbdf67399ee2c0fd6` was SENT/HTTP 200 at
2026-10-04T00:38:26Z. The five real API/Web/Catalog/HWPX/Workflow services remain active; operating
V6 raw configuration SHA is still
`f96eda843dbcbf9bd4ba0b22e5da7ca7e4485b00cbbfb353f8631f6028eb5845`.

Next: an additive comparison that explicitly pins this extraction receipt/conditioning members
and the unchanged baseline prompt/seed/model geometry. Compare learned versus old conditioning
with declared base/LoRA arms inside the remaining bounded budget. Original 30 rejected SDXL
outputs remain preserved; extraction adds **zero SDXL outputs and zero training updates**, so
follow-up control use is still 6/12. Full-data expansion, independent blind review, remaining
matched arms and a quality-passing Item Preview/HWPX canary are open. The whole goal stays ACTIVE.

### 2026-10-04 learned-conditioning BASE/LORA: actual four-output comparison

ADR 0182 and source `2e113a31cc6051fda55847fdef1a61969bda0b79` add a fixed two-arm comparison,
not a generic experiment scheduler. It pins the original six-case baseline, successful extraction
command/result and accepted LoRA training/evaluation provenance. Only two selected conditioning
PNGs and the adapter are materialized after original TRAIN lineage admission; original PNGs are
not copied into this worker. The existing indexed batch reader admits the 46.6 MB adapter with
a 64 MiB member / 128 MiB aggregate ceiling, preserving safe hash/permission/size resolution.
No DB, dependency, queue, privilege, worker-auth or production policy change is involved.

Source gates: isolated image suite **363 PASS**; focused pure contracts/admission/handoff/
compatibility **147 PASS**; dependency boundaries **6 PASS**; strict types eight changed modules
PASS; formatter/linter/shell/diff PASS. These overlapping suites are not summed unique coverage.
Initial fixture exception expectations, an adapter-strength field and explicit Pillow stub
interpreter selection were corrected before final gates, installation and any GPU dispatch.

Immutable build: `/tmp/eom-image-trainer-build/2e113a31cc6051fda55847fdef1a61969bda0b79.vDH1cV`.
Contract wheel SHA `93267b436d8e50b23e09769e95d84be08a729e5d8a81e52dfc33b1fadf7a128b`;
provider SHA `99b6ccda14000e50dd0d7c4e4cb20bd408346bd99db9a8117411e95f77ecdba0`.
Only these two wheels were installed into `eom-image-trainer` under the existing physical GPU
lock after quiescence and exact old-wheel RECORD/rollback checks. Trainer distribution still
comes from `cc2f32e7`; the new trainer wheel was built but not installed. Worker-identity import,
CUDA capability, offline fixed unit and pip checks PASS. Operating inference/V6/models unchanged.

One dispatch `imgsdxllearnedrun_40b8f423c55d449d56005ae59ea7543f` staged 13 members and generated
MICROSCOPE/RADIO x original seed 104729 x BASE/LORA = **four outputs**. Original prompt/negative,
model pins, steps/CFG/T2I strength, geometry and accepted LoRA strength stayed unchanged. A fresh
pipeline per arm avoided adapter leakage into BASE. Actual duration **24,213 ms**; peak allocated
CUDA memory **8,328,740,352 bytes**; no additional training updates or generation retries.

Command Artifact `artifact_0079711dda19493da91a0a5ce9ec4964` /
`rev_1024317bbdfc4c8e92b98fd0a5605ec1`, member `manifests/sdxl-learned-comparison-command.json`,
raw SHA `sha256:9bf333e3620e199349ea9e944fefa90dfcb39c5ea4bd6f3b18134abd130b95d4`.
Result Artifact `artifact_d6de2fc680144395bc0205fb55208004` /
`rev_129ad15be4734368a41ff2df452d5490`, member `manifests/sdxl-learned-comparison-result.json`,
raw SHA `sha256:df7580d32b6d9b37b5428ea42f2b3f934a9f4d485cb27a7d11f71fe50ba4a9ef`,
semantic SHA `sha256:2e434a403ad95782c982ce17d3f0a25aee83e223a28c7c9109cd37dc63ee0326`.
All nine receipt/raw/final members passed source/hash/PNG/mode/dimension/publication-crop checks.
Installed worker replay verified eight image members with model/GPU/adapter entry points denied,
no Torch import and zero inference. The five long-lived services stayed active; GPU returned idle.

Own inspection opened all four new finals, both original fitted references and all four old
same-seed BASE/LORA images at original resolution. All new finals are **REJECTED**: black fill
decreases and broad layout is retained better, but gray canvas/shadow, speaker/platform texture,
embossed contours and inherited source frame remain. Native 800x500 paired metrics verify reduced
dark fill but dominant midtones/border foreground. Old viewing hashes were checked against their
canonical receipts. This two-TRAIN-case observation does not establish unseen-data generalization
or independent blind-review acceptance. Actual images are not replaced with thresholded edits.

Own review and eleven sanitized logs are archived at `artifact_aa350234fb4043dd836617ec6d03b52f` /
`rev_6b24ba1ba7634f139e622bc1aa247170`, primary `reports/learned-comparison-own-review.md`,
SHA `sha256:df365c07d0508751c0f48fb2b10bde8162a89ea790c9a703d88a5c2a02127430`.
Viewing copies: `/tmp/eom-sdxl-learned-samples-20261004/{microscope,radio}-{base,lora}-104729.png`.
Slack `devreport_437729c94ccb4e37b1f7429155019798` was SENT/HTTP 200 at 01:22:39 UTC.

Upstream documents white contours on black for this lineart adapter, matching current conditioning;
do not infer or "fix" polarity just from a gray final. [Pinned primary model card](https://huggingface.co/TencentARC/t2i-adapter-lineart-sdxl-1.0/blob/5f1f33b049b96fa599f0aa3d77b31dbef5095e97/README.md).
Next: inspect the 16 actual TRAIN targets/style distribution and caption-trigger consistency
before increasing training or spending remaining outputs. Changed targets/crops/prompts require
explicit successor lineage; original pixels/receipts remain intact. Actual SDXL own verdicts are
now **34 REJECTED**; follow-up budget **10/12 consumed, 2 remaining**. Six learned-extractor outputs
remain preprocessing, not additional authored SDXL images. Full-data expansion, remaining arms,
independent blind review and a quality-passing Item Preview/HWPX canary remain open. GOAL=ACTIVE.

### 2026-10-04 actual TRAIN target audit and two-output style-prefix control

At source `01402845b65c07c50cf8543ec7c67e0d76f0b898`, the accepted command/result and
16 realized TRAIN targets were resolved by the existing indexed bounded reader. Every viewing
copy matched its canonical PNG hash; all 16 were opened at original resolution. They span
14 TRAIN documents / 13 exam groups. No VAL/HOLDOUT pixels, new copies or training updates.

White outer canvas has border foreground 0/1000, but foreground occupies only 5–35/1000 of pixels
and threshold-245 ink bounding boxes 18–151/1000 of the 768x512 target. Old preparation downscales
without enlarging small objects. Inspection also finds panel lines, annotation/white-mask residue,
incomplete crops, scientific arrows and mixed heavy-tone/fine-texture versus restrained contours.
These are preparation hypotheses, not proof of one generation root cause or rejection of every
institutional source. Preserve original images, crop approvals, masks, partitions and receipt.
A changed fit, crop, mask or caption needs explicit derivative/successor lineage.

All 16 training captions contain the style prefix; none of the six original evaluation prompts
does. A frozen control added it to BOTH BASE and LORA for the original RADIO TRAIN reference/seed
104729. Negative prompt, base/VAE/T2I pins, steps 30, CFG 7, T2I 0.8, adapter 1.0 and geometry
stay unchanged. New prompt/seed content received a new case ID, policy Artifact and baseline;
LORA pins that baseline and the old adapter. Existing contracts/Orchestrator admission, staging,
dispatch and publication suffice: no new core code, dependency, migration, queue, unit, privilege
or operating installation. Source/provider installed revisions remain honestly distinct.

Actual token counts: positive 57/57→63/63, negative 67/67 within 77/77; training captions max 21/21.
Numerical versions and generation-session/conditioning ASTs match across the two installed
environments. Focused applicable regression **108 PASS**; operator formatter/linter/compile PASS.
Early private discovery/invocation/environment mistakes were fixed before model dispatch;
they were not production incidents, authority changes or inference retries.

One BASE dispatch `imgsdxlproberun_57bef754ab3bdb310829939abc626056`: **11,590 ms**,
allocated CUDA peak 8,280,481,280 bytes. Result `artifact_aa80840456b942c5bda63cc633ac555c` /
`rev_dcb24a1016b44cafa8f84c4a47707149`, `manifests/sdxl-lineart-probe-result.json`, raw SHA
`sha256:f98ce43387c2ca47a3cea706c3ac7d81d35bc50e16ae59d2668103618f79b516`.
Only after terminal BASE success, one LORA dispatch `imgsdxlloraevalrun_a02a13fa7e13df8a39dbe267ad3c6919`:
**12,860 ms**, peak 8,328,740,352 bytes. Result `artifact_41da9770a4fa4e4cae2bdc5e158d9c93` /
`rev_2cfdb8ebbcf5499d867aecb7cd2c79f9`, `manifests/sdxl-lora-evaluation-result.json`, raw SHA
`sha256:427e4828d8f0073f5459261d550484001820ea682a6d7e0cb382f77da4c07b01`.
Each established family committed four validated members; conditioning hashes and publication
crop match. Actual worker-identity replay verified receipts/images with model entry points denied,
no Torch import and zero inference. Five services remain active, GPU idle, V6 raw binding unchanged.

Both new/old same-seed RADIO pairs were directly inspected. BASE adds an invented background grid;
LORA is close to its old gray/shadowed/textured output. Both new images are **REJECTED**.
Native BASE dark 176→258, midtone 787→707, border foreground 949→958; LORA 116→112,
879→884, 1000→1000 (per 1000). Viewing hashes were verified. Prefix correction alone does not
fix this one TRAIN case; this is not unseen-data or independent acceptance. All **36 actual SDXL
own verdicts are REJECTED**; follow-up allowance **12/12 consumed, 0 remaining**. No new training,
activation or canary. Six extractor outputs still count only as preprocessing.

Own target-by-target review, eight bounded logs, four operator sources and frozen plan are archived
as 14 evidence members at `artifact_7916bc4397d34f328389c43d02e008ae` /
`rev_c3a32f91027249128c6cbd7b2f4d5447`, primary `reports/target-and-trigger-own-review.md`, SHA
`sha256:1dbabc399b7b7dd2b3e35cbd59240832fb382d519a81444f7f90dd5506aac64b`.
No PNGs were duplicated into this archive. Viewing copies:
`/tmp/eom-sdxl-trigger-control-samples-20261004/radio-{base,lora}-104729.png`.

Next authorized development is explicit target preparation/data admission: object framing/scale,
source mark/crop repair with reviewed derivation, expression-type/caption consistency. Do not
repeat inference under the exhausted control cohort, inflate eligible counts, silently change
its meaning or replace rejected images with thresholded edits. Pin the next command/data/budget
before training. Full-data expansion, remaining arms, independent blind review and a passing
Item Preview/HWPX canary remain open. This diagnostic is PROGRESS; the whole goal stays ACTIVE.
