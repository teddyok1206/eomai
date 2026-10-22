# Private benchmark runtime successor candidate — 2026-10-22 UTC

Status: source-only coherent backport on
`maintenance/embedding-benchmark-budget600-20261022`. No build, prefix installation,
authentication, model execution, DB changes, deployment or GPU-default activation.

## Provenance and narrow purpose

- Exact base: `6c4cd95f709ba66756bfcbe2c4528b94cf3622ea`, the existing owner/CPU
  runtime source family. This is a separate temporary worktree; main is
  not replaced, rewound or edited by this preparation.
- Backport source: reviewed current-turn changes, now preserved in main commit
  `a4be4f528631c455060c9af10abb47585c5e9163` (previously prepared from the
  `b4c52056` working baseline). The private backport has its own Git identity;
  it is not the full main source or a published runtime release. A later wheel
  hash/RECORD and installed evidence must identify any runtime installation.
- Scope: explicit benchmark policy/request/invocation 1.1 and 600-second unit
  families; append-only closure of the actual legacy CPU1 post-start failure;
  bounded checkpoint/ACK timing diagnostics and terminal-record boundaries.
  Original model, Graph, access policy, input/token witnesses, numerical recipe,
  ordering and numerical acceptance thresholds are not changed.
- Existing-file changes are current-turn diff hunks applied to this base, not
  wholesale copies of current main modules. New protocol/model/schema mirrors,
  fixed unit templates and focused tests are additive.
- One prerequisite: the existing shared `observe_failed_gpu_unit_metadata`
  function from main's `gpu_unit_terminal_observation.py` is backported together
  with its benchmark consumer. It replaces the same older inline metadata read;
  it grants neither process cleanup nor model execution authority.
- Closed-family consumers include effective GPU-policy readback, native CPU
  capacity/cgroup checks and native host OOM observation. Their backports select
  only the reviewed 180/600 families. Normal INDEX/QUERY limits remain unchanged.
- The worker explicitly accepts CUDA's already sealed READY capture once through
  `begin_worker_execution()`, instead of re-entering its existing context manager.
  Ordinary re-entry remains invalid; the original CPU/CUDA leaf bytes are unchanged.
  The final 1.1 READY file-source pin is
  `4bc5d315e3f4ec25c49fd11feeac0132bdb88f0354cc2d562bf6f6c2e97c69f9`;
  the released 1.0 READY pin is preserved, not rewritten.
- One focused private test checks that the out-of-scope native CUDA INDEX resource
  API remains absent, instead of calling main's unrelated newer INDEX entrypoint.

## Frozen numerical identity

The three implementation files retain the original raw bytes:

| Component | Relative source | SHA-256 |
|---|---|---|
| FLOAT32_CODEC | `packages/catalog_contracts/eom_catalog_contracts/embedding_vector_binary.py` | `3487cae0e2f21dbe2f95c58a278c083a181bea2255f023e00e53484ee2ebdb79` |
| HOST_L2 | `services/catalog_service/eom_catalog_service/inference_transfer_vectors.py` | `440d7406db48cc7cf18e423033294b7f8a36b155833eea1eec50b935811490c5` |
| OFFLINE_ENCODER | `services/catalog_service/eom_catalog_service/embedding_offline_backend.py` | `f667e54da9ebf74312ef4d93b6c8f44760c49bb6012dc00b9b47799ff54f500b` |

Current main's generalized registered-review ranking module has different raw
bytes. Copying the full main wheel into a native prefix would therefore change
the admitted numerical identity and is not this candidate's installation plan.

Likewise, only the two new schema-registry entries are backported; unrelated
mixed/registered-review resources and native CUDA INDEX APIs are not copied.
The existing released 1.0 schema, legacy numerical entrypoints and legacy
180-second unit bytes stay unchanged.

## Validation and later installation boundary

Use the explicit `eom-api` Conda interpreter with this worktree's source roots,
not an ambient interpreter or main's source tree. Focused pure tests must cover
policy/version rejection, fixed unit/FD ownership, old/new frame deadlines,
post-start root proof and append-only application semantics, and diagnostic
ordering. Record skipped privileged or database gates honestly; main's distinct
runtime tests are not automatically evidence for this private source candidate.

Even with identical numerical files, changing platform code changes the whole
prefix inventory. A later installation needs an immutable candidate wheel,
verified RECORD, successor prefix/config/inventory and fresh protected native
admission receipts. Never modify an admitted prefix under its old receipt or
reuse main's successful source tests as installation/benchmark performance PASS.

No new queue, registry, framework, dependency or external API is introduced.
Application transactions, current Identity/source admission and explicit failure
predecessor guards remain authoritative. Parsed observations and larger resource
budgets do not authorize retry, bypass active-work guards or extend sessions.

## Observed source gates for this private candidate

- Ruff formatter and lint: all 64 changed Python files PASS.
- Mypy: all 42 changed core Python files PASS (`--follow-imports=silent`).
- Focused pure unit cohort: 716 PASS in 109.62 seconds, covering budget/schema,
  admission, closed unit/FD/CUDA fences, failure contracts/application/root proof,
  progress/ACK timing, OOM, native entry/channel/files, worker, capacity and GPU
  policy parsing. All machine, root and model assertions in these unit fixtures
  remain synthetic; no numerical inference is performed.
- Independent package schema inventory, no source-relative loader fallback and
  unknown-schema rejection: 3 PASS in 2.91 seconds. No wheel is built by this gate.
- Final READY source-pin and CUDA budget-fence checks: 73 PASS in 18.73 seconds,
  after matching the 1.1 pin to the final worker-files source. The legacy READY
  pin remains unchanged.
- Frozen numerical files and old 1.0 schema/CPU-CUDA leaf/four original unit bytes:
  unchanged from the exact base; whitespace/diff checks PASS.
- Private candidate build, installed/native admission, real privileged DAC,
  disposable PostgreSQL concurrency and actual model/GPU comparison:
  NOT_RUN_FOR_THIS_PRIVATE_CANDIDATE. Distinct main-tree evidence is not promoted
  into these statuses automatically.
