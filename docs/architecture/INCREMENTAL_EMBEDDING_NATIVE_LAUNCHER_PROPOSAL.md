# Protected native embedding factory and launcher — proposal

2026-10-12 UTC. **DESIGN_ONLY / NOT_INSTALLED / NOT_ADMITTED / NOT_ACTIVE**.
This note changes no code, schema, unit, ACL, identity, database or runtime. It proposes the
smallest installed composition of the existing native leaves. Historical CPU experiment files,
account, model manifests, environment, unit hashes and results remain unchanged. The actual
same-input CPU/CUDA benchmark and, if superior with all gates passing, CUDA default activation
remain required outcomes, not conclusions of this note.

## Eleven-item boundary

1. **Responsibility/boundary.** Orchestrator owns protected materialization, fixed-unit launch,
   command/capacity fencing, result validation and Artifact publication. A native worker factory
   composes one released configuration, configured bundle, installed observer and existing
   offline backend. It neither selects a device from availability nor establishes source,
   operator, service, Job or command authority. Index purpose `LOCAL_EMBEDDING` and benchmark
   purpose `LOCAL_EMBEDDING_DEVICE_BENCHMARK` have distinct admission and transports.
2. **Canonical source.** Retain the one root-owned payload under `/opt/eom/embedding-models`,
   exact archived wheels, protected successor prefixes and independently accepted proof/bundle
   revisions. Only small configuration and local inputs/outputs are newly materialized. Do not
   clone the old CPU site, duplicate/hardlink weights, copy source/report bodies across services,
   rewrite installed RECORD/direct-URL evidence, or execute worktree/developer Python as root.
3. **Identity/revision.** Separate logical model/payload revision, execution model revision,
   bundle/proof revisions, numerical descriptor SHA, configuration revision/raw SHA, owner Job,
   encoding key, command generation, execution ID, unit InvocationID and Artifact/member hashes.
   A path/profile is a location/choice, not identity. Full release/prefix/unit hashes are installation
   audit; unrelated platform changes do not enter the numerical-space fingerprint.
4. **Pointers/checks.** Configuration supplies exact bundle/proof pointers and fixed profile,
   not paths, executable names, roles or expected descriptors supplied by a worker. Resolve
   canonical schema/media/raw/semantic/member closure, lifecycle and permission before staging;
   separately check protected installation, runtime read-back, immutable FD/named/ancestor epochs,
   device mapping and actual lease before ML import. Reauthorize current source and caller at
   owner mutation/read boundaries. A valid proof, saved actor ID or parsed policy grants nothing.
5. **Access patterns.** Two fixed profile lookups, one exact configuration/proof/bundle lookup,
   one initial streamed byte audit followed by epoch checks, O_EXCL launch/member reservation,
   bounded ordered encoding, exact terminal unit/cgroup observation and same-key replay dominate.
   Index reservation remains the existing per-encoding Jobs boundary; overlapping `[ab]`/`[bc]`
   must not become independent batch-only computations. Benchmark is six serial launches, not
   another queue or corpus scan.
6. **Structures/indexes.** Frozen configuration/resource values, tuples for fixed member/phase
   ordering, maps/sets for exact member uniqueness, retained descriptor/epoch snapshots and existing
   Job/event/claim indexes suffice. Use one closed CPU/CUDA switch and one closed INDEX/BENCHMARK
   switch at their respective owners. No provider registry, generic dispatcher, broker daemon,
   lease table, mutable global cache, fake Codex role or binary/text DB column.
7. **Scale/cost.** Configuration ≤64 KiB; proof/bundle use existing 128/64 KiB bounds. Index
   input/output use the existing 64 MiB/row/dimension bounds. Benchmark envelope ≤64 KiB, staged
   input ≤64 MiB, output ≤16 MiB and ≤64 fixed members, as its reviewed contract eventually defines.
   Initial runtime/payload proof is streaming O(bytes+members); subsequent checks are O(members).
   Local output processing is O(rows×dimension), with bounded chunks; no repeated full wheel hash
   per row, immutable-source reparsing loop or second canonical numerical payload.
8. **Transaction/concurrency.** No SQL transaction spans inference. Actual owner admission and
   final mutation fence run in short current transactions. One native launch is active; CUDA also
   holds the shared physical lease before observer/ML through synchronized teardown. Unit exit,
   cgroup emptiness and device cleanup are additional gates: last-close flock alone proves none.
   Missing any actual shared-lock/all-entrypoint/orphan gate denies CUDA, including shadow/benchmark.
