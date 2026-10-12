# Fixed native embedding factory and index entrypoint — source plan

2026-10-12 UTC. SOURCE_ADAPTER_ONLY / NOT_COMPOSED / NOT_ADMITTED / NOT_ACTIVE.
This is the narrow composition checkpoint for the approved
[launcher proposal](INCREMENTAL_EMBEDDING_NATIVE_LAUNCHER_PROPOSAL.md), not new installation,
source authority, Runner behavior or benchmark transport. No schema/unit/config, installed
prefix, canonical payload, identity, ACL, database or default is changed. The source-only
`embedding-native-runtime-config/1.0` contract already exists. Its raw pin remains owner-supplied.

## Eleven-item boundary

1. **Responsibility.** Catalog infrastructure composes the protected fixed-profile config,
   admitted installation, numerical observer, existing bundle/payload resolver and offline
   backend. The index entrypoint adapts exactly three inherited regular descriptors. Orchestrator
   alone owns authenticated admission, Job/source/command fences, launch, cleanup and publication.
2. **Canonical source.** Use the one unchanged legacy payload and retained archives. Config,
   bundle and proof are tiny immutable manifests, not copies of weights or source/query bodies.
   The factory must reuse one resolved payload snapshot, not hash the large payload twice.
3. **Identity/revision.** Keep config ID/revision/semantic/raw SHA, bundle/proof pins, numerical
   runtime SHA, execution model revision, owner Job/execution/InvocationID and descriptor inodes
   separate. Prefix/profile/path does not identify an admitted release or grant work.
4. **Pointers/checks.** Capture exact config logical/revision IDs and expected raw SHA from the
   independently accepted installed owner context, not argv, environment, stdin or a parsed DTO.
   Resolve canonical config/bundle/proof closure and current protected epochs. A mandatory
   independently accepted whole-prefix/host/loader admission handle precedes optional ML imports.
5. **Access patterns.** One fixed profile lookup, one bounded metadata read per manifest, one
   streamed payload verification, then ordered metadata/epoch checks around work. Index uses one
   existing input/result/vector FD triplet; there is no queue, latest lookup or corpus traversal.
6. **Structures.** One frozen captured installation value, one no-argument context factory,
   existing resolved snapshots and one small observer composition suffice. Use the closed CPU/CUDA
   profile mapping, not mutable registries, runtime selectors, arbitrary loaders or a proxy encoder.
7. **Cost/scale.** Config/bundle/proof retain their64/64/128KiB bounds. Keep only bounded metadata
   and per-member/ancestor epochs; stream payload hashes once. Initial work is O(bytes+members),
   later checks O(members), and encoding retains the existing fixed batch4/thread4/interop1 recipe.
8. **Concurrency.** No DB transaction or source lock spans inference. The owner reserves one
   launch and separately enforces its current Job/command/source fences. CUDA requires the actual
   shared physical lease and independently admitted idle/orphan/device mapping before observation.
9. **Dependencies/ownership.** Contracts remain IO-free; no new dependency is needed. Factory
   and entrypoint are Catalog adapters using explicit public modules. The GPU installation agent
   owns whole-prefix admission and root actions; this plan does not copy its receipt or parser.
10. **Failure/replay.** Missing capture/admission/identity/epoch/ownership denies before ML. Busy
    CUDA does not select CPU. On construction, encoding or teardown failure preserve partial output
    and exit unsuccessfully; owner reconciles the same execution, never overwrites or re-encodes
    merely because cleanup is unknown. A local completion never releases owner capacity itself.
11. **Simpler alternative.** Passing request descriptors to a historical CPU factory bypasses
    config/admission/device closure. Independently pre-resolving then re-resolving weights doubles
    byte work. Reuse the existing observer/backend/stdio with three small read-only seams instead
    of duplicating encoder/provenance rules or inventing a general installed-runtime framework.

## Existing seams and the three narrow gaps

`ConfiguredEmbeddingBundle`/`resolve_configured_embedding_bundle` return a supported
`ResolvedEmbeddingBundle` containing the actual bundle, verified legacy payload and small raw
manifest. `OfflineNativeEmbeddingBackend` currently always invokes that resolver itself.
Propose an explicit unreleased `resolved_bundle` construction seam: the trusted factory passes
that same snapshot after public pointer/raw/root checks; the old constructor path still resolves
normally. The backend checks configured identity/roots, execution/runtime closure and unchanged
epochs before use. This value is no installation/authority grant and never comes from worker JSON.

`ProtectedInstalledEmbeddingRuntimeObserver` already reads the protected proof once, verifies
exact numeric archives/RECORD/installed members and observes actual interpreter/OS identity. It
currently exposes only `observe()`. Propose one read-only verified proof/raw-metadata accessor,
retaining its initial bounded raw proof. This lets the existing public config-reference validator
use real resolved metadata without private `_proof` access, a request echo or a second proof read.
Its source numerical proof still does not admit the complete prefix/loader/sandbox.

