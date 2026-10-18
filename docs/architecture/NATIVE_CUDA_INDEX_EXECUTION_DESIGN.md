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

### Fixed root INDEX controller boundary

1. **Responsibility.** One root controller composes the existing original-input
   handoff, fixed main unit, READY observation, ACK and terminal retirement. It
   grants neither source access nor Artifact publication; the original owner still
   owns admission, reservation and late-source fences.
2. **Canonical source.** The staged association/request remain the original input.
   Fixed root-owned `/etc/eom/embedding-native-index-backend.json` uses the existing
   backend-selection contract; the owner request cannot choose a configuration.
   `/etc/eom/embedding-native-cuda.env` contains only its five non-secret immutable
   configuration/receipt pins. Its static raw hash is not dynamic `launch.env`.
3. **Identity/revisions.** Original execution/Job/association/input identities are
   retained. A separate owner-binding contract pins the actual owner PID/birth;
   no new Job, queue, vector identity or model-selected authority is introduced.
4. **Resolution.** Root retains protected deployment-file epochs, validates the
   actual owner and original staged input, exclusively prepares descriptors, and
   captures the existing complete installed configuration/receipt closure before
   starting the main unit. Missing deployment files fail closed.
5. **Access patterns.** Exact execution/configuration lookup and bounded ordered
   readiness/terminal observation; never directory-wide discovery or latest lookup.
6. **Structures.** Frozen outcome values and existing unit/effect records are used.
   Exclusive runtime-directory creation reserves the one dispatch. No registry,
   DB schema, cache, retry identity or parallel scheduling framework is added.
7. **Complexity.** O(bounded original bytes + existing installation capture) plus
   bounded status observations within the fixed180-second computation lifetime.
   File epochs are reused inside that scope, not cached across launches.
8. **Concurrency.** Require a fresh exact main unit before one nonblocking start.
   Once started, pin its first actual invocation/start. Before ACK the worker may
   wait on the existing shared GPU lease until the original deadline, retrying only
   BUSY on the same input/identity; INVALID is never retried. No model/GPU device
   access occurs while waiting. No CPU fallback or new encoding key is allowed.
9. **Dependency/ownership.** The protected owner SDK composes infrastructure only;
   the numerical CUDA prefix is not modified. A new root service is distinct from
   the CPU prepare service. Start-only authorization names the controller, never
   the CUDA main unit. Root needs actual process inspection and PID1 access.
10. **Failure/idempotency.** A dispatch timeout is uncertain, not permission to
    start again. Exact failed terminal observations use the separate pre-READY
    cleanup path; a reserved/uncertain ACK never does. After READY, preserve the
    original outcome and require retirement. Unexpected observation failure or
    deadline does not authorize blind stop/reset/cleanup or publication.
11. **Simpler alternative.** A direct main-unit start loses trusted ACK/retirement;
    borrowing benchmark authority or weakening the CPU root service loses its
    boundary. Composing the already implemented concrete adapters is sufficient.
    The installed CPU owner currently uses a different service process group from
    the primary-group proof required here; it is not silently declared compatible.
    A reviewed CUDA-owner composition/group alignment remains a deployment gate.

This section is an implementation plan, not evidence of installed deployment,
valid operator authentication, GPU performance or complete owner publication.

### Original owner-process binding

1. **Boundary.** Bind the real Orchestrator process that marked one CUDA INDEX
   launch. This small value is neither source authority, backend choice nor ACK.
2. **Canonical source.** Actual current kernel PID/birth and fixed owner credentials
   produce `owner-binding.json` in the existing canonical owner-local workspace.
   Existing association/input Artifacts remain canonical for Job/request/source.
3. **Identity.** The closed1.0 value carries execution ID, association semantic SHA,
   owner PID/start ticks and its own semantic hash, not a duplicate Job or input.
4. **Checks.** JSON Schema2020-12 precedes the frozen model; bounded canonical parsing
   rejects extra/coerced/copied fields and bad hashes. Protected readback links the
   exact staged association and existing launch marker, not an implicit latest.
5. **Access.** One fixed execution-key lookup and constant-size proc/file reads;
   no process scan, database, source-content lookup or worker-selected path.
6. **Structures.** One frozen value and exclusive exact-replay owner file reuse
   existing retained-directory/member primitives. No registry/cache is introduced.