9. **Dependency/ownership.** Contracts remain IO-free. Catalog infrastructure composes its public
   bundle/observer/backend ports; Orchestrator imports supported worker entrypoints/receipts rather
   than private Catalog or image internals. Reuse/expose the existing protected handoff and fixed
   unit primitives in their owning Orchestrator module, preserving legacy wrappers/bytes. No new
   third-party dependency is required; CUDA alone installs the canonical standalone pinned
   `eom-gpu-lease` wheel. Core/API do not acquire ML or an unconditional lease dependency.
10. **Failure/retry/idempotency.** Absent adapter/configuration/install/source/session/lease/device
    proof fails before Job creation/claim; validate again immediately before launch. Busy is WAIT,
    not CPU retry. Preserve partial O_EXCL output and launch evidence; timeout, lost command fence,
    failed owner channel or unknown cleanup is UNCERTAIN. Reconcile the original execution/key,
    reuse a validated Artifact without re-encoding, and never truncate/overwrite/reset a unit.
11. **Simpler alternative.** Extending old experiment stdio or passing request models to its CPU
    factory would change immutable runtime semantics and still lack vector/QUERY transport and
    numerical proof. A broad root supervisor, SCM_RIGHTS ownership service or PID1 FD-store protocol
    is not necessary to implement the CPU leaf and is not silently assumed for CUDA. The fixed
    direct worker is smaller; CUDA remains unavailable until its separate failure-cleanup and
    all-physical-entrypoint gate is concretely implemented and independently accepted.

## Existing public source seams and actual limits

| Source/public seam | Reuse and limit |
| --- | --- |
| Catalog `embedding_bundle_resolver.ConfiguredEmbeddingBundle`, `resolve_configured_embedding_bundle` | Configured roots/pointer, exact small bundle and authoritative legacy payload resolver; no release/source grant and no full held-ancestor launch audit |
| Catalog `embedding_installed_runtime_observer.ConfiguredInstalledRuntimeProof`, `ProtectedInstalledEmbeddingRuntimeObserver` | Fixed prefix/proof/archive roots, exact CPU5/CUDA20 archive/installed-member/RECORD closure, live interpreter/OS read-back; no ML, subprocess, lease acquisition, whole-prefix/ABI or sandbox proof |
| Catalog `embedding_execution_ports.InstalledEmbeddingRuntimeObserver`, `CudaEmbeddingOwnership`, `NativeEmbeddingBackend` | Supported observation/ownership/backend boundaries; ownership takes no request and only asserts actual retained ownership |
| Catalog `embedding_offline_backend.OfflineNativeEmbeddingBackend`, `observed_embedding_implementation_pins` | Lazy protected exact FP32/eager/eval backend and relevant installed code hashes; no launcher, selector, GPU acquisition, fallback or authorization |
| Catalog `embedding_native_stdio.NativeEmbeddingDescriptors`, `run_native_embedding_descriptors` | Index-only three distinct root-owned regular FDs, canonical input, binary then completion JSON; no CLI/installed factory, path selection, unit identity or process cleanup |
| Orchestrator `inference_transfer_cpu_handoff.prepare_cpu_handoff`, `materialize_cpu_output`, `fixed_owner_identity`, `validate_cpu_execution_id` | Existing root staging/O_EXCL/held ancestor FD and owner-only read pattern. Exact experiment contracts/roots/account prevent direct reuse for new requests |
| Orchestrator `inference_transfer_cpu_systemd.FixedCpuExperimentLauncher`, `CpuUnitObservation`, `cpu_resource_limits`, `require_cpu_runtime`, `inspect_cpu_unit` | Fixed template/interpreter pin, fresh-to-terminal/InvocationID and UNCERTAIN pattern; exact old units/hashes/resources are not native readiness |
| Orchestrator `worker_systemd.FixedUnitStatus`, `parse_unit_status` | Reuse public status value/parser after a strict closed-property check; current parser itself is not strict duplicate/extra-field validation or cgroup proof |
| Catalog `inference_transfer_cpu_verifier.require_cpu_identity`, `verify_installed_runtime`, `denied_file`, `denied_socket`, `verify_no_network`, `read_cpu_model_spec` | Existing identity/negative-probe pattern. Fixed historical identity/prefix/pins preclude applying its PASS to a successor; expose only a reviewed compatible primitive, not private helper imports |
| Orchestrator `inference_transfer_cpu_installation.validate_effective_policies`, `verify_polkit_scope` | Existing exact effective policy/actual subject test pattern; native policy/subjects/units need explicit separate acceptance |
| `eom_gpu_lease.acquire_shared_gpu_lease`, `SharedGpuLease.assert_valid`, `fileno`, `close` | Actual fixed existing-only read-only inode/ancestor/tmpfs validation and nonblocking mutual exclusion; no scheduling, authority, VRAM quota, process or driver cleanup |

