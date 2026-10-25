# GPU-preferred embedding: live acceptance ledger

As of2026-10-25 18:26 UTC. **GOAL=ACTIVE; completion is not proven.**
This small ledger preserves the whole approved scope while background catch-up
continues. Source tests, installed composition and actual execution are separate
evidence. It is not a new runtime registry or permission grant.

## Operating checkpoint, not final completion

| Component | Actual selected release |
|---|---|
| API/platform/contracts | `07ec7b32105ca4c0e80973ec734418fd12840f76` |
| Web | `06b5d0e92aa96bd105762a6465d73b0e113b80dc`; API/Web source/DTO bytes unchanged |
| Catalog completed CPU/CUDA reader | reader configuration3, SDK07 |
| INDEX metadata owner | `07ec7b32105ca4c0e80973ec734418fd12840f76`; eight targets, metadata MemoryMax2GiB |
| Root GPU controller | `04e36bbe248695a6200f7f114c83b4eb347a3536`, actual entrypoint/declared controller agree |
| INDEX invocation | `297d8b3dfb30417bafdee3869b630a09`, PID453623, running |
| Public/mixed/private QUERY | SDK07, **CPU default**, invocation `11b5bc86df9545fc88b44c70f2f2d4d5` |
| Qualified CPU/CUDA numerical SDK | `eae2c0d3`, unchanged |
| Unselected QUERY3 candidate | owner/provider07, controller04; previous3db candidate preserved, not selected |
| Migration | `20261019_0058`; no new migration |

Production source checkpoint is `07ec7b32`; this is **not** GPU goal completion.
Actual API wheel SHA is `46d5371724a73e8d0ce0daf93bd02096ac8d2318315c5128dfcb8520728ff745`.
The immutable owner SDK has its separately pinned wheel bytes; same package version
or source does not conflate the two wheel identities. **GPU completion commit and final
operating release set: NOT_SET.** README cleanup `4e9c962e` is not repeated.

## Requirement-by-requirement status

| Requirement | Evidence and remaining boundary |
|---|---|
| Schema-first device policy, exact spaces and finite carriers | Source implementation/tests recorded in the [design](../architecture/EMBEDDING_GPU_PREFERRED_BATCH_EXECUTION.md); released predecessor semantics preserved. Not itself live activation. |
| GPU incremental DOCUMENT execution | Actual CUDA children completed for CONTENT/CONCRETE/METADATA. First three numerical cohorts have8 rows each. Full corpus still incomplete. |
| Bounded model lifetime | Actual finite native invocation and the installed single-backend-scope implementation support the DOCUMENT cohort; no direct model-construction counter was measured. Multi-child QUERY reuse remains live-pending. |
| GPU return | Those three exact numerical invocations succeeded and have canonical retirement receipts; process0/retainedFD0. This is per-cohort closure, not a claim that no newer GPU job is running. |
| Full CPU/CUDA per-view pair closure | **PENDING**: require the same complete source/profile/input-hash targets through the actual source owner, not equal counts or a smaller intersection. |
| Continuous CPU standby coverage | The actual blocker was64 producers owned by an original CPU unit timed out on October19. Recovery3 officially closed only that expired original Workflow/native/producers as FAILED, preserving508 earlier SUCCEEDED commands and the failed unit. Current revision CPU CONCRETE work is queued again. Successor producer/completed exact-space coverage is still pending. |
| Finite multi-item GPU QUERY | **PENDING**: actual authenticated request3, ordered child completion, original pins and result reads after pair readiness. |
| Resource-only CPU fallback | **PENDING live**: actual shared-kernel pre-init BUSY, exact CPU pair, no fallback on authority/hash/unknown execution. Source tests alone do not close it. |
| Original request/device replay | Original replay source/PG evidence preserved. Candidate07 has installed no-forward composition PASS43.839s with actual API07; no authentication/model/claim/selection. Live routed default/replay is still pending. |
| Image coexistence and release | **PENDING live**. Original independent `IMAGE_TRAINER_REGRESSION=NOT_RUN` is preserved; a synthetic mutex probe must not be labeled a real image/training run. |
| Throughput | Historical CPU/CUDA comparison stays unchanged. Measure finite QUERY/cohort behavior separately from end-to-end source/registration overhead; no new service speedup is claimed. |
| GPU default, rollback and compatible installed set | **PENDING**. Candidate/backups/preflight exist, but actual default selection, read-back and supported rollback still need live verification. |
| Git/docs/Slack | Source fixes and evidence pushed. Milestone report `devreport_5555af57a3984798b16e4ec263dd39a7` SENT; final completion report remains pending. |

