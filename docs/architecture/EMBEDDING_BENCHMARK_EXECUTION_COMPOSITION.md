# Native benchmark execution composition

Status: source implementation in progress; not six-launch acceptance or a device-default change.

This closes the execution composition described in
`INCREMENTAL_EMBEDDING_GPU_RUNTIME_DESIGN.md`, without changing the released
`embedding-device-benchmark/1.0` schema or its numerical/performance thresholds.

## Boundary and data flow

The application owner must authorize the actual operator, resolve pinned Graph/policy/source
revisions, materialize the accepted input Artifact, and create a genuine structured Job. The
Catalog infrastructure handoff adapter only prepares a local execution directory. A valid
`operator_audit_id`, request hash or handoff is **not** authentication or launch admission.

Canonical source remains the registered input Artifact and its validated source pointers.
`benchmark_id`, immutable benchmark revision, Job ID, execution ID, input-set semantic hash,
invocation semantic hash and raw serialized-file hash remain distinct. The returned handoff
receipt contains small metadata, not copied source documents or a published output Artifact.

The existing request/invocation/input validators run before filesystem effects. Raw bytes are
canonical and bounded; no stale pointer is replaced by latest. Resolution of permissions,
source media/schema/lifecycle and Artifact bytes belongs to the supported application owner,
not to a root filesystem preparer or numerical worker.

## Local materialization

The fixed root is `/run/eom-incremental-embeddings/benchmark`. Installation must prepare this
protected root separately. The adapter must not create arbitrary ancestors. Execute-only
root-owned global parents prevent native users listing other executions. Ancestor traversal
uses directory `O_PATH` descriptors; only the execution-specific directory is readable under
its closed native-user/owner-group ACL. Every component is no-follow and non-writable by
other principals.

One atomic execution-directory creation is the concurrent-claim boundary. Existing or
partially prepared executions are explicit failures, not overwrite/replay permission. The
worker cannot create, replace or remove members: root owns the directories and immutable
input, and precreates the exact empty output files owned by the fixed native account.
Invocation FD ownership stays with the caller; the worker owns only its captured duplicate.
Preparation failures preserve the partial directory for explicit inspection, never broad
recursive cleanup or a second identity that disguises the failed attempt.

Primary operations are keyed execution lookup, bounded ordered output iteration and exact
set membership. A fixed tuple (4 or 16 output members), descriptor-relative file operations
and atomic `mkdir` suffice. Time is O(input bytes + path depth + member count), space is
O(input bytes + path depth); no DB/index/cache/migration or new dependency is needed.
Shared deterministic ACL/member-layout functions keep preparation and capture consistent.
This is a local infrastructure boundary, not a new cross-service JSON message.

## Remaining execution responsibilities

1. Application source authorization, real Job admission and immutable owner-request capture.
2. Six fresh fixed CPU/CUDA units in the released interleaved order, mandatory installation
   admission, exact configuration pins, Unix peer fencing and checkpoint/resource exchange.
3. Actual GPU physical lease/cgroup/cleanup and image/trainer model/cache/BUSY/crash/timeout
   gates before CUDA inference. Retained negative OS gates alone do not satisfy them.
4. Owner validation of sealed output bytes, token witnesses, numerical ranking/performance
   and all nine owner gates. Only the Orchestrator commits validated output Artifacts to NAS.

Each launch retains its own immutable outcome. Timeout is not proof of non-execution;
unknown cleanup blocks the next device launch and publication. Retrying requires supported
state reconciliation and a recorded launch decision, not truncating staged files. No worker
may authorize itself, impersonate an operator, mutate another service's DB or write NAS.

The simpler generic three-file INDEX handoff is insufficient: benchmark launches require
4/16 native-owned members, read-only per-execution ACLs and independently pinned invocation
and staged-input bytes. Reuse the existing contract and fixed runtime-profile mapping rather
than introducing a parallel queue, generic runner framework or artificial Job/Artifact.

Source tests use explicitly synthetic ownership fixtures and cannot prove root admission,
actual device timing or installed-runtime acceptance. Those remain separate opt-in gates.

## Source checkpoint — 2026-10-17

The root-only preparer, shared closed ACL/member layout and execute-only ancestor traversal
are implemented. Eight focused source suites: **526 PASS** (39.13 s); strict mypy on four
changed production modules and Ruff/format pass. Cases cover six layouts, schema/hash
closure before mutation, real concurrent mkdir uniqueness, no-clobber, private partial
failure, missing/symlink/writable/default-ACL root, and listing-denied ancestor traversal.
No released schema bytes changed; no dependency, migration or model execution was added.

`tests/integration/test_embedding_benchmark_handoff_privileged.py` is a separate opt-in
root OS test (`EOM_RUN_BENCHMARK_HANDOFF_PRIVILEGED=1`). It prepares only private `/run`
fixtures, permanently drops child UID/groups, and tests actual native-account access and
other-account denial. It does not create production Jobs/Artifacts or exercise GPU/models,
and must not be reported as six-launch numerical/performance acceptance.