The public modules above are explicit interfaces even where package `__init__.py` has no re-export.
Do not call their underscored functions across packages. The smallest reuse change is a supported
native branch in the existing handoff/systemd owners, with a narrow public retained root-directory/
member and installed-template check where two real transports need it. Do not copy their private
functions into benchmark modules or generalize caller-selected paths/commands. Legacy behavior and
source/hash pins require regression tests; any extraction affecting installed old bytes requires
a separately compatible release, not an assertion that legacy installation still matches.

## Fixed profiles, accounts and installation configuration

| Profile | Exact interpreter | Proposed worker identity and resource recipe |
| --- | --- | --- |
| CPU_INDEX_FP32 | `/opt/eom/conda/envs/eom-embedding-index-cpu/bin/python3.12` | `eom-embedding-index-cpu`, its own primary group, no supplementary groups; torch2.7.1+cpu |
| CUDA_INDEX_FP32 | `/opt/eom/conda/envs/eom-embedding-cuda/bin/python3.12` | `eom-embedding-cuda`, its own primary group; only the GPU unit has `SupplementaryGroups=eom-gpu-lease`; torch2.7.1+cu128 |

Both use CPython3.12.13/Linux x86_64, maximum batch4/threads4/interop1, CPUQuota400%, TasksMax64,
MemoryMax6GiB, timeout180s, maximum active launches1, core dumps0 and no restart. Index output/file
limit64MiB; benchmark total output16MiB (a per-file LimitFSIZE is not an aggregate quota).
CUDA's reserved **and independently whole-process observed** VRAM maximum is8GiB, not MemoryMax
or an enforced GPU quota. Capacity at the exact 2048-token recipe and batch1/4 is mandatory.
Neither the DTO's wider RAM/thread bounds nor an observed idle device authorizes a larger profile.

Proposed root-protected configuration location is
`/opt/eom/embedding-native-config/<configuration_id>/<configuration_revision_id>/config.json`.
The released unit/owner installation configuration pins that exact revision/raw SHA, not a mutable
latest symlink or worker-provided CLI path. Configuration is metadata without credentials; root
owns its non-writable ancestors and single-link regular file. Bundle location is proposed as
`/opt/eom/embedding-runtime-bundles/<bundle_id>/<bundle_revision_id>/bundle.json`; proof/archive
locations remain the observer's existing fixed locations. Payload root remains the one legacy root.

Before code, define one closed JSON Schema2020-12/frozen model for this small **installation** value:
schema version, configuration ID/revision, CPU_INDEX_FP32|CUDA_INDEX_FP32 profile, exact bundle
pointer, exact installed-proof pointer, numerical-runtime SHA, exact resource-profile value/SHA,
and configuration semantic SHA. Owner release separately pins raw configuration SHA, accepted
private release/full-prefix receipt and exact unit/verifier bytes. No absolute paths, executable,
module, operator ID, permission list, service grant, mutable device default or activation flag is
accepted in this value. These are proposed fields, not a registered schema or existing adapter.
Index policy and distinct benchmark policy are resolved/authorized by their owners; runtime
configuration cannot become either compute-purpose policy. Reparse values before use to reject
constructed/copied frozen model bypasses and retain strict integer-only resource serialization.

The fixed worker entrypoint gets only a validated execution ID and the profile implied by its
exact installed template/entrypoint; it cannot override config, device, batch, threads or model.
One no-argument context factory is captured from protected installation configuration. Its order:
identity/capability/environment/FD checks → configuration raw/semantic/pin checks → complete
installation admission → actual CUDA ownership/device capture if applicable → observer/proof
construction → bundle/payload resolution → `OfflineNativeEmbeddingBackend` → existing numerical
read-back → work → backend synchronized close → owner cleanup. Keep stdout/stderr quiet around
all optional library imports; do not print source text, validation dictionaries or raw exceptions.