The approved resolver reuse also has one private construction-provenance witness, minted only
after its authoritative payload byte audit. The public resolved-snapshot validator binds original
bundle/payload/manifest object identities, exact configured roots/pointer/canonical raw bytes,
nonempty exact audited member closure and current epoch snapshots. Constructed or changed copies
are rejected before observer/ML; unchanged copies may reference the same legitimate objects.
This is ordinary Python provenance, not a cryptographic/unforgeable Python-code security boundary,
secret, authority capability or registry. It does not waive independent installed admission.

`NumericalRuntimeFileSnapshots` holds no-follow file/ancestor FDs during initial reads and retains
named file/ancestor epochs afterward; it does not retain every FD for the whole invocation.
The legacy payload resolver does not provide strong nonwritable ancestor-epoch closure. Propose
one metadata-only protected member-identity observation method in the existing files owner, shared
by its interpreter wrapper and the native factory's exact derived bundle/payload/implementation
members. It captures file type/owner/mode/nlink and protected ancestor identity without rehashing.
Observe around resolution and cross-check both snapshots before/after use.
The resolver's optional `observe_member_identity` seam invokes this metadata observer before
reading the bundle, then before the exact parsed payload manifest/members' legacy byte audit.
The factory passes its real protected observer and asserts all captured epochs afterward;
fresh same-byte manifest/ancestor swaps during resolution are denied before backend/ML.
The GPU agent owns separate bounded initial-observed-byte/whole-prefix additions; coordinate this
method before edits.
Do not call or copy `_protected_open` from another module, alter legacy resolver semantics, or
describe retained named epochs as continuously held descriptors.

## Captured owner context and entry order

The proposed captured installation value contains only the closed profile, exact configuration
logical/revision IDs/raw pin and a mandatory actual installed-admission handle. Fixed roots derive
from the accepted profile and validated IDs. CUDA additionally captures the existing typed
`CudaEmbeddingOwnership`; CPU rejects such a handle and does not import the lease distribution.
The factory callable takes no request, descriptor, path, actor, role, flag or runtime override.
The accepted handle's exact profile/prefix and captured config pin must agree before use; an
admission for the other prefix cannot satisfy this factory. The production capture/loader must
be root-installed and independently admitted. Its exact public
whole-prefix receipt loader remains the GPU agent/root review gate; absent concrete acceptance
is unavailable, not a fabricated successful observer or self-hashing admission DTO.

1. **Owner before first successor instruction:** independently admit the exact prefix, interpreter,
   private source/wheel, host/ELF/loader/site hooks and bytecode closure. Root uses its admitted old
   protected interpreter for the initial stdlib audit; the factory cannot retroactively prove safe
   interpreter startup or site initialization. Fixed unit/source/bootstrap pins are separate checks.
2. **Earliest entrypoint code is stdlib-only:** validate the fixed installed interpreter/profile and
   exact worker UID/primary/supplementary groups, isolation flags, NoNewPrivs and zero capabilities.
   No user-selected interpreter, module, prefix, library knobs or fallback is accepted. Root unit
   association provides the sole execution identity; native input1.0 has Job/request pins, not an
   execution-ID field. Root prepare must bind the unit/launch/input before PID1 opens the FDs.
3. **Protect output before other imports:** save FD1/result and FD2/vectors using close-on-exec
   duplicates, keep FD0/input, and redirect ordinary stdout/stderr to null. Do not restore diagnostic
   output to result/binary channels on failure or after library teardown. Close only owned duplicates
   and sink FDs. Original/source exceptions never become logs or completion JSON.
4. **Reuse the existing leaf:** pass `NativeEmbeddingDescriptors(0, saved_result, saved_vectors)`
   and the captured no-argument scope to `run_native_embedding_descriptors`. Its public checks
   validate distinct root-owned regular inodes/modes/flags/offsets/empty outputs and canonical input
   before scope construction. Do not duplicate its parser or relax its three-root-FD rules.
5. **Scope preflight:** revalidate mandatory accepted installation and protected config epochs,
   read config once from its fixed ID/revision-derived location, enforce independent raw/canonical/
   semantic pins and profile/resources. No copied bool/extra value bypass or mutable latest.
6. **CUDA before observation:** assert actual shared ownership, exact UUID/minor/driver/boot mapping
   and independently admitted device idle/unknown-PID gate. Missing any concrete gate denies before
   observer/model work; no GPU auto-detection or version-to-hash inference.
7. **Resolve once:** construct the real protected numerical observer; obtain its verified proof
   metadata; resolve the exact bundle and one canonical payload; retain stronger member/ancestor
   epochs; run the existing public config-reference validator on those actual raw documents. Compare
   runtime SHA, device/Python/CUDA build, exact5/20 archive pins and fixed batch/thread closure.
