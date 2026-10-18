# Fixed native CUDA INDEX execution

Status: **SOURCE CONTRACT ONLY / NOT_INSTALLED / NOT_ACTIVE / NOT_EVALUATED**.
This defines the protocol for the production INDEX boundary required by the
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