## Generate actual evidence; do not mint expected evidence

`scripts/embedding/install_index_runtime.sh` and its reviewed stdlib snapshot helper end
INSTALLED_NOT_ADMITTED/NOT_PROBED. They retain accepted raw archives and source/prefix evidence;
they do not produce a numerical proof, grant model access or install units. Follow-up owner gates:

1. Independently admit full prefix/interpreter/Conda/ELF/GLIBC/loader/private wheel+source closure,
   immutable installed bytes and absence of editable paths/hooks/unchecked bytecode. Use only the
   exact protected interpreter with `-I -B`, and `-I -S -B` for the admitted stdlib bootstrap.
2. Derive the proof from actual accepted archive bytes, installed raw RECORD/closed additions and
   CPU OS identity; validate through existing proof models/observer, never copy planned hashes.
   Relevant installed encoder/L2/f32 implementation SHA comes from the public observation seam.
3. CUDA capture additionally requires the actual admitted physical lease and already reviewed
   device policy. An owner-only fixed bounded capture reads actual UUID/PCI/minor/model/driver/
   boot and compute capability from independently admitted OS/driver tooling, then cross-checks
   current proc/node identity. The immutable capture is not synthesized from RTX marketing name,
   advertised CUDA version or an expected descriptor. Unsupported fixed tooling fails. No Torch
   model/forward is needed for proof generation; actual backend later rechecks capability/build.
4. Construct the numerical descriptor from those independent observations and fixed recipe; create
   only small successor execution model/bundle metadata referencing the exact unchanged legacy
   payload model/upstream/file/pooling/prefix/dimension/normalization/truncation/token ceiling.
   CPU/CUDA runtime flavors and revisions remain distinct. Validate exact raw/semantic bundle
   closure with the existing resolver and preserve proof/bundle evidence no-clobber.
5. Root reviews the exact config/pointers/unit/verifier/effective policy and negative probes. A
   JSON descriptor which hashes itself or a developer-generated proof remains untrusted input
   until independently accepted. Reboot/driver/device/payload/code/ACL drift requires renewed
   owner admission; do not update an immutable revision to make stale evidence pass.

Canonical model DAC is a separate reviewed mutation: root-owned payload bytes/manifest/nlink and
legacy UID/group remain unchanged; give only the new exact worker UIDs traverse on necessary
ancestors and read on the exact admitted payload members using narrow per-UID read-only ACLs.
No default/writable ACL, broad model subtree, legacy group, `eom`, sudo, Docker or new NAS access.
Read back actual ACL/mask/modes/owners and both UIDs' deny/read probes; ACL changes affect ctime
snapshots and must precede renewed epoch admission. Do not call content/hash immutability proof of
unchanged metadata. Root package installation does not implicitly perform this DAC change.

## Index: reuse exactly three regular descriptors

Proposed `eom-embedding-index-cpu@.service` and `eom-embedding-index-cuda@.service` depend on the
fixed root native prepare unit. Owner root is proposed as
`/var/lib/eom-workflow-runner/incremental-embeddings/index/`; root handoff remains
`/run/eom-incremental-embeddings/index/<execution_id>/`. Root prepare validates the owner launch
marker, exact request/association/Job pins, approved source staging and configuration, then reserves
the directory/members once with O_EXCL, no-follow held ancestors and before/after named/FD epochs.
It does not reauthorize from an actor ID in that file. No partial handoff is repaired or overwritten.

PID1 opens `input.json` read-only as0, `result.json` write-only as1 and `vectors.f32` write-only as2
using fixed `StandardInput=file`, `StandardOutput=file`, `StandardError=file` directives before
the worker's private namespace. Input root-owned0600; outputs root-owned0640 with the owner
read group; all nlink1/distinct regular inodes/offset0, outputs empty. The fixed entrypoint saves
FD1/2, redirects ordinary Python/library stdout/stderr to null, then passes the saved descriptors
to `run_native_embedding_descriptors` with its owner-configured no-argument backend context.
FD2 is a binary channel, never a diagnostic stream. Exact effective descriptor flags are tested;
append/truncation/aliasing or changed size fails before constructing a backend.