## Reusable live DOCUMENT evidence

The following exact Workflows were COMPLETED in the16:02 read-only observation;
their immutable successful history was not rewritten. An older16-row unpublished
failure is excluded, retained FAILED and officially reconciled separately.

| View | Workflow | Successful numerical invocation | Retirement SHA-256 |
|---|---|---|---|
| CONTENT | `workflow_0c62b08fde184af6bb29340e611688e9` | `66af304ffd7e4f7ca1e4e850159b9405` | `e2409ae956cfcedf7ab2dbe248cd8a90a5177be0bec126efeb00916fa1742f23` |
| CONCRETE | `workflow_63cf9d0bafb64e66a28e504efa2a0b1c` | `47061cc4195b43e4b125df1ea7376ec4` | `b8535f17c270a54c58a137a3f59c42d24a6321c5dc3c710cb3671253938385be` |
| METADATA | `workflow_a219c2a9ffe8443fb0ec154edbffd383` | `122f8f43cc6b49f48e614c8a3a3bd3ad` | `4feb7b08e62597c7e6c1309265b08a076d0ce74e0cc7840f6ae76496143f9928` |

Each corresponding local numerical binary was32768 bytes:8×1024 FLOAT32 values.
Input-grant-to-result file timestamps were approximately126.52s/125.85s/118.01s.
These include actual source-fence/control/serialization work; **they are not
isolated model-forward or warm-GPU timings**. No second model invocation was
submitted merely to collect this evidence.

Read-only evidence: `/tmp/eom-current-index-phase-20261025-1550.json` and
`/tmp/eom-current-index-phase-20261025-1602.json`, status EXIT0. Current numerical
retirement files remain under `/opt/eom/embedding-gpu-batch-lifetimes/` using the
exact original unit/invocation. Detailed source/installed evidence and rollback
candidate locations are in [routed execution](../architecture/REFERENCE_QUERY_ROUTED_EXECUTION.md).

The15:47 technical audit showed mixed CPU521/457/521 versus CUDA57/157/24 for
CONTENT/CONCRETE/METADATA. These stale-as-of counts are explicitly not the current
canonical pair result. Current INDEX work was confirmed live at16:02; do not
restart it because an observation or a monitoring interval ends.

## CPU blocker and installed successor evidence

- Source `07ec7b32`: unit203 PASS; strict mypy8 production modules; scoped
  Ruff/format; guarded disposable PG r70:53 PASS and cleanup EXIT0.
- PG r71:68 PASS and cleanup EXIT0, including concurrent unbound terminal failure
  replay and late-evidence transaction rollback in all three existing plan families.
  These overlapping suites are not summed into an invented independent total.
- Actual original CPU Workflow `workflow_1b68f2babfcb4d90a6344644f41f1d50`, native
  Job `job_ced5f8ad3d7a4bd0a79e2e792f46416d`: officially FAILED at17:49:27,
  exact replay PASS,64 producer failures,508 prior successful commands unchanged.
  Proof/schema-owner authority and original unit identity were checked, not supplied
  by an operator-shaped DTO. No original failed result became success.
- INDEX invocation `6e792…` drained naturally with exit0. Current-revision CPU
  waiters owned no producer and held no live command lease; their pinned historical
  rows were preserved, not overwritten or labeled successful.
- First new metadata invocation `987b13…` subsequently failed because the rollout
  advanced the controller entrypoint while declaring controller04. The channel
  correctly refused it. Original failed root/retirement and unbound parent
  `job_bb2f11b8234d4573ab1f77cb28ff7b2d` were preserved; the existing Orchestrator
  planning-failure operation closed that parent FAILED with exact replay, not a
  replacement allocation or Workflow. Evidence Artifact
  `artifact_91fc7f90fdcb4ded90b5eff2c9a3d493` /
  `rev_a0065b1e23b345d08e07d7812fa60082`, `root-failure.json`, SHA
  `d129e42863eab366453e6fd1b57363083fd3d9deb6c68bfe50219ccd5ed9e4bc`.