7. **Scale.** At most1KiB canonical metadata, O(1) space/time beyond existing bounded
   association/input validation. Process metadata contains no text or credentials.
8. **Concurrency.** After the current source/command fence, the actual owner writes
   the binding before the association-only launch marker. Same-process exact replay
   is allowed; a replacement owner conflicts rather than replacing old provenance.
9. **Direction.** The pure Catalog contract imports only contracts/identifiers.
   Orchestrator IO uses its public protected-directory/member interfaces and a tiny
   local stdlib-only fixed proc adapter, not a forbidden dependency on Catalog
   infrastructure, benchmark authority or sibling private helpers.
10. **Failure.** Missing/tampered binding, PID reuse or credential/birth drift fails
    root preparation before runtime creation. Protected readback itself stays usable
    after owner death for cleanup; a later live observer separately fences compute.
11. **Alternative.** The association-only marker cannot identify the actual owner.
    Accepting PID claims as flags would not bind them to original protected staging.
    CPU marker/contracts and all current CPU runtime selections remain unchanged.

The current released CPU controller unit uses Group=eom; that is not proof of a
CUDA-compatible primary owner GID. These new kernel checks keep the fixed owner's
primary UID/GID rule. A future CUDA controller must align its trusted unit Group or
separately review an exact runtime-GID contract; this slice does not broaden the
check, modify the CPU unit or claim the current composition passes CUDA admission.

Verification: the schema/mirrored resource/loader/model gate passed32 tests before
producer behavior changed. Final229 tests across owner-binding, CUDA/CPU/QUERY
handoffs, dispatch/launch identity, READY and dependency boundaries PASS22.60s;
strict typing5, Ruff5 and formatter5 PASS. Initial diagnostic failures are retained:
two schema-test assumptions about mathematically integral float lexemes, one real
forbidden infrastructure dependency (removed, not allowlisted), then two outdated
synthetic IO seams after that adapter relocation. No business guard was relaxed.
The final gate includes real unprivileged reads of the test process's own proc
metadata; root runtime creation remains synthetic, not installed CUDA acceptance.

### Failed original INDEX before ACK: terminal recovery

1. **Boundary.** Observe and retire only an originally failed CUDA INDEX invocation
   without an ACK record. Never fabricate READY, worker birth or benchmark authority.
2. **Canonical source.** Actual systemd terminal invocation/start/ExecMainPID/store,
   the original protected launch files and actual PID1/lease facts are authoritative.
3. **Identity.** Keep execution, Job, association/input hashes, terminal invocation,
   actual terminal PID and raw READY hash/epoch separate; partial/empty READY is metadata.
4. **Checks.** Require root, fixed unit family, full original installed/file closure,
   unchanged original failed outcome/start, empty cgroup and absent ACK reservation.
5. **Access.** Exact original-unit/file lookup and bounded kernel/descriptor reads;
   no database, source-content scan, live-owner requirement or implicit latest.
6. **Structures.** Frozen terminal/retirement values and the existing protected
   unit/invocation/phase effect records; reuse the shared physical/terminal primitives.
7. **Scale.** O(8KiB READY + existing bounded installed closure/descriptor scan),
   constant terminal metadata, no full request, vector or credential history.
8. **Concurrency.** Recheck before intent and effect. Store1 requires the exact
   retained lock/device and idle GPU before one reset/clean, then same-inode released
   reacquisition plus postchecks. Store0 never inspects or cleans another GPU holder.
9. **Direction.** INDEX infrastructure owns concrete root effects; shared physical
   readers grant no execution authority. The sealed numerical prefix and released
   READY schemas stay unchanged.
10. **Failure/replay.** Preserve FAILED. Partial records/uncertain effects are not
    retried; read-only retirement reconciliation remains available after owner death
    or compute expiry. Missing/changed proof remains explicit uncertainty.
11. **Alternative.** The after-READY path cannot represent absent readiness, and
    importing benchmark recovery would borrow unrelated authority. One narrow INDEX
    path reusing existing primitives closes that real lifecycle gap without a framework.

This source slice is not installed execution, GPU/default activation or numerical success.