Keep the handoff and owner workspace inaccessible by pathname in the worker. It receives no
directory handle, Artifact ID chooser, source report, NAS/DB URI or permission DTO. The public
leaf writes binary before JSON completion; owner verifies both held/named identities and exact
request/result/shard/binary closure after terminal process/cgroup checks. Existing Artifact store
publishes the validated file set; shared per-encoding row receipts do not change original Job
allocations. A valid local result is neither a committed Artifact nor authority to register it.

## Benchmark: separate bounded owner session, not three-FD index behavior

The [benchmark proposal](INCREMENTAL_EMBEDDING_DEVICE_BENCHMARK_PROPOSAL.md) and currently evolving
contract source are not frozen installed transport. Its exact worker invocation field proposal
binds benchmark/revision/Job/execution, launch ordinal/device, owner-request SHA, fixed local input
raw pin, input-set/family/runtime(bundle/proof/descriptor/DOCUMENT+QUERY spaces), recipe and
numerical resource policy. It contains no actor/Graph/source grants, executable or path.

Keep the already proposed `eom-embedding-benchmark-cpu@.service` and
`eom-embedding-benchmark-cuda@.service`, separate benchmark prepare/handoff aliases under
`/run/eom-incremental-embeddings/benchmark/`. Root-staged descriptor/input reads and diagnostics
remain isolated: proposed stdin0 is the root-owned0600 canonical worker-invocation regular FD;
the exact `benchmark-inputs.json` alias is separately root-staged, single-link/read-only and
readable only through the selected new UID's narrow read/traverse ACL in its own immutable input
directory. No request path overrides that alias. Retain/read/hash both under no-follow ancestor/
member epochs before model construction. Benchmark may expose this one local input/output subtree,
not the index or another execution's handoff. Stdout/stderr remain null outside the explicit owner
protocol channel. The transport must be explicitly schema-first: one per-launch authenticated
owner connection, bounded length/canonical JSON frames, deadlines/backpressure and exact peer
UID/PID/starttime/unit InvocationID/cgroup association. The current chat transport's one
EOF-delimited message per direction cannot be reused for 21 messages by changing a flag.

A minimal proposed owner channel is one fixed per-execution AF_UNIX endpoint under a separate
protected native-control root, exposed only to that worker UID; other owner/systemd/DB sockets
stay denied. It is an owner transport, not worker-to-worker communication or a command service.
Opening it cannot grant compute: parent must validate exact freshly admitted launch and worker
peer before sending continuation. Its finite checkpoint/ACK state table is exactly COLD_READY1,
then QUERY_PREPARED2/4/…/20 with no vector/span and QUERY_READY3/5/…/21. Each ACK binds execution/
invocation/sequence/phase/query/checkpoint SHA. Non-first cold children have only phase1; first
CPU ordinal1/CUDA ordinal2 retain their one model instance. No extra phase/repetition is accepted.

Output layout/FD construction remains a proposal gate, not fabricated existing functionality.
Use the benchmark contract's closed member recipe, never worker-selected paths. The proposed
minimal layout is a root-protected per-execution output directory: root prepare preallocates its
exact members O_EXCL, empty/nlink1/regular, owned by the selected native UID with the owner's read
GID and0640 mode. Grant the native UID only traversal/read of that protected directory, not name
creation/removal/rename; the worker opens each fixed existing member once, write-only/no-follow/
no-append, requiring its empty initial epoch. Unit write access is restricted to those local
members. This is an explicit local-output boundary, not NAS or another worker's workspace.
Owner retains/validates directory/member FDs, type/owner/GID/mode/nlink/epochs/offset/size/raw hash
and closure, rejects missing/extra members and enforces aggregate limits before reading. It does
not weaken the index's root-owned three-FD rule. Final benchmark schema/member decision and
exact output UID/read-DAC verification precede implementation.

The currently evolving closed aliases are `cold-documents.f32`, `query-1-1.f32` through
`query-2-5.f32`, one `supplementary-documents.f32` and `token-witness.json`, `timings.json`,
`resources.json`, `worker-result.json`. Cold/query members are fsynced and closed before their
matching checkpoint; supplementary synthetic/warm/capacity ranges close only at final completion.
Checkpoint FD/raw/shape proof retains epochs, and final proof rejects subsequent mutation.
The proposal bounds the two first-cold file sets at16 members each and four cold-only sets at4
each (≤48 total, below64). Each per-launch binary file set is published once; top-level evidence
references it rather than copying canonical vectors. This list is not a claim that unfrozen
benchmark contracts or a worker currently implement that output layout.

