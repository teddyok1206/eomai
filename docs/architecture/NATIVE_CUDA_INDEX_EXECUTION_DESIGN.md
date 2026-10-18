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