- After restoring the declared controller's exact environment, INDEX invocation
  `297d8b…` completed actual CUDA CONCRETE Workflow
  `workflow_40ee6e6a9ccd42a890a59fdfebb9309b` and8 producers. Its root invocation
  `4937516fd5d545979356fba72d6f1ca3` succeeded/retired with process0/FD0; another
  METADATA cohort was genuinely executing in the18:22 observation.
  Original numerical invocation `d3eeba4afb3c418d80982da1585eb65e`, retirement
  raw SHA `1e7ac30ce91186b33220825ae37fd41da517459a07384e8b94c99f932f3b79ed`.
  The binary is32768 bytes, not a new model/recipe or a claim of warm-only timing.
- HTTPS ready and receiver/read-back PASS after correction. Original failed
  read-back/startup/operator logs remain separate; initial service start is not
  itself sustained runtime acceptance. QUERY remains CPU; no new Studio login,
  password reset or credential-file change occurred.

Small evidence: `/tmp/eom-cpu-failure-index-finish-20261025-r2.log`,
`/tmp/eom-cpu-successor-controller-correction-20261025-r1.log`,
`/tmp/eom-cpu-successor-unbound-plan-record-20261025-r1.log`,
`/tmp/eom-cpu-failure-release-readback-20261025-r2.log`,
`/tmp/eom-current-index-phase-20261025-1820.json`, status EXIT0, and
`/tmp/eom-routed-query-07-candidate-preflight-20261025-r1.log`, EXIT0.
Durable invariant/operation rationale: [CPU failure recovery](../architecture/NATIVE_CPU_INDEX_FAILURE_RECOVERY.md).

The18:25 read-only technical audit (`/tmp/eom-current-index-pair-metadata-20261025-r8.json`,
EXIT0) reports mixed CPU521/457/521 and CUDA81/165/40, versus legacy ALL
CPU520/457/520 and CUDA73/157/40 in CONTENT/CONCRETE/METADATA order. These are
explicitly **partial counts, not exact canonical pair validation**. No smaller
intersection is accepted as completion. The CPU CONCRETE successor Workflow
`workflow_30d9d547127e4907ac64888d2032f95a` is REQUESTED, not completed; the
ordinary current service queue must execute it. Source profiles/eligibility and
binding counts retain their distinct meanings.

Candidate07 installed no-forward preflight:43.839s PASS, actual UID990/GID1000,
groups0/caps0, public+mixed routed factories and unchanged private CPU factory.
No operator capture, source query, numerical work, claim, activation or selection
occurred. The actual active INDEX and CPU QUERY configuration bytes were fenced
before/after. This replaces neither full pair nor authenticated live canary gates.

### Separate observation, not an additional GPU implementation stream

The ordinary expiry-maintenance service has intermittently restarted when its
automatic Codex capability observation tries to resolve a canonical verification
report beneath NAS, which that specialized unit intentionally cannot read.
The relevant admission/processor/unit source files are unchanged between06 and07;
predeployment occurrence was not established. API, primary Runner, Catalog, QUERY
and INDEX remain separate. A momentarily active unit does **not** prove this
maintenance path healthy. No NAS permission was broadened, no prior model proof
was trusted for another account, and no unrelated source fix was slipped into the
GPU work. Record this real observation for the following system review; do not
claim whole-system stability or let it replace the GPU acceptance gates.

## Next boundary

Let the confirmed current catch-up invocation run, with milestone-based reporting
and bounded metadata observations. Do not add unrelated code or repeatedly ask
for human authentication while pair readiness is incomplete. On readiness, use
one fresh actual Studio session for the existing authenticated acceptance path;
never simulate login or extend authentication age.

Only after every live-pending row is proved, record the completion commit and
actual compatible operating release, then inspect the user's post-checkpoint
12-candidate/4-check static review. That external document remains unopened.