Owner starts the cold wall clock before admission/staging and stops it after validating COLD_READY,
before ACK, not at final exit (which would include warm/query/capacity). For each QUERY_PREPARED,
start E2E timing **before** fresh actual query/candidate authorization, then ACK; validate genuine
QUERY vector, rank against immutable same-device cold DOCUMENT rows, stop E2E before QUERY_READY
ACK. Revocation/lost session/command fence sends no continuation. Missing fresh owner authority
makes the purpose unavailable; saved operator ID/permission SHA cannot resume it. Checkpoints
are provisional until complete output and unit/cgroup/device cleanup; they release no capacity
and publish no Artifact. Existing performance thresholds and predeclared workload stay unchanged.

## Effective sandbox and physical GPU lifecycle admission

Reuse old unit restrictions: non-root exact UID/GID, NoNewPrivileges, empty effective/bounding/
ambient capabilities, private network/tmp, ProtectSystem=strict/ProtectHome, protected kernel/
control groups, AF_UNIX only, no core dumps/restart. CPU PrivateDevices=yes and empty
CUDA_VISIBLE_DEVICES; CUDA alone PrivateDevices=no/DevicePolicy=closed and exact admitted
`/dev/nvidia0`, `/dev/nvidiactl`, `/dev/nvidia-uvm`, `/dev/nvidia-uvm-tools` rw allowances.
Read-only exact runtime/model/config/proof/archive mounts; deny NAS, repository/EOMIS, `/etc/eom`,
root auth, old CPU workspace/runtime, API runtime, other worker homes/image models, Docker,
PostgreSQL, D-Bus and systemd control sockets. Benchmark's one owner endpoint is the sole explicit
new IPC exception, not visibility of an entire owner workspace. No dynamic/transient unit or drop-in.

Before ML: assert worker UID/primary/supplementary groups, NoNewPrivs and CapEff/CapBnd/CapAmb0;
verify actual character-node owner/mode/rdev/named identity and DAC open in this effective unit;
require exact current UUID→cuda:0 mapping (`CUDA_VISIBLE_DEVICES` pinned UUID, one visible device),
driver/boot/PCI/minor capture, `CUBLAS_WORKSPACE_CONFIG=:4096:8`, physical lock and current device
idle/orphan state. Read allowed/denied device nodes without pixels/model data and close probe FDs.
Do not grant video/render/legacy groups to make an unexplained denial disappear. Complete-prefix/
ABI, numerical observer, backend read-back and sandbox checks are separate, cumulative gates.

The native CUDA GPU-using leaf is one process and must not fork/exec a GPU child/daemon; numerical
threads are not an exception allowing GPU descendants. The actual `SharedGpuLease` and current
device mapping implement `CudaEmbeddingOwnership.assert_owned`; check before observer construction,
before/after model/encoding/synchronization and output. Backend `close` does not close the owner's
lease. Use KillMode=control-group, bounded stop grace/SIGKILL and exact unit InvocationID+ControlGroup
and process-start witnesses. Final checks require MainPID0, no remaining process/descendant in the
admitted cgroup and bounded independent whole-process/whole-device capture with no unknown consumer
or unreclaimed former invocation. PIDs alone are reusable; final fixed-unit status alone is insufficient.

**Unresolved failure boundary:** a killed process's last-close can release flock before independently
observed driver cleanup. The approved lease API does not retain an FD in PID1 or another owner,
and this note does not assert otherwise. All physical entrypoints must perform the same failclosed
post-acquire/pre-ML idle/unknown-PID/device-epoch check, while the official owner preserves uncertain
launch/capacity evidence and blocks re-entry pending supported cleanup. If that cannot establish
no residual device consumer, use CPU and keep CUDA unavailable. A retained-OFD handoff/PID1 store
would be a separately reviewed privilege/lifecycle extension, not a shortcut proof; local systemd
documentation explicitly warns FD-store lifetime depends on unit retention/GC. No such extension
is installed or approved here.

Actual migration must inventory/drain **every** provider/trainer/direct operator GPU entry, active/
uncertain unit, descendant and legacy inode holder; verify no mixed active lock policy and install
the exact canonical standalone lease wheel/units/config/device gate as one compatible set. Preserve
legacy0700/0600 branch/history for rollback, but forbid its active coexistence with sharedGPU0.
Bidirectional provider/trainer/native contention, SIGTERM/SIGKILL/timeout/owner loss, residual child,
node/UUID/boot/driver/inode drift and image canary tests are required. Neither source lease tests,
image packaging preflight nor this note constitutes that live migration gate.

