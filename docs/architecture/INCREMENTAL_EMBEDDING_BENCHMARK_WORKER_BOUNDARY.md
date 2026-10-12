# Fixed native benchmark worker leaf — design for approval

2026-10-12 UTC. WORKER_LEAF_DESIGN_ONLY / SOURCE_SEAMS_IMPLEMENTED / NOT_EXECUTED / NOT_ACTIVE.
Root approved the first narrow source phase: in-process observed-token/device/allocator APIs,
the existing authoritative sample-program wrapper and one terminal resource exchange. The worker,
files, factory/index entrypoint and all schemas/configurations remain unchanged. No source authority,
prefix, unit, ACL, install, actual model/GPU execution, database or default changes.
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

The existing backend exposes token lengths, not actual encode-used padded IDs/masks/types. Add
one explicit benchmark observation method using the same authoritative tokenizer/padding/forward/
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

Provide public backend synchronization and cumulative allocator-peak read-back seams; no peak
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

## Ten-symbol/file map — worker/files remain unimplemented

| Symbol | File and smallest proposed scope |
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

Source tests cover fixed
sample/phase/order/QUERY provenance, actual used tokens/batches/negative no-forward behavior, cold
constructor/maxima retention, peer/FD/deadline changes, raw copied bools and local-vs-owner resource
immutability/replay. Worker clock construction, FD/no-clobber output/aggregate caps and worker
close/result composition remain future behavior tests, not proven by this first source phase. Fake libraries/ports
test source invariants only. Actual installed capture, pre-execution prefix/loader/DAC/unit/session/
physical lease/independent monitor and six real launches remain owner gates; no source result means
executed benchmark, whole-process GPU PASS, performance superiority or activated CUDA default.
Changing the encoder's relevant module bytes requires fresh observed implementation/runtime pins
before actual installation/composition; no old protected bundle/proof is relabeled valid by these
source checks. Schemas and predeclared benchmark thresholds remain byte-identical.
