# Fixed native CUDA INDEX execution

Status: **PARTIAL SOURCE IMPLEMENTATION / NOT_INSTALLED / NOT_ACTIVE / NOT_EVALUATED**.
This defines the protocol and execution boundary required by the
[original GPU goal](SYSTEM_RAG_SIMILARITY_AND_INCREMENTAL_EMBEDDING_DESIGN.md#81-cpugpu-비교와-기본-device-결정--사용자-추가-요청),
not benchmark authority or a GPU-default decision. See also the
[numerical/runtime design](INCREMENTAL_EMBEDDING_GPU_RUNTIME_DESIGN.md) and
[existing execution boundary](INCREMENTAL_EMBEDDING_EXECUTION_BOUNDARY.md).

1. **Responsibility.** A fixed CUDA INDEX leaf performs only one already admitted
   incremental DOCUMENT request. A separate fixed root lifetime adapter owns
   physical readiness, ACK and retirement. Neither grants source access, allocates
   Jobs, reads PostgreSQL/NAS, commits Artifacts or selects a device/default.
2. **Canonical source.** The existing Orchestrator owns the current admission,
   launch association, original input Artifact member and encoding reservations.
   The admitted CUDA prefix owns the numerical implementation/model; an external
   root-owned immutable entry calls its existing public `run_native_embedding_index`
   and `native_cuda_backend_scope`, without modifying or copying that prefix/model.
3. **Identity.** Preserve the original execution ID, native launch Job, association
   semantic SHA, input member raw SHA, request semantic SHA and ordered input-set
   SHA separately. The new `embedding-native-cuda-index-ready/1.0` is an untrusted
   pre-ML retention request, not an installation receipt, source grant or root ACK.
4. **Pointers/checks.** READY pins the existing configuration value, receipt raw
   SHA, expected CUDA device, PID/birth, account/groups and five resource FDs.
   The owner validates its full Workflow association against the existing input;
   the Catalog-only pure linkage validator compares that input and the small
   caller-selected identities. It does not import or reinterpret Workflow rules.
   Root must separately pin the external entry bytes/epoch, unit/env/full argv,
   prefix inventory/host mappings and actual current kernel/device/FDSTORE facts.
5. **Access pattern.** One original execution has one bounded READY lookup,
   one ACK reservation and one terminal/retirement observation. Numerical input,
   result and vector descriptors retain the existing explicit materialization
   boundaries; READY contains no text, model data, vectors or arbitrary paths.
6. **Structures.** Reuse frozen typed configuration/device/resource values and
   existing immutable effect records keyed by exact unit/invocation/phase. No
   registry, queue, cross-root authority cache, DB table or receipt family is added.
7. **Scale.** READY is canonical JSON bounded to 8 KiB; its own validation is O(1)
   bounded metadata. Linkage validates/hashes the existing bounded request once,
   O(request bytes), without duplicating its rows/encodings into another DTO.
8. **Concurrency/lifetime.** Existing admission/lease/late source fences remain.
   The leaf blocks ACK signal before shared `gpu0.lock` acquisition, asks PID1 to
   retain that same lease, emits READY with all pre-ML counters exactly zero, and
   waits. Only root's independently observed ACK permits opening GPU devices and
   model execution. Backend close and original unit termination precede retirement;
   actual empty cgroup/no GPU clients/FDSTORE and lock release precede publication.
9. **Dependency/ownership.** New Catalog contracts depend only on existing pure
   contracts/identifiers/protocol values. The Orchestrator's CUDA handoff/launcher
   supplies the real association; fixed native/root infrastructure owns effects.
   Reuse shared lease/device/map/terminal/effect-record primitives, never a
   `BenchmarkWorkerInvocation`, benchmark READY or timing-channel permission.
10. **Failure/idempotency.** Busy means the admitted WAIT policy, not CPU fallback
    or a second encoding key. Wrong hash/identity, revoked admission, uncertain ACK,
    timeout or uncertain retirement fail closed against the original invocation.
    Preserve original outcome and retained ownership; do not replay ACK/cleanup or
    publish from READY alone. Normal owner recovery remains explicit.
11. **Simpler alternative.** Calling the numerical API without this physical
    lifetime loses root ACK/retained-lease proof; reusing benchmark messages borrows
    unrelated authority. Rebuilding the sealed numerical prefix merely to add
    control framing is unnecessary: its identity checks allow an exact external
    entry under the same isolated interpreter, while the new owner must separately
    attest that entry. Existing CPU launcher/templates and released benchmark
    contracts remain unchanged. Worker behavior follows only after this contract
    is reviewed/frozen; installing/activating it requires separate operating proof.

The schema, mirrored package resource, pure readiness/linkage model and existing
Catalog schema-loader entry passed125 focused readiness/benchmark/resource tests,
strict typing on the two new Python files, Ruff/format and an independent review.
This evidence covers canonical input/result linkage and hostile metadata, not an
actual retained lease, root ACK, CUDA INDEX launch or default-device activation.

### Fixed worker entry and READY descriptor

The external immutable INDEX entry uses only libraries already in the sealed CUDA
prefix; it must not import the new READY model. Root validates its small canonical
READY body against the new schema. Its closed positional argv is INDEX, original
execution/Job/association SHA/input raw SHA, absolute monotonic expiry, configuration
ID/revision/semantic SHA/raw SHA, and receipt raw SHA. No path/backend/authority flag
or benchmark invocation is accepted.

READY uses inherited FD3, not result FD1 or vector FD2. The future fixed unit selects
`OpenFile=/run/eom-native-embedding-cuda-index/%i/ready.json:cuda-index-ready`;
installed systemd255 documentation supports OpenFile since253 and its default is
O_RDWR, not O_WRONLY. The leaf requires exactly that activation name/PID/count,
root-owned single-link empty regular0640/nonappend FD3, and makes it close-on-exec.
It writes/fsyncs canonical READY once and rechecks its epoch before device access.
Root separately pins the fixed staged file/inode/unit/entry. This source choice has
not been exercised as an actual privileged OpenFile launch.

Top-level imports are stdlib only. SIGUSR1 is blocked before identity/lease/optional
ML imports, and a fixed guarded `/dev/null` sink precedes even the existing public
identity-library import. Import failure cannot write traceback into result/vector
FDs. Any pending old ACK is denied.
The wait uses zero-time sigtimedwait plus bounded short sleeps, at most30seconds and
never beyond the original monotonic expiry. This fixed INDEX target permits at most
180seconds, not the general resource-policy upper bound. Only UID0 with a positive kernel sender
PID is accepted: the existing root effect uses systemctl kill, whose sender may be
PID1, so an invented guardian-PID pin would be incorrect. Independent root observation,
reserved ACK record and exact original unit/invocation remain mandatory. Device R/W
open and model scope occur only after ACK. Worker cleanup closes its borrowed lease
handle without unlock/store removal; root retirement remains a required next piece.

The source checkpoint now also includes `embedding_native_cuda_index_entry.py` as an
external-copyable leaf. It first preserves the root result/vector descriptors, then
permanently silences diagnostics before any EOM import; sink failure closes1/2 and
fails, including KeyboardInterrupt/SystemExit or import/preflight failure. Exact
canonical bounded FD0 is hash-checked and rewound for the existing numerical API.
Pinned receipt metadata supplies the expected device/runtime; retained lease and
PATH-only resources precede READY. Only an accepted root ACK and fresh descriptor/
receipt/resource epochs permit device R/W and the existing CUDA backend/numerical
entry. Only that standard adapter may write JSON/vectors. Local return0 is not root
retirement, Artifact publication or GPU-default activation.

Source verification:278tests across the new77leaf cases and existing READY/native
entry/backend/resource/benchmark regressions PASS9.40s; strict leaf typing, Ruff2,
formatter2 and diff checks PASS. Tests include real unprivileged child-process
zero-diagnostic failures, while FD3/root/device/model observations are synthetic.
There is no actual OpenFile, root ACK, GPU model or installed execution proof.
Fixed unit/entry admission, independent root READY/ACK/retirement and actual WAIT
capacity handling remain required before a production owner may use this leaf;
no new busy/retry/fallback protocol is implemented here.

### INDEX physical-resource observation wrappers

The existing physical observer now has three closed INDEX-only public entrypoints:
`observe_native_cuda_index_ready_resources`,
`observe_native_cuda_index_retained_resources`, and
`hold_released_native_cuda_index_resources`. READY requires the exact frozen
`NativeCudaIndexReady` type, current semantic hash and root identity, and binds only
`eom-embedding-native-cuda-index@<execution_id>.service`. Its model import is lazy;
old probe/image/benchmark paths do not require the new contract to be installed.

These wrappers reuse the existing worker/PID1 FD, FDSTORE, device-node, tmpfs and
exclusive-flock checks. They return the existing small `CudaProbeResourceObservation`
physical value, not a probe status, installation receipt, source grant or root ACK.
Retained observation uses the exact INDEX unit family and does not read dead worker
FDs. The released-lock scope only opens a new description of the same now-free
inode and holds it across caller post-checks; it never unlocks the old lease,
signals/stops/resets a unit or removes PID1's store. The caller must independently
prove the original unit/invocation and terminal/retirement boundary. These source
wrappers do not install or complete that root lifetime/controller.

Remaining production wiring is deliberately separate. The typed handoff below keeps
`native_embedding_index_handoff._checked_batch` CPU-only and supplies a distinct
`PreparedNativeCudaIndex` with the original exact input/association/ordered hashes.
It reuses the descriptor-file primitive in `inference_transfer_cpu_handoff.py`, with
a separate CUDA runtime root and READY FD3. A future actual retired-launch proof must
precede output materialization and explicit CUDA executor composition.
`NativeEmbeddingIndexCompletion` is already
device-neutral; no new Job/vector/receipt/Registry schema is needed. The current
pending-read path in `local_embedding_encoding_admission.py` treats all successful
unit observations as certain: a future CUDA launcher's successful observation must
also require independently proven retirement, never merely process exit success.
These physical wrappers alone cannot supply that completion certainty.

Source verification:355 focused resource/probe/image/benchmark/INDEX leaf/READY
tests PASS25.11s, strict observer typing and Ruff/format PASS. Root GPU/FDSTORE
observations in these tests are synthetic, not an installed CUDA INDEX execution.

### Original-input CUDA INDEX handoff

1. **Responsibility/boundary.** The Orchestrator stages and rereads one distinct
   `PreparedNativeCudaIndex`; root prepares its four descriptor files. This slice
   does not launch, ACK, retire, materialize output or publish an Artifact.
2. **Canonical source.** The existing original input Artifact and launch association
   remain canonical. Reuse their existing owner-local INDEX workspace; the CUDA
   runtime input is only the explicit root/worker descriptor materialization.
3. **Identity/revision.** Preserve execution ID, native Job, association semantic
   SHA, original member raw SHA, request semantic SHA and ordered input-set SHA as
   separate values. No new Job, vector, receipt or Registry schema is introduced.
4. **Resolution checks.** A shared original-input validator reparses both closed
   contracts, preserves copied-model extras for rejection, and compares exact Job,
   space, ordered encodings and all input hashes. The existing CPU wrapper still
   requires CPU; the separate CUDA value requires CUDA, batch4 and threads4.
5. **Access pattern.** Fixed execution-key lookup, ordered bounded input validation
   and exact file/marker replay; no directory scan, latest lookup or DB query.
6. **Structures/indexes.** Frozen prepared values and retained-directory descriptor
   operations reuse the public protected-filesystem primitives. No cache, registry,
   dispatch flag or generic backend framework is added.
7. **Scale/complexity.** Validation/staging is O(original bounded input bytes), with
   one canonical owner input and one explicit runtime copy, not another row DTO.
   READY starts empty; its existing8KiB contract is validated by the later root owner.
8. **Concurrency.** Owner-only staging and association marker precede root-only
   exclusive creation under `/run/eom-native-embedding-cuda-index/<execution>/`.
   Root creates input0600 and result/vector/READY0640 with single-link protection;
   READY is the future O_RDWR OpenFile FD3, not result FD1 or vector FD2.
9. **Dependency/ownership.** The new handoff uses public filesystem and shared
   original-input interfaces only. It imports neither a sibling private helper nor
   a numerical backend, DB, root launcher or benchmark authority.
10. **Failure/idempotency.** Identical owner staging/marker replay is safe; changed,
    malformed, symlinked or mismatched bytes fail. Existing or partial root runtime
    directories are retained and rejected, never repaired/overwritten or relaunched.
11. **Simpler alternative.** Reusing `PreparedNativeIndex` would weaken its CPU
    guard. Duplicating association rules would drift. Sharing only the original
    validator and filesystem primitives keeps two explicit device boundaries.
    No CUDA completion/materializer is exposed until a real independently observed
    root retirement proof exists; a boolean, callback or process-success stub is
    insufficient. Current CPU configuration and runtime behavior remain unchanged.

Source verification:225tests across the new CUDA handoff and existing CPU INDEX,
QUERY handoff, dispatch/launch-identity, native entry and encoding-admission suites
PASS18.86s. Strict typing on both handoff modules and the new test file, Ruff3,
formatter3 and diff checks PASS. Root file creation in these tests uses an explicit
synthetic ownership seam; this is not an actual privileged prepare/OpenFile launch,
retirement proof, model run or GPU activation. No completion/materializer is exposed.

### Fixed unit, root observation and after-READY lifetime — 2026-10-18

The source now includes the fixed CUDA INDEX main unit and a closed serializer for
its eleven positional arguments/nine non-secret environment values. Root may write
`launch.env` only after admitting the original association; its exact form, root
ownership, selected configuration/receipt and immutable input remain pinned. The
main unit uses the existing admitted isolated CUDA interpreter and a separately
root-owned external entry, not an overlay or modified numerical prefix. The new
INDEX effective-policy reader shares the existing physical-policy parser without
extending the existing image/benchmark public allowlists.

The root observer owns the existing `ProtectedCudaInstallationFiles` closure. Its
inventory/host pointers are captured once per scope, with fresh closure assertions
around critical observations, not a persistent cache. Unit/entry/environment/input
bytes and epochs, actual owner/worker birth and credentials, one task, reserved ACK
mask, exact argv/cgroup/cwd, executable maps, device and retained lease must match
before and after observation. FD0 is the original input; FD3 is READY; FD1/2 are
already `/dev/null`. Saved numerical output handles are found by bounded unique
inode/flag matching rather than assuming descriptor numbers4/5. Mutable output
size/time is not incorrectly frozen before model execution.

READY has a dedicated short exclusive writer flock. Root never takes a shared lock
on an empty READY: doing so could make the legitimate nonblocking first writer fail.
A nonempty partial writer instead produces NOT_READY on shared-lock contention;
complete READY is read under that lock and its full nine-field epoch and hash are
pinned. These are descriptor synchronization rules, not changes to the GPU lease
or released READY schema. The entry raw SHA is now
`d7d60aa6035f69be899cb2d00254012681b54813c74988f1a907d0483404e606`;
the main unit raw SHA is
`6a7d5ad3e921d89cd30482ae4e00a5797a0d6a2d16e3b0f61adbf25c316a0bf1`.

The after-READY lifetime functions use the existing protected unit-effect records:
reobserve exact READY, reserve/write ACK intent, reobserve, then signal only that
original main once. Uncertain effects/partial records cannot be replayed. Terminal
verification preserves original outcome/invocation/start and requires old process
termination, empty cgroup and retained physical fencing. Retirement records intent
before outcome-specific stop/reset; an actually retained store is independently
revalidated before its one cleanup. Store0, no GPU client, same-inode exclusive
reacquisition and postchecks determine retirement. Dead owner/expired compute budget
do not prevent cleanup. Successful retirement of an originally FAILED process is
not numerical success or Artifact publication. Read-only uncertainty reconciliation
performs no effect.

The root observer/controller must itself use the already admitted
`/opt/eom/embedding-cuda-loader-empty` cwd: the reused installation closure enforces
that actual inode as well as the worker's cwd. No new dependencies, DB changes,
queue, global registry, source-policy exception or numerical-prefix mutation were
introduced. Scoped work is O(bounded input bytes + bounded descriptor scan + existing
installation epoch checks); metadata history contains no full input or vectors.

Final combined source gate:689 tests PASS53.74s across17 explicit suites, strict
typing on7 changed source modules, Ruff/format13 and independent unit/lifetime/
observer review PASS. Earlier225/344/103/216 suite counts overlap and are not added.
The separate six dependency-boundary checks also PASS, including domain/runtime
direction, reviewed composition-cycle scope and absence of large binary DB columns.
This includes real unprivileged flock/diagnostic tests; root unit/device/FDSTORE
ports remain synthetic. Local final XML is
`/tmp/eom-native-cuda-successor.gKpxVAwN/cuda-index-after-ready-source-final.xml`,
raw SHA `34d80546ad55d5843b9ed7d31bd6dd8d55efd6cd31557d3af515e909e605b5d2`.

Remaining required production work is explicit:

- A fixed root controller must bind the actual trusted owner PID/birth, prepare the
  environment and launch this main unit. Keep start-only authorization on that
  controller; do not copy the CPU rule to grant direct CUDA-main starts.
- Failure before valid READY may already retain a PID1 lease. It needs separate
  actual terminal PID/store0-or1 readback, not a fabricated READY, borrowed benchmark
  observation or automatic cleanup. The current after-READY API rejects this case.
- Owner completion/pending-read certainty must consume independently proven root
  retirement before output materialization/publication, not just process success.
- Preserve the existing pinned WAIT policy under GPU contention and add the real
  public/private CUDA QUERY compositions and exact historical CPU read compatibility.
- Install/activate only a compatible set after the original six actual CPU/CUDA
  measurements. If GPU wins the original gates, verify real INDEX/QUERY/default and
  CPU rollback; otherwise retain CPU with its actual measured reason.

These are original-goal requirements, not new acceptance or human-review gates.
Source functions and synthetic tests do not attest a live root launch, numerical
execution, consumer delivery, performance winner or GPU-default activation.
