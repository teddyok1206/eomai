# Fixed native benchmark worker leaf — source boundary

2026-10-13 UTC. SOURCE_LEAF_IMPLEMENTED / NOT_ACTUALLY_BENCHMARKED / NOT_ACTIVE.
Root approved the narrow seam phase and the ten-path worker/files phase below. The source leaf
now reuses the in-process observed-token/device/allocator APIs, authoritative sample-program
wrapper and terminal resource exchange. Factory typing is richer; its captured admission behavior
is unchanged. Index entrypoint, schemas/configurations, source authority, installed prefix, unit,
ACL, install, actual model/GPU execution, database and default remain unchanged.
This advances the required actual CPU/CUDA benchmark/conditional activation route; it proves none
of its pending runtime gates. The reviewed
[benchmark recipe](INCREMENTAL_EMBEDDING_DEVICE_BENCHMARK_PROPOSAL.md),
[GPU design §§6–8](INCREMENTAL_EMBEDDING_GPU_RUNTIME_DESIGN.md#6-실행-전에-pin하는-작은-benchmark-protocol),
[factory boundary](INCREMENTAL_EMBEDDING_NATIVE_FACTORY_BOUNDARY.md) and
[committed channel](INCREMENTAL_EMBEDDING_BENCHMARK_CHANNEL_BOUNDARY.md) remain authoritative.

## Eleven-item boundary

1. **Responsibility.** One Catalog native leaf executes an already admitted fixed benchmark
   invocation, emitting local vector/token/timing/resource evidence and checkpoints. Orchestrator
   authenticates and reauthorizes sources/queries, launches six children, ranks/compares, observes
   process/device cleanup and publishes Artifacts. Neither worker nor channel grants admission.
2. **Canonical source.** Reuse one legacy payload, exact configured CPU/CUDA bundle/proof and
   staged inputs. One per-launch canonical vector file set and final resource member suffice.
   Token arrays exist only in bounded local witness evidence, never DB/source bodies or Git.
3. **Identity/revision.** Keep benchmark ID/revision, owner Job/execution/invocation raw/semantic
   pins, input-set/family hashes, both purpose spaces, config identity/raw pin, member hashes and
   socket/file/PID/InvocationID epochs distinct. No mutable latest or fabricated real profile.
4. **Pointers/checks.** Capture the admitted launch/profile/config/invocation raw pin and actual
   owner peer/fences from the installed owner context, never request authority or path knobs.
   Validate fixed local input/raw/semantic closure and actual backend model/runtime against the
   invocation. Numeric SHA alone does not establish logical bundle/proof identity; exact owner
   staging/config association is separately mandatory. Preserve the factory's required admission.
5. **Access patterns.** One bounded invocation/input read, ordered≤18 DOCUMENT/two QUERY rows,
   fixed sample/phase iteration, fixed-member lookup and one terminal resource roundtrip. Hash
   immutable files once at materialization, then retain epochs; no queue, corpus scan or re-encode
   on transport retry. Row and member maps/sets enforce uniqueness without repeated list searches.
6. **Structures.** Frozen existing messages, ordered sample/token tuples, one retained file set,
   one backend instance and the existing channel state counter are enough. Public sample-program
   access must reuse the contract's private authoritative program, not another benchmark engine.
7. **Bounds/cost.** Invocation≤64KiB, staged input≤64MiB, aggregate local output≤16MiB and
   ≤64 members; fixed batch maximum4/thread4/interop1, dimension1024/token ceiling2048. First-cold
   output16 members and cold-only4 use the approved aliases below; six file sets total48. Work is
   O(actual token/vector bytes), metadata O(rows+members+21); no model/payload duplication.
8. **Concurrency.** One serial child/model/channel per admitted launch; global180s deadline
   includes constructor, work, ACK waits, close and terminal resources. No SQL transaction spans
   inference/waits. CUDA actual ownership precedes observer/ML and lasts through owner cleanup;
   the worker/factory cannot release owner capacity merely because a checkpoint or result exists.
9. **Dependencies.** Reuse Catalog contracts, stdlib files/clocks, public factory/backend/codec
   and committed channel. No new dependency, worker DB/NAS access, direct worker communication or
   private index/image/legacy helper import. Independent GPU observation remains an owner adapter.
10. **Failure/idempotency.** EOF/deadline/peer/epoch/source/runtime/token/OOM/close/resource error
    stops further phases and preserves partial local files. Never overwrite, reconnect, silently
    choose CPU, truncate, reduce batch/tokens or change thresholds. Only a validated exact phase
    prefix may form FAILED evidence; incomplete witnesses/timings stay absent, not fabricated.
11. **Simpler alternative.** Index3FD1.0 is DOCUMENT-only and cannot carry QUERY phases; separate
    tokenization would not prove tokens actually used by inference; Torch allocator numbers do not
    prove whole-process/device GPU usage. Two small worker/files modules plus narrow public backend/
    program/channel seams suffice, without a generic benchmark, dispatcher or new wire family.

## Fixed program, tokenizer proof and clocks

The six launch order remains CPU1→CUDA2→CUDA3→CPU4→CPU5→CUDA6. Ordinals1/2 keep their one
model instance; other four execute only cold. Use the frozen sample program: cold DOCUMENT,
valid synthetic cases1..6 at actual batch1/4, one unmeasured full DOCUMENT warm-up, warm DOCUMENT5,
QUERY1×5 then QUERY2×5, capacity2048 at actual batch1/4. Synthetic empty7/overflow8 at batch1/4
produce exactly four rejection records, never vectors. Warm-up has only its existing count1.
First-cold has30 vector/token samples; cold-only has1. Real rows retain exact profile/view/text
refs; synthetic/capacity token rows bind their existing input-text SHA plus ordered batch position,
not invented corpus profile IDs. Duplicate case5/6 text/IDs remain exact duplicates.

The historical index backend exposed token lengths, not actual encode-used padded IDs/masks/types.
The source benchmark observation method uses the same authoritative tokenizer/padding/forward/
host-L2 path as existing `encode`, preserving the index method and configured maximum batch4.
It returns actual used batches plus vectors. EMPTY rejects before tokenizer and carries only input
hashes with explicitly absent token counts/ID hashes; it never presents count0/hash([]) as observed.
OVERFLOW retains actual validated unpadded count/ID hashes bounded to4096, never long token arrays;
it requires at least one actual count>2048 and the actual model ceiling2048. Generic smaller-ceiling
model failures or larger input have no benchmark expected-rejection summary. Unrelated runtime/OOM failures are not
expected rejection.
No worker accesses `_tokenizer`, `_tokens`, `_torch` or recreates tokenizer/normalization rules.
Verify staged actual count/ID hash for each corresponding purpose, ordered rows, actual batches,
pad token, mask/type lengths and exactly2048 capacity including prefixes/special tokens. Frozen
token-witness1.0 requires right/longest padding; an incompatible actual tokenizer fails, not a
normalization/left-padding waiver. No truncation, autocast, TF32, compile or mixed-device tensors.

Public backend synchronization and cumulative allocator-peak read-back seams retain their bounds; no peak
reset after constructor may erase load/warm/cold maxima. Linux RSS is actual cumulative
`ru_maxrss×1024`, not a model-only estimate. Capacity local samples report cumulative high-water
marks observed after each fixed probe, not an invented exclusive per-call peak. No real GPU data
is captured by this note or synthesized from hardware/model names.

Record positive raw `perf_counter_ns` spans. Protected earliest-entry timestamp→factory entry is
worker startup; factory entry→yield is load/hash/model constructor; parent cold E2E starts before
admission/staging/startup and stops after validated COLD_READY. Worker startup is not the parent's
complete unit-start duration. Public synchronize fences surround each measured encode span,
including tokenization/forward/transfer/host-L2/f32/local vector validation. File durability/owner
validation are separately included in cold/query E2E; warm/query encode spans never include ACK
waits. CPU floor(ns/1000), CUDA ceiling(ns/1000) remain owner conversions; sub-microsecond CPU
samples fail, never become artificial1us. There are no cache drops or page-cache-cold claims.

| Checkpoint | Worker action and owner clock |
| --- | --- |
| COLD_READY1 | Close/fsync cold f32 after local token/vector checks; owner validates it and stops cold E2E before ACK. No warm/query work before matching ACK. |
| QUERY_PREPARED2/4/…/20 | No vector/span. Worker waits; owner starts QUERY E2E BEFORE fresh query/candidate/source/session/command authorization, then sends matching ACK. |
| QUERY_READY3/5/…/21 | Encode genuine QUERY batch1, close/fsync its fixed f32, emit actual encode span; owner validates/ranks against immutable same-device cold DOCUMENT rows, stops E2E, then ACKs. |

Sequence is exactly1 or21, q=1..2/r=1..5 prepared sequence2+10(q−1)+2(r−1), ready successor.
The complete first-cold `BenchmarkTokenWitness` cannot be sealed at COLD_READY: its contract
requires all30 samples. Cold token sample is validated locally then retained; final witness is
sealed after all phases. Cold checkpoint is provisional until owner validates that final actual
witness, file epochs and cleanup. Do not claim an early complete witness or add another phase.
The actual monotonic owner query interval includes fresh authorization, wait, encode and ranking;
worker cannot manufacture it by summing local spans. All predeclared numerical/rank/resource/
performance gates remain unchanged; only the actual owner evaluates them.

## Fixed files and no-clobber materialization

Invocation comes through the distinct root-owned0600 regular read-only FD0. The exact
`benchmark-inputs.json` alias is root-staged, single-link/read-only under the launch's fixed input
directory; native UID gets only necessary read/traverse DAC. Its accepted ACL/mode is read back,
not misrepresented as0600 if the ACL mask changes group mode bits. Capture expected execution/
invocation/profile/root pins independently; no worker-supplied directory or other alias is opened.
Use the existing benchmark bounded parser with its fixed64KiB/64MiB budgets, not the index parser.

Root prepares exact output names O_EXCL. Output directory is root-protected with native UID
traverse/read only, no name create/delete/rename. Existing output members are native-UID-owned0640
with the accepted owner's read GID; open each once no-follow/write-only/no-append, require initial
empty offset0/nlink1/regular/distinct inodes, retain FD/named/ancestor epochs. Do not O_TRUNC or
create files in the worker. Check aggregate limit before every write, flush/fsync/close before the
matching ready checkpoint, and never rewrite closed cold/query members.

First-cold has12 f32 aliases: cold, supplementary, query-q-r for q1..2/r1..5; plus
`token-witness.json`, `timings.json`, `resources.json`, `worker-result.json` (16 total).
Cold-only has cold f32, token witness, resources and worker result (4); its cold timings are
already inline in WorkerResult, no extra standalone timing alias needed. Supplementary ranges
append each synthetic/warm/capacity sample once, then close and bind one final binary hash/size.
Use existing f32 pack/read validators, exact offsets/alignment/row count and finite unit norms.
Final `worker-result.json` is written once after successful close/resource finalization, or as a
validated FAILED prefix where representable. Interrupted/uncertain partial bytes remain evidence;
an empty or partial file is not repaired into a successful result. Only owner commits Artifacts.

## One terminal owner-resource roundtrip — existing message, not another checkpoint

`BenchmarkResourceEvidence/1.0` is already a top-level parsed family message. Preliminary CUDA
evidence may have owner_count0/whole-process/device peaksNone; a COMPLETED CUDA WorkerResult
cannot. After the exact checkpoint transcript completes, worker performs remaining capacity probes,
samples local RSS/allocator/OOM values and closes the backend through its admitted factory while
retaining CUDA ownership. Then it submits one bounded preliminary resource message over the same
admitted owner endpoint and waits for one finalized resource message. No new schema, checkpoint,
phase, query authorization grant or arbitrary dispatch is added. The source channel now implements
`exchange_resources`/`finalize_resources`; the owner method requires a caller-supplied late finalizer
and rechecks peer/FD/absolute deadline immediately before and after it. This is a required adapter
port, not a concrete installed monitor or an authority grant.

The independent owner monitor starts BEFORE model constructor, retains actual invocation/PID/
starttime/cgroup/device/lease association and bounded process/whole-device observations, and runs
through late finalization/cleanup. Owner uses real current source/session/command/peer/device
fences, verifies unchanged worker local measurements, merges only independently observed whole-
process/device peaks, observation/overlap counts and capacity whole-process bounds, then replies.
Capacity schema has no window timestamps: an explicitly predeclared invocation-wide observed peak
may serve as a conservative bound for each capacity sample; never claim exclusive per-probe peaks.
Missing observations, unknown consumers or uncertain close cannot become invented zero/one counts.

Worker validates exact invocation/ordinal/device, unchanged local RSS/allocator/OOM/capacity text/
token/batch fields, permitted owner additions and all schema/hash bounds before sealing ONE final
`resources.json` and genuine COMPLETED result. Preliminary metadata is an in-memory/local transport
materialization, not a second canonical resource Artifact or a rewrite of an earlier FAILED result.
CPU uses the same late owner/fence boundary without claiming GPU observations. The endpoint rejects
early/duplicate/mismatched resource messages, more than one roundtrip, EOF and the original absolute
deadline; no reconnect. The immutable completed1/21 CP+ACK transcript is captured at the last ACK
and remains historical even if terminal resource exchange later fails; it is not resource success
or admission evidence. Ordinary CP receive still rejects resource messages. Pure contract validators
enforce the exact permitted local→owner field delta and capacity invocation-wide bound. Bounded
canonical local bytes are retained before the callback, preventing input-alias mutation from
erasing the comparison baseline. These validators check claims, never attest a real monitor.
Missing actual owner resource/fence composition
denies completion/admission; synthetic ports do not establish independent observation.

## Ten-symbol/file map — implemented source, not an installed entrypoint

| Symbol | File and narrow source scope |
| --- | --- |
| `run_embedding_device_benchmark` (new) | `services/catalog_service/eom_catalog_service/embedding_device_benchmark_worker.py`: fixed program and existing evidence construction; no admission/owner/ranker/framework |
| `BenchmarkWorkerLocalFiles` (new) | `services/catalog_service/eom_catalog_service/embedding_device_benchmark_files.py`: exact staged/input/output FD/member ownership, bounds, immutable epochs and one-write finalization |
| `native_embedding_backend_scope` | Existing `embedding_native_factory.py`: reuse mandatory admitted capture; only richer observed-backend typing if separately approved, no default receipt/main |
| `BenchmarkNativeEmbeddingBackend` (source port/value seam) | Existing `embedding_execution_ports.py`: actual encode-used token observations/rejection data, synchronize and cumulative allocator peaks, not authority or new wire messages |
| `OfflineNativeEmbeddingBackend` | Existing `embedding_offline_backend.py`: implement those observations through its same authoritative encoder, preserving existing encode/error/numerical recipe |
| `benchmark_sample_program` (source public wrapper) | Existing contract `embedding_device_benchmark.py`: validate integer ordinal and expose the already-authoritative fixed sample tuple, no schema/gate change |
| `BenchmarkWorkerChannel` | Existing `embedding_benchmark_channel.py`: one terminal resource submit/response after complete CP transcript; unchanged peer/deadline/CP checks |
| `BenchmarkOwnerChannel` | Same channel owner: mandatory actual resource finalizer/late fence for the one terminal exchange, no fabricated observations or source grant |
| `parse_embedding_device_benchmark_bytes` | Existing contract parser: exact invocation/staged/resource/result types, bounded canonical bytes; no index3FD parser copy |
| `pack_unit_vectors` | Existing `embedding_vector_binary.py` codec with public read validator: one canonical bounded f32 materialization and same finite/norm/shape rules |

The first approved source phase owns exactly ports/backend/channel, the existing benchmark contract,
three focused test modules plus native fake-library fixtures, and this note. Observed encoding
accepts1..18 texts, emits ordered actual batches≤4 and padded rows≤2048 without Torch tensors;
the normal index encoder neither constructs nor hashes observation tuples. CPU allocator fields
are absent. CUDA reads cumulative actual-device0 allocated/reserved peaks around runtime/lease
fences, never resets peaks and makes no independent whole-process claim.

The first seam-phase source tests cover fixed
sample/phase/order/QUERY provenance, actual used tokens/batches/negative no-forward behavior, cold
constructor/maxima retention, peer/FD/deadline changes, raw copied bools and local-vs-owner resource
immutability/replay. The second-phase tests below add worker clocks, FD/no-clobber output/aggregate
caps and worker close/result composition. Fake libraries/ports
test source invariants only. Actual installed capture, pre-execution prefix/loader/DAC/unit/session/
physical lease/independent monitor and six real launches remain owner gates; no source result means
executed benchmark, whole-process GPU PASS, performance superiority or activated CUDA default.
Changing the encoder's relevant module bytes requires fresh observed implementation/runtime pins
before actual installation/composition; no old protected bundle/proof is relabeled valid by these
source checks. Schemas and predeclared benchmark thresholds remain byte-identical.

## Second phase approved source boundary

The first seam phase was reviewed/committed as `550a239c`. Root approved the 343-line design
appendix frozen at `19eab053…12abf` before behavior; that remains historical design-review evidence.
The implemented source boundary is the following ten paths, not an installed launcher:

| Path | Exact approved symbol/change |
| --- | --- |
| `services/catalog_service/eom_catalog_service/embedding_device_benchmark_worker.py` (new) | `run_embedding_device_benchmark`; fixed sample/checkpoint execution and existing evidence construction; small required `BenchmarkHostOomObserver` port |
| `services/catalog_service/eom_catalog_service/embedding_device_benchmark_files.py` (new) | `BenchmarkWorkerLocalFiles`; fixed captured staging/FD/member ownership, bounded writes, sealed member pointers and epochs |
| `tests/unit/test_embedding_device_benchmark_worker.py` (new) | Synthetic observed backend/scope/channel/resource captures; deterministic clocks and all fixed program/error ordering |
| `tests/unit/test_embedding_device_benchmark_files.py` (new) | Unprivileged temporary FD/member cases; no root installation or live permission claim |
| `services/catalog_service/eom_catalog_service/embedding_native_factory.py` | Return/iterator typing only: existing no-argument scope yields `BenchmarkNativeEmbeddingBackend`, already implemented by the concrete backend; indexing callers remain compatible |
| `services/catalog_service/eom_catalog_service/embedding_execution_ports.py` | Add only `BenchmarkNativeEmbeddingBackend.cuda_oom_count() -> int | None`; allocator-peak value remains unchanged |
| `services/catalog_service/eom_catalog_service/embedding_offline_backend.py` | Implement that read from actual current-device0 `torch.cuda.memory_stats(0)["num_ooms"]`, around runtime/ownership/synchronization checks; no reset, import or device knob |
| `tests/unit/embedding_native_backend_fixtures.py` | Synthetic cumulative CUDA OOM statistic/read callback; never import real Torch |
| `tests/unit/test_embedding_offline_backend.py` | Constructor-inclusive OOM count, CPU absence, exact integer/bounds, missing/stat drift/lease/closed negatives |
| This note | Approved scope, exact evidence/clock/error/cleanup and source gate checkpoint |

No index main/stdio/stdout/stdin, JSON Schema, config, runtime-files, installer, Orchestrator,
owner/ranker or registry change is included. No public package export or dependency is added.

1. **Captured file API.** `BenchmarkWorkerLocalFiles(invocation_fd, *, profile, execution_id,
   invocation_raw_sha256)` takes an independently captured fixed profile/execution/raw pin, not
   fields derived from the untrusted invocation. Derive native UID from the public fixed-profile
   account and read GID from the fixed `eom-workflow-runner` account. The fixed root is
   `/run/eom-incremental-embeddings/benchmark/<execution_id>/`, with `inputs/benchmark-inputs.json`
   and `outputs/<closed alias>`; the borrowed invocation FD must match the fixed sibling
   `invocation.json` named epoch. No path/UID/GID/alias chooser is accepted from worker messages.
   Duplicate the borrowed read-only invocation FD close-on-exec; caller retains the original.
   The context owns only that duplicate plus its opened member/ancestor FDs.
2. **Read and reserve before ML.** `read_invocation()` returns the existing typed invocation after
   root UID0600/nlink1/regular/read-only/offset0 checks, ≤64KiB initial size/raw pin/canonical parse
   and held-FD epoch checks. `read_inputs(invocation)` reads the fixed alias once, ≤64MiB, exact
   raw SHA/size/canonical family type, retaining named/ancestor epochs. Require captured profile/
   execution, benchmark ID/revision, input-set and public-fixture hashes to match. Owner separately
   uses the existing full owner-request projection validator and config/bundle/proof association;
   worker cannot reconstruct authority from `owner_request_sha256` or a claimed descriptor.
   Before entering the factory open all exact4/16 empty output members and reject bounded extra/
   missing namespace entries, duplicate inodes, links or incompatible identity/access.
3. **DAC/epoch recipe.** Hold no-follow directory FDs and compare held/named dev/inode/UID/GID/mode
   (not unrelated sibling directory timestamps). Root-owned ancestors have no group/other write;
   per-execution input/output directories grant only the captured UID necessary read/traverse,
   never create/rename/remove. Read the actual fixed narrow POSIX ACL where used: input root-owned
   read-only with only the selected UID read; do not call the ACL-masked mode0600. Output directories
   are root-protected, with selected UID read/traverse and owner read group; output files are native
   UID/owner-GID0640 without extra ACLs. Root's read-only account lookup found the fixed controller
   `eom-workflow-runner` UID990/primaryGID1000; source derives the actual current account UID/GID,
   not those numbers as hard-coded substitutes. Exact ACLs are: execution/input/output directories
   rootUID/ownerGID, actual0750, base ownerrwx/groupr-x/other--- plus nativeUIDr-x and maskr-x;
   staged input rootUID/ownerGID, actual0640, base ownerrw-/groupr--/other--- plus nativeUIDr-- and
   maskr--; output directory rootUID/ownerGID0750, base ownerrwx/groupr-x/other--- plus nativeUIDr-x
   and maskr-x. Invocation rootUID/rootGID0600 and output nativeUID/ownerGID0640 have no extended
   ACL. Reject other named users/groups, writable grants, default ACLs or extra entries; no
   arbitrary allowlist. File GID1000 grants existing controller read/traverse, never native-worker
   membership of the `eom` group; no account/group change is authorized. Output open is only
   WRONLY/NOFOLLOW/CLOEXEC/NONBLOCK, without CREAT/TRUNC/APPEND; initial size/offset0 and nlink1.
4. **Write API and dynamic epochs.** `write_vectors(key, payload)` derives the already-frozen
   cold/query/supplementary alias from validated `BenchmarkSampleKey`, accepts exact bytes and
   writes only at its tracked current offset. Cold/query seal immediately, returning the existing
   `BenchmarkLocalBinary`; supplementary returns no premature pointer. `seal_supplementary()`
   returns its one final binary pointer. `write_evidence(message)` accepts only TokenWitness,
   InvocationTimings, ResourceEvidence or WorkerResult and derives the fixed JSON alias/type.
   `assert_current()` checks all retained input/directory/empty-or-writing/sealed member epochs.
   State is EMPTY→WRITING→SEALED, or POISONED on uncertain write; update data epoch only after a
   known owned write while structural FD/flags/offset/name remain exact. Reserve prospective total
   ≤16MiB before every bounded write, hash accepted bytes once, fsync/close once then retain immutable
   named epoch. Never reopen a sealed output, seek backward, truncate, overwrite or repair a partial.
   Worker hashes written bytes; actual closed-file byte/hash validation remains the owner's ACK gate.
5. **Worker API.** `run_embedding_device_benchmark(files, backend_scope, channel, *, entry_started_ns,
   expires_ns, host_oom_observer) -> BenchmarkWorkerResult` owns the supplied files context/channel
   for this single run, not the caller's original invocation FD or owner lease. Scope is the existing
   captured no-argument admitted native factory with richer return typing only. Entry/deadline values
   are protected caller captures, never JSON knobs; actual monotonic/performance clocks are fixed
   stdlib calls, patched only in synthetic tests. The same absolute owner deadline governs waits;
   checks before/after local phases do not replace the unit's hard180s timeout for a stuck kernel.
   Deny missing required captures and compare actual backend model/runtime/device/1024dimension/
   token2048/batch4/thread4 to the invocation before and after work. No fallback or purpose override.
6. **Actual token/vector sealing.** Iterate only `benchmark_sample_program(ordinal)`. Backend validates
   actual untruncated CPU IDs/masks/types before forward; after return the worker revalidates each
   frozen observation, matches ordered staged input SHA/count/ID hashes and real row refs, requires
   actual right/longest padding and exact purpose. A mismatched staged token witness may have already
   encoded authorized text, but can emit no vector/checkpoint success. Pack/read-validate the same
   returned vectors with the existing f32 codec before writing. Keep only bounded token samples and
   range metadata; discard vector tuples/bytes after materialization. Cold/query are closed before
   ready. Hold supplementary sample offsets/row refs until its final hash exists, then construct the
   exact vector sample tuple; seal the complete30/1 token witness once, never at early COLD_READY.
7. **Exact clocks/program.** Earliest protected-entry→factory enter is startup; factory enter→yield
   is load/hash/constructor. For each measured call synchronize, start perf-counter, encode observed,
   validate token/f32 bytes, synchronize, stop; positive actual spans only. File fsync/owner ACK are
   outside encode spans. COLD_READY1/ACK precedes all synthetic/warm work. First ordinals execute
   six valid synthetic cases×batch1/4, four exact EMPTY7/OVERFLOW8 negatives, one unmeasured full-doc
   warm-up, warm5, then query1..2×repeat1..5. Each genuine QUERY requires PREPARED/ACK before encode
   and READY/ACK after closed-file validation; owner starts true E2E before fresh authorization.
   Capacity2048×batch1/4 follows complete21 checkpoints. EMPTY must match case7 input hashes and
   absent tokenizer counts/hashes; OVERFLOW must match case8 actual counts/ID hashes≤4096. Neither
   an unexpected error nor a returned vector satisfies a required rejection. Cold-only has one sample/ACK.
8. **Actual local resources/OOM.** Read Linux `getrusage(RUSAGE_SELF).ru_maxrss×1024` directly; no
   gratuitous RSS provider/estimate. Read allocator maxima and CUDA `num_ooms` from the public backend,
   including constructor and all measured work, without resetting. CPU `cuda_oom_count` is None,
   not a CUDA observation. The required local `BenchmarkHostOomObserver.observe_delta() -> int`
   checks an independently captured exact own-unit/cgroup `memory.events` FD/named epoch and accepted
   pre-entry baseline; no worker-chosen path. Count the `oom` delta once, not additionally its
   `oom_kill` subset; owner cleanup separately vetoes any kill. Wire `oom_count` is this actual host
   delta plus actual CUDA allocator count (CPU CUDA addend is inapplicable0). Retain/document those
   distinct semantics; unknown/missing/decreasing/over-bound counters fail, never clamp or invent0.
   Read final allocator/OOM values before scope teardown and host delta after teardown; no public
   closed-backend read or claim of a model-only number covering later process/device cleanup.
9. **Close→terminal evidence.** Capacity samples store actual cumulative local RSS/allocator maxima,
   not exclusive per-probe peaks. Seal/write complete witness and timings before final local sampling,
   so large witness materialization is included in observed RSS; neither file signals successful
   teardown or completion. Exit the factory exactly once and require successful gated backend
   teardown; ownership remains held. Then send preliminary resources through the existing mandatory
   one terminal roundtrip. Independent owner monitor spans before constructor through late cleanup
   and supplies only permitted whole-process/device fields/counts and whole-invocation capacity
   bounds. Timings member exists only first ordinals. After validated response write one finalized
   `resources.json` and finally one COMPLETED result; leave no public success if
   close/resource/file fence fails. COMPLETED is evidence-program status, not source authorization,
   cleanup, numerical/performance acceptance or default activation. If later FD/channel cleanup
   fails, already written COMPLETED bytes remain historical local evidence, but the function raises;
   the owner must reject acceptance without its independent cleanup/unit/cgroup/device gates.
10. **Failure/cleanup.** Content-free stable errors distinguish input/identity/runtime/token/vector/
    write/phase/deadline/resource/teardown uncertainty. Stop on the first unexpected error; no second
    constructor/inference/connection or later phase. Attempt all owned FD/channel cleanup and factory
    exit even on exceptions, preserving the primary error plus teardown uncertainty. Only already
    sealed vector members with a valid exact program prefix may enter a FAILED result; if a poisoned
    supplementary file prevents its pointer, truncate the result's metadata prefix before that first
    missing sample, never the file. Incomplete token/timing/resource evidence is absent. Write a
    FAILED result only when its untouched precreated member/epochs/budget remain safe; otherwise raise
    and preserve partial bytes for the owner. Cleanup neither deletes members nor releases capacity.
11. **Focused gates before freeze.** Test all six launch ordinals/30-or1 sample/1-or21 checkpoint
    identities, QUERY waits and purpose spaces, actual token/hash/right-padding/capacity/negative
    no-forward proofs, cold constructor spans and ACK exclusion, actual cumulative RSS/CUDA OOM and
    host baseline semantics, whole/local resource immutability, missing/revoked captures, corrupt
    raw/epoch/FD/ACL/member/offset/append/link cases, preallocation bounds and partial write/fsync/close
    failures, one-write result and every exit path. Source-only fakes cannot attest real admission.
    Run explicit API tests plus API/core strict typing/Ruff/format on the owned Python paths; preserve
    old index/factory/encoder/receipt regression. Actual protected entry/main/session/cgroup/host observer,
    staging/DAC/unit/device ownership/monitor and six real launches remain owner composition gates.

## Source-only checkpoint — 2026-10-13 UTC

The explicit API eight-suite gate passed **619 tests in 37.50s**: worker, files, offline backend,
native factory, native stdio, benchmark channel, benchmark contracts and historical local adapter.
Both explicit API/core strict mypy passed the nine owned Python files; API Ruff and format-check
passed the same nine. Synthetic libraries, account captures, host OOM/resource ports and temporary
file ACLs establish source invariants only, not a protected installed prefix or actual GPU observation.
The ten paths above are frozen for root's independent review/gate/commit; no new dependency or
schema bytes changed. Relevant encoder bytes require newly derived implementation/runtime pins.

The required actual root-captured factory/entrypoint, current source authorization, fixed staging
DAC/unit/cgroup host observer, physical CUDA ownership/independent monitor, six real benchmark
launches and conditional default activation remain unexecuted. This checkpoint does not complete
the actual benchmark goal or authorize installation/runtime mutation.