8. **Construct existing backend:** inject that resolved snapshot and a tiny observer composition
   which asserts installation/config/member epochs before/after delegating real `observe()`.
   Existing backend observation around construction/token/encode/close then protects these gates
   without a duplicate encoder/provenance layer. Optional Torch/transformers imports occur only now;
   actual FP32/eager/device/tensor/thread4/interop1 read-back stays backend-owned.
9. **Work/output:** existing index leaf performs genuine DOCUMENT encoding, validates f32 and
   semantic closure, writes binary before JSON once, and preserves any partial output. The same
   backend factory may later serve genuine QUERY benchmarking, but this entrypoint is index-only.
10. **Exit:** assert gates around synchronized backend close; never close the owner's CUDA lease
    inside the factory. Owner verifies exact terminal unit/InvocationID/cgroup/process/device cleanup
    before publication/release. Abnormal last-close can release flock before driver cleanup; the
    existing all-entrypoint pre-ML/reconciliation requirement remains mandatory, not solved here.

Base bytecode is not blanket-denied: current independent archive evidence found1133 canonical
Conda pyc and779 installed Python pyc, with archive bytes and CPython source/header behavior
requiring the exact reviewed admission ledger. `-B` prevents writes, not reads. Only that accepted
base-bytecode closure is usable; every unregistered/private EOM pyc remains forbidden. A stale
timestamp ignored by CPython is not permission to execute arbitrary bytecode or remove evidence.
Canonical model DAC remains root-owned: exact new native UIDs get only required ancestor traversal
and admitted member read ACLs, no duplicate/hardlinked weights, default/writable ACL, broad group,
NAS or legacy-environment access. Apply/read back DAC before renewed metadata/epoch acceptance.

## Exact approved source/test scope

Root approved these11 source/test paths. The sole mandatory admission port is
`NativeEmbeddingInstallationAdmission.assert_current(*, profile, configuration_id,
configuration_revision_id, configuration_raw_sha256) -> None`, coordinated with the installation
agent. No default receipt implementation, boolean grant, root-installed capture or CLI/main exists.
The source library adapter requires explicit owner capture and cannot establish first-instruction
or effective installed-unit admission. The11 paths plus this note are the complete narrow scope.

| Path | Source responsibility |
| --- | --- |
| `services/catalog_service/eom_catalog_service/embedding_native_factory.py` (new) | Fixed captured pin/admission context, no-argument backend scope and small observer gate composition; no installer or authorization |
| `services/catalog_service/eom_catalog_service/embedding_native_entrypoint.py` (new) | Stdlib-first quiet output/identity/closed profile adapter into existing three-FD leaf; no configurable CLI runtime knobs |
| `services/catalog_service/eom_catalog_service/embedding_offline_backend.py` | Supported already-resolved bundle reuse only, same old constructor behavior and encoder recipe |
| `services/catalog_service/eom_catalog_service/embedding_installed_runtime_observer.py` | Tiny read-only verified proof/raw accessor only |
| `services/catalog_service/eom_catalog_service/embedding_runtime_files.py` | Metadata-only protected member/ancestor epoch observation; coordinated with installation owner |
| `services/catalog_service/eom_catalog_service/embedding_bundle_resolver.py` | Authoritative construction-provenance witness/public resolved-snapshot validation, no registry or authority |
| `tests/unit/test_embedding_native_factory.py` (new) | Synthetic captured contexts, fail-before-ML order, exact profile/pins/closure, epoch drift, one payload hash, admission loss/teardown fencing |
| `tests/unit/test_embedding_native_entrypoint.py` (new) | Fixed UID/groups/capabilities/profile, quiet imported-library output, malformed/aliased FD order, duplicate/sink cleanup and no worker path/knob/grant |
| `tests/unit/test_embedding_offline_backend.py` | Reused snapshot identity/root/raw mismatch, one payload byte audit and unchanged old constructor/encoder behavior |
| `tests/unit/test_embedding_installed_runtime_observer.py` | Accessor read-once/bounds, strong ancestor/leaf mode/link/missing/epoch drift and unchanged observation behavior |
| `tests/unit/test_embedding_bundle_resolver.py` | Constructed/changed/empty snapshot denial and unchanged original-object reuse without another payload byte read |

Do not edit frozen config/benchmark contracts or legacy CPU/stdIO/handoff/verifier/unit paths.
Run explicit API source tests, Ruff/formatter and API/core strict checks; retain the historical
schema/default/stdio regression suites and fresh-import no-ML guards. Synthetic handles only
establish source ordering, never installed prefix/GPU/admission PASS. Factory source completion
would still leave actual owner receipt/unit/DAC/source authority/lease migration, benchmark owner
transport, mandatory same-input CPU/CUDA evidence and conditional CUDA default activation pending.