Verification:230 tests across the new INDEX unacknowledged/actual terminal-metadata
readers and existing benchmark unacknowledged/INDEX lifetime/physical-resource suites
PASS22.14s; the separate82 existing benchmark pre-ACK retirement, benchmark lifetime
and image lifetime regressions PASS16.81s. Strict typing5, Ruff9, formatter9 and diff
checks PASS. Initial fixture collection and exact-union typing errors were corrected
without weakening guards. Root/kernel/GPU ports remain synthetic; protected local
record writes are real. The source preserves store0 isolation, raw partial/empty
READY, absent-ACK proof, original FAILED, no-replay partial effects and same-inode
release closure. No actual root start, ACK, cleanup, model or device selection ran.

### Controller source integration checkpoint — 19:09 UTC

The fixed root controller now composes original owner binding, exclusive runtime
preparation, fixed static backend pins, installed-file capture, one nonblocking
main start, actual invocation/start pinning, independently observed READY/ACK and
the appropriate after-READY or unacknowledged FAILED retirement. Its small frozen
return contains execution/Job/association/input identities and retirement metadata,
not another copy of the request. It is explicitly not a wire completion receipt or
permission to publish an Artifact.

The new `eom-embedding-native-cuda-index-owner@.service` uses the existing protected
owner SDK/isolated interpreter with the CUDA empty cwd and selected cache. Root
gets only CHOWN/DAC_READ_SEARCH/SYS_PTRACE capabilities, fixed device access and
PID1/process observation. Start-only Polkit grants the trusted owner this controller,
and explicitly denies direct CUDA main starts. The old CPU prepare service, old
CPU Polkit rule and numerical CUDA prefix were not changed. Nonoptional runtime
and lifetime directories must be protected/precreated during a later installation.

The leaf's admitted WAIT is now explicit: only shared-lease BUSY retries on the same
original execution until its unchanged finite deadline; invalid lease protection
fails immediately. No model/device opening, new request, same-unit restart or CPU
fallback is introduced. The external leaf's new raw SHA is
`0fb389628c322ea9b0cc01ad05c422f44ee637dc3d7883c95344eed425548a8a`;
the main template bytes are unchanged. Controller source raw SHA is
`600c0c17dd82b5e527a352286a3c99bcdf32bc020d65fe5ff6437a2a1a136fa5`.

Final combined27-suite gate:975 tests PASS97.44s, including dependency boundaries,
legacy CPU/QUERY and GPU probe/benchmark/image retirement. Separate resource/wheel
packaging tests71 PASS9.27s; strict typing12 source files, Ruff/format21 and independent
controller/owner/pre-READY reviews PASS. Earlier229/230/82/149/77 reports overlap
this cohort and are not added. Actual unprivileged own-process proc reads, flock,
zero-diagnostic children and protected local record IO are exercised; privileged
systemd/device/FDSTORE/model ports remain synthetic.

Final XML `/tmp/eom-native-cuda-successor.gKpxVAwN/cuda-index-controller-final.xml`,
raw SHA `ad948679c1191807600892d65ea209294c6aa7d5d893b213c3405b86344ca8b4`.
Packaging XML raw SHA
`cc210eb6b66cea9ab3a035dcecd77df7d0c3a023b396854388bf455c0c7e06ac`.
No database/state change, dependency addition, auth prompt, service mutation,
numerical run, original benchmark allocation or default-device change occurred.

**Still required:** owner completion/pending reads must consume a protected actual
retirement/output proof before materialization/publication. This source controller
alone is not that proof. Actual fixed six-run performance/finalization and C1–C5
delivery remain the original priority once genuine supported authentication is
available. GPU QUERY/default and real CPU rollback are conditional on the original
measured winner/gates, not on synthetic test counts. No additional acceptance or
human evaluation gate is added. Do not expand implementation beyond these original
dependencies or activate the partial CUDA composition merely to exercise it.

Candidate `061439696a7b45c8452e1224127ae93537abf55c` passed official build-only
wheel/RECORD verification in
`/tmp/eom-api-build/061439696a7b45c8452e1224127ae93537abf55c.3zQplf/dist`.
The two owner wheels were materialized only under
`/tmp/eom-cuda-index-owner-import.oQdmrBz1/site-packages`. Both actual protected
INDEX-CPU and experiment interpreters imported the new controller, unacknowledged
recovery, handoff and owner contract with `-I -B`, no repository/source path and
zero numerical/ML/`eom_gpu_lease` module imports. No function granting execution or
reading source/IAM was called. This is installed-wheel simulation, not protected
owner-release installation or numerical admission. The new root unit also passed
actual `systemd-analyze verify --man=no`; no unit was installed or started.