## Exact next owner paths and ordered gates

Proposed paths for review, not an authorization to edit them now:

| Owner/purpose | Minimal next source paths |
| --- | --- |
| Installation value, protocol first | `schemas/knowledge/embedding-native-runtime-config-v1.schema.json`; `packages/catalog_contracts/eom_catalog_contracts/resources/knowledge/embedding-native-runtime-config-v1.schema.json`; `packages/catalog_contracts/eom_catalog_contracts/embedding_native_runtime_config.py`; additive public registry/export and focused schema/frozen/canonical closure tests |
| Protected worker composition | New Catalog `embedding_native_factory.py` and fixed `embedding_native_entrypoint.py`; reuse public bundle/observer/backend/stdio. Separate `embedding_device_benchmark_stdio.py` only after benchmark schema/member freeze; narrowly supported token/synchronization/resource seams stay backend-owned |
| Protected materialization | Extend existing Orchestrator `inference_transfer_cpu_handoff.py` with explicit native branch/public compatible primitives, preserving legacy functions/defaults; new `embedding_device_benchmark_handoff.py` only for its different session/member contract |
| Fixed launch/readiness | Extend existing Orchestrator `inference_transfer_cpu_systemd.py` with explicit native profiles/public exact template/status primitives, preserving old names/hash/defaults; new Catalog `embedding_native_verifier.py`, Orchestrator `embedding_native_installation.py` and `embedding_device_benchmark_systemd.py`. Owner still uses existing command/Job/resource application ports |
| Exact installed policy | Under `infra/systemd/`: `eom-embedding-index-cpu@.service`, `eom-embedding-index-cuda@.service`, `eom-embedding-benchmark-cpu@.service`, `eom-embedding-benchmark-cuda@.service`, `eom-embedding-native-index-prepare@.service`, `eom-embedding-native-benchmark-prepare@.service`; additive narrow native StartUnit rule in `infra/polkit/50-eom-worker-units.rules` only after privilege review. No blanket stop/restart/clean/transient-unit authority |
| Source/synthetic gates | Proposed `tests/unit/test_embedding_native_runtime_config.py`, `test_embedding_native_factory.py`, `test_embedding_native_entrypoint.py`, `test_embedding_native_handoff.py`, `test_embedding_native_systemd.py`, `test_embedding_native_verifier.py`, `test_embedding_device_benchmark_session.py`; historical CPU handoff/systemd/stdio/verifier AST/hash/default behavior regression; no model/real GPU/root/DB fixtures |
| Actual opt-in gates | Independently admitted disposable/installed negative sandbox probes and fixed-unit/physical-lease lifecycle/image regression; fresh source/IAM/command fences, mandatory benchmark, GPU-default policy/index/query read-back and CPU rollback |

Root approved freezing the direct single-process proposal plus mandatory shared-lease/pre-ML
idle-orphan/post-exit reconciliation boundary. It is design approval only; root must review the
protected reuse seam and actual CUDA cleanup/all-entrypoint implementation before behavior or
admission. Prepared tests include no ML construction before malformed/aliased/mutable FD,
untrusted config/proof/runtime or missing lease; no stdout/stderr leak; no writable namespace/source
imports/unchecked bytecode; timeout after partial output without second inference; exact native
purpose unavailable before claim; all 21 phase/ACK mismatch/EOF/backpressure/revocation cases; stale
session/command generation and source revocation; cgroup/PID reuse/orphan and raw-vs-semantic drift.
New status/tool subprocess collection is bounded **during** selector reads with fixed deadlines
and stderr null, not `capture_output=True` followed by a length check; old launcher code remains
historical until its own compatible review. Strict property/member closure precedes public parsing.
Source tests must not be labeled installed/device/privilege/database PASS. This note ran no tests
of newly proposed behavior, since it implements none.

The accepted outcome remains: actual same-input CPU/CUDA cold/warm/QUERY/ranking/capacity evidence;
if CUDA is superior and every authority/isolation/cleanup/image gate passes, activate and read back
the released CUDA default, compatible CUDA-only index/QUERY family and rollback. Otherwise retain
CPU with exact reasons. A factory proposal, prefix installation or performance verdict alone is
not completion, and background-service admission remains separately unavailable.
