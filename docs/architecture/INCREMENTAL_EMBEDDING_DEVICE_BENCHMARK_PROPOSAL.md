# Native CPU/CUDA device benchmark — protocol and owner-path proposal

2026-10-12 UTC. **SOURCE_CONTRACTS_ONLY / NOT_INSTALLED / NOT_EXECUTED / NOT_ACTIVE**.
This is the next concrete route to the requested actual benchmark and, if CUDA is superior and
all other gates pass, actual default activation. A proposal or performance verdict is not completion.
Only the additive schema/mirror/frozen values/registration and synthetic contract tests now exist.
No worker/owner, migration, install, model/GPU invocation or runtime change is made here.
The small source-only real-row ranking seam below is now implemented; it is not an executed benchmark.

Authoritative criteria are [GPU runtime design §§6–8](INCREMENTAL_EMBEDDING_GPU_RUNTIME_DESIGN.md#6-실행-전에-pin하는-작은-benchmark-protocol)
and the existing pure `embedding_device_comparison.compare_embedding_device_performance`.
The [native admission proposal](INCREMENTAL_EMBEDDING_RUNNER_ADMISSION_PROPOSAL.md) implements
source contracts only; its index purpose does not authorize this benchmark or QUERY work.

## Eleven-item boundary note

1. **Responsibility/boundary.** One fixed operator-only native owner purpose,
   `LOCAL_EMBEDDING_DEVICE_BENCHMARK`, measures the predeclared CPU/CUDA recipe. Catalog supplies
   currently authorized pinned source/projection values; Orchestrator owns admission, six serial
   isolated child launches, live command/capacity/physical-lease fences, validation and Artifact
   publication. This is neither a Codex role/Workflow nor an indexing/background-service grant.
2. **Canonical source.** Reuse the official Catalog/Orchestrator source-resolution boundary and
   one canonical legacy protected model payload. A pointer-only benchmark plan binds source,
   accepted profile/report/evidence, Graph/policy, view recipe and exact DOCUMENT/QUERY text hashes.
   Text bytes are materialized only into protected local input/approved Artifact boundaries.
   Benchmark vectors, token witnesses and timing/resource traces have one canonical result file set.
3. **Identity/revision.** Benchmark logical ID, immutable benchmark revision, recipe revision,
   owner Job/child execution IDs, input semantic hash and Artifact raw-member hashes stay distinct.
   CPU/CUDA numerical spaces are distinct; within each device DOCUMENT and QUERY spaces are distinct
   even if a reviewed model has equal prefixes or happens to emit equal bytes. Benchmark row refs
   are small immutable real profile/view/text values, not fabricated registered encoding rows.
4. **Pointers/checks.** Resolve exact immutable existence, schema/version/media, lifecycle,
   permission, size/raw SHA and semantic closure before staging, launch, each query retrieval,
   publication and replay. Compare requested bundle/proof/space/profile with independently
   released owner configuration and actual observation; parsing a descriptor is not authority.
   Workers receive fixed local FD/member aliases, not credentials, roles, DB/NAS URIs or path choices.
5. **Access patterns.** Exact plan/member lookup, bounded stable row ordering, one streaming
   verification per immutable input/payload/runtime snapshot, six ordered launches, two fixed query
   lookups and O(Nd) exact ranking/comparison. This is not a 520-profile/1,560-view rerun or latest scan.
6. **Structures/indexes.** Frozen recipe/row/space values, tuples for prescribed repetitions,
   maps/sets for row/member/phase uniqueness and existing indexed Job idempotency/events/capacity.
   No new queue, generic registry, lease table, global model cache or binary/text DB column.
7. **Scale/cost.** Exactly six admitted profiles, their available three views (at most 18 DOCUMENT
   rows), exactly two QUERY rows, eight public synthetic cases and one bounded capacity fixture.
   Envelope ≤64 KiB, staged text/control input ≤64 MiB, numerical output ≤16 MiB and ≤64 fixed
   output members. Initial payload/runtime verification is streaming O(bytes); row comparison is
   O(Nd), pair/rank checks O(N²) for N≤18. Immutable hashes are reused through epoch checks.
8. **Transactions/concurrency.** Authenticate/fence current operator and pin the plan in short
   owner transactions; never keep SQL open through inference. One native launch is active at a
   time; CUDA additionally holds the admitted physical GPU lease until output and process/cgroup/
   device cleanup are proven. A timed-out/uncertain child retains capacity and is reconciled by
   its original operation key, not bypassed with a new ID. Source/authority revocation still wins.
9. **Dependency/ownership.** Contracts are IO-free. The protected standalone worker composes
   the configured bundle resolver, installed numerical observer and existing FP32 offline backend.
   Catalog core/API gain no ML dependency. Orchestrator uses supported source/Identity/publication
   ports, not private repositories or image/Catalog helper imports. Reuse handoff/unit patterns,
   not the legacy CPU experiment's installed protocol, account, manifest or environment.
10. **Failure/retry/idempotency.** Missing source/query/view coverage is `INSUFFICIENT`, never
    substituted. Hash/schema/token/runtime/authority/finite/rank/resource/isolation errors fail
    explicitly. GPU busy is `WAIT_FOR_GPU`; no implicit CPU retry, batch/token/dtype reduction or
    threshold/timeout increase. Known validated output is republished by the same key; uncertain
    execution requires supported cleanup/reconciliation. Preserve every failed revision/result.
11. **Simpler alternative.** `IncrementalEmbeddingInput/1.0` and `encode_incremental_batch` are
    DOCUMENT-only; legacy experiment1.0 borrows a document vector as its query. Neither represents
    this genuine QUERY/DOCUMENT measurement. One fixed owner use case and native stdio leaf are
    smaller than a fake Codex Workflow, new scheduler or broad benchmark framework.

## Fixed workload, purpose family and measurements

The initial candidate is reviewed BGE: upstream revision
`9a0624b896d81da7492a910ffa53731274b6cf3d`, dimension 1024, maximum tokens 2048, FP32 eager
eval/inference, host L2 and existing f32 codec. CPU uses the separate protected successor
`/opt/eom/conda/envs/eom-embedding-index-cpu` with `torch==2.7.1+cpu`; CUDA uses
`/opt/eom/conda/envs/eom-embedding-cuda` with `torch==2.7.1+cu128`. Historical CPU1.0 is untouched.
Weights/tokenizer upstream revision and every file SHA, tokenizer options, prefix/pooling recipe
and relevant encoder/L2/f32 code identities must match. Installed numeric/device/runtime pins
remain independently exact per device. No cu128-in-CPU-mode substitute for the primary baseline.

Owner binds four `EmbeddingSpace` values: CPU DOCUMENT/QUERY and CUDA DOCUMENT/QUERY. A small
canonical compatible-family value excludes device/purpose from identity only after checking
the same payload/tokenizer/encoder/pooling/L2/codec recipe and both explicit purpose-prefix rules.
It is not permission to compare arbitrary spaces. Within each device both purposes use that
device's exact installed runtime descriptor. Across devices request text, order and token witness
must be identical for each corresponding purpose. QUERY always calls `encode(..., purpose="QUERY")`;
never reuse its DOCUMENT vector, index row, shard or encoding-completion event.

Selection is operator-authenticated and bounded: pin exactly six accepted source profiles through
the official current source/report/Graph/policy boundary; use the existing `CONTENT_ONLY`,
`CONCRETE_FACETS`, `METADATA_ONLY` projections. Declare tokenizer-length strata before selecting
the six and sort the selected real profile/view refs stably. The exact two requested profile/view
queries are independently rendered/token-measured for QUERY purpose, not model-created substitutes.
Preselection tokenization is an explicitly separate owner-admitted staging/preflight observation,
not a fourth cold sample or an OS-cache-cold claim. Freeze all selected IDs/revisions/hashes,
coverage limitations and actual input bytes before the six timed launches. If six eligible profiles,
two encodable exact queries, one valid view per profile or five post-self-exclusion candidate
profiles are unavailable, return `INSUFFICIENT`; do not widen the scope or replace a missing view.

| Measurement | Fixed recipe and clock boundary |
| --- | --- |
| Synthetic | Eight public cases: short Korean/formula/units/negation, exact duplicate text, empty and overflow negatives; valid batch lengths 1/4; compare full token IDs/masks/padding, order, dimensions and norm |
| Cold | Six fresh processes in **CPU → CUDA → CUDA → CPU → CPU → CUDA** order; three per device; owner admission/staging/startup/load/hash/tokenization/encode/host transfer/L2/f32/local validation included, with startup/load/encode spans separate |
| Warm | Only each device's first cold process continues: one unmeasured full-batch warm-up, then the identical full DOCUMENT matrix five times in that same process/model instance |
| Query | In that warm instance, each of two genuine QUERY inputs is encoded as an actual batch of one five times; encode and complete authorized retrieval/ranking end-to-end are separate spans |
| Capacity | One public deterministic long fixture measured at exactly 2048 tokens including the pinned prefix/special-token recipe; actual batch lengths 1 and 4 once each; no truncation or automatic shorter fixture |
| Resources | Peak process RSS ≤6 GiB; CUDA max reserved and independently observed whole-process GPU usage ≤8 GiB, OOM=0 and other GPU consumers overlapping=0; allocated alone never proves the cap |

The configured backend maximum batch remains 4/threads4; a one-row QUERY/capacity call does not
silently create a different batch-size runtime fingerprint. All phases are fixed in advance.
In the first process: measured cold DOCUMENT checkpoint, public synthetic checks, one warm-up,
five warm DOCUMENT calls, ten QUERY calls, then capacity1/4. Other cold processes perform only
their prescribed cold call and termination. Non-cold phases never enter a cold duration.
Initial per-invocation timeout remains 180s, CPUQuota400%, TasksMax64, RAM6GiB. If the first process
cannot complete its prescribed phases in the admitted bound, it fails; increasing that bound
requires an explicitly reviewed recipe/resource-policy revision, never an automatic retry.

CUDA fences synchronize before/after every wall interval, including transfer and host L2;
kernel event timing is supplementary. Use `perf_counter_ns`, retain integer raw nanoseconds,
positive integer microseconds, workload numerators/denominators and all maxima. To avoid a
conversion making a near-threshold failure pass, proposed gate inputs use CPU floor(ns/1000)
and CUDA ceiling(ns/1000); reject sub-microsecond CPU samples rather than replacing zero with one.
This conservative quantization is predeclared, not selected after seeing results. Cold means
fresh process/model load, not reboot/page-cache-cold; do not drop host caches.

## Cold checkpoint and real end-to-end query timing

One small purpose-specific stdio session is necessary. The first child closes its fixed cold
vector/witness files and emits `COLD_READY`; owner validates them and stops the cold end-to-end
clock **before** sending the matching `OWNER_CONTINUE` ACK. That child then retains the same model
instance for warm/query/capacity; a non-first cold child exits after that ACK instead. The trusted
owner descriptor fixes this role from the six-launch ordinal, not a worker-selected flag.
Waiting for final process exit before measuring cold would
incorrectly include warm/query work; starting another process would not be warm. ACKs are not
permissions or lease tokens; only the trusted parent can write the fixed control FD.

After all warm calls, and before **each** of the ten query calls, worker emits `QUERY_PREPARED`
with the fixed query ordinal/repetition and no vector, then waits. Owner validates that marker,
starts the retrieval wall clock **before** fresh authorization of the exact query and whole
candidate scope, and only after authorization sends the matching ACK. Revocation/failure sends
no continuation and terminates/reconciles the child. Worker then encodes and emits `QUERY_READY`
with the same query identity, closed vector and encode span. Owner validates its genuine QUERY
space, ranks against the immutable same-device cold DOCUMENT matrix, validates the result and
stops the end-to-end clock before acknowledging that result. This includes current source
authorization and real local retrieval/validation, not just a kernel timer or a guessed sum.
The worker cannot begin the next query before that ACK; after the last ACK it runs capacity probes
and finishes. Fixed bounded phase framing/timeouts/backpressure/FD cleanup are required before
behavior. Worker stdout is bounded protocol only; stderr is capped/redacted diagnostic output.
All checkpoints remain provisional until final output, immutable epochs and unit/cgroup/device
cleanup are confirmed; a checkpoint does not release capacity or publish an Artifact.

The first cold child of each device has exactly 21 checkpoints and 21 matching ACKs: sequence1
is `COLD_READY`; for query ordinal q=1..2 and repetition r=1..5, sequence
`2 + 10×(q−1) + 2×(r−1)` is `QUERY_PREPARED` and its successor is `QUERY_READY`. Each other cold
child has sequence1 only. The projected descriptor pins device/launch ordinal/request/input/space
identities. Reject missing, duplicate, reordered, wrong-phase/query/member/hash ACKs or checkpoints;
accept no extra phase or worker-selected repetition. The pending stdio state table is this fixed
bounded sequence, not a new reusable workflow engine.

## Exact numerical and ranking decision — unchanged thresholds

Independently validate every sample's ordered rows, dimension, finite/nonzero vectors, byte
length/raw SHA and f32 L2 absolute norm error ≤1e-5. Compare corresponding CPU/CUDA vectors:
cosine ≥0.99999, maximum normalized-component absolute difference ≤1e-4 and every measured
QUERY/DOCUMENT score absolute difference ≤2e-5. Apply the same tolerances/ranking checks to
same-device repetitions. Device raw-vector SHA equality is not required; no mixed-space index.

Use the full fixed ≤18-row matrix, excluding **all** rows of a query's exact real source profile.
Keep duplicate text rows as distinct real profile/view refs. Existing unrounded `math.fsum`
cosine/clamping and stable profile-ID/revision/hash tie prefix remain authoritative; the narrowly
needed row key adds view/text-hash only to distinguish several views of the same actual profile.
Do not fabricate profile IDs to call the old profile-only ranker. A supported typed row-rank seam
must share its existing scalar/order rule, preserving historical ranker behavior; no ANN service.

Before any result, pin the near-tie algorithm, threshold and stable key. CPU-first query reference
scores seal the concrete cluster receipt before the first CUDA result is admitted. Deterministic
complete-span clusters have CPU score max−min ≤4e-5; no transitive close-score chain may excuse
a >4e-5 pair reversal. Every candidate pair with CPU gap >4e-5 preserves relative order, cluster
order is preserved, exact ties use the stable key, and differing top5 boundary membership is
allowed only within the same predeclared cluster. Store every swap/gap; no top-K overlap shortcut
or millionths-rounded score decision. Raw float64 score/difference evidence is a bounded Artifact,
not JSON/DB float summaries pretending to prove the tolerances.

After validated timing artifacts, owner constructs the existing frozen `EmbeddingDeviceTimings`
and calls `compare_embedding_device_performance` **unchanged**. All are inclusive:

- CUDA warm full-batch median ≤CPU×0.80;
- CUDA cold end-to-end median ≤CPU×0.90;
- each query's encode median and end-to-end median independently ≤CPU×1.10;
- CUDA cold max ≤CPU cold max×1.20; retain cold3/warm5/query5 maxima and every reason.

`CUDA_PERFORMANCE_SUPERIOR` is performance only. Numerical, capacity, sandbox, physical lease,
orphan/cgroup cleanup and image/trainer contention/canary gates must independently pass. No p95
SLA or educational/recall/answer-quality claim follows from this small device measurement.

## Canonical source-contract checkpoint — no worker or owner behavior

The canonical [JSON Schema 2020-12 family](../../schemas/knowledge/embedding-device-benchmark-v1.schema.json)
and byte-identical packaged mirror now define the whole fixed protocol. The
[frozen contract module](../../packages/catalog_contracts/eom_catalog_contracts/embedding_device_benchmark.py)
implements only values, canonical serialization and resolved-value association checks.
Its one family has20 top-level message/evidence types; the remaining nested definitions are
small closed values required for the six launches, token/binary closure or existing gates.
There is no schema factory, queue, generic policy/benchmark framework, ranker or IO adapter.
The earlier inline boundary-only proposal is superseded by these canonical source files.

| Value group | Scope |
| --- | --- |
| Owner request | Six exact source/profile/accepted-report selections; Graph/policy/view recipe; stable ≤18 DOCUMENT rows and positions1/2 of exact QUERY rows; input Artifact pointer |
| Staged input | One explicit text materialization: those20 maximum real inputs, public synthetic8 and exact2048 capacity text; actual preflight token-count/ID hashes |
| Family/runtime | Ordered payload file identities and both prefixes/common encoder recipe/three relevant implementation pins; independent CPU5/CUDA20 descriptors, bundle/proof pointers and four distinct purpose/device spaces |
| Invocation | Owner request SHA plus job/execution/ordinal; fixed local-input raw SHA/size; numerical recipe/policy; no actor, Graph, source grant or filesystem path choices |
| Vector/token evidence | Fixed f32 member aliases/ranges, genuine purpose/space and ordered row SHA refs; actual IDs/masks/token types/pad token/longest padding, no duplicate profile payloads |
| Session | Exact cold checkpoint1 then ten prepared/ready pairs and21 matching ACKs for first CPU1/CUDA2; other four cold invocations have checkpoint1 only |
| Timing/resource | Cold3/warm5/query2×5 shape; raw integer nanoseconds and conservative integer microseconds; positive RSS/allocated/reserved/owner process/device bytes, OOM/overlap counts and capacity1/4 |
| Published evidence/result | Canonical per-launch Artifact pointers, complete-device records or explicit partial failure; bounded f64 score member/aligned offsets/near-tie receipt and integer decision counters; nine fixed owner gate statuses |

Phase identity is exactly:

- sequence1: `COLD_READY`, query ordinal/repetition null, closed DOCUMENT member/span;
- q=1..2, r=1..5: sequence `2+10×(q−1)+2×(r−1)` is `QUERY_PREPARED`, no vector/span;
- its successor is `QUERY_READY`, one genuine QUERY row in `query-q-r.f32` plus encode span;
- every ACK repeats execution ID, invocation SHA, sequence, phase, q/r and checkpoint SHA exactly.

The invocation SHA, not just the broader owner-request SHA, binds each checkpoint/ACK to its
exact child projection. Prepared ACK follows fresh authorization with the owner query clock already
running. Result ACK follows vector/rank validation and clock stop. The source session validator
checks identity/order/count, not real FD origin, live authorization, timing or process cleanup.
The future trusted owner/worker session still has to enforce those actual boundaries.

First-cold output has30 vector samples: cold1, six public valid cases at each actual batch1/4
(12 samples), warm5, query2×5, then capacity1/4. Empty/overflow cases7/8 at each batch1/4 have four
explicit rejection records, never vectors. Unmeasured warm-up count1 is recorded separately.
Synthetic case5/6 text and token hashes are exact duplicates. The public fixture hash is separate
from the ordered real-input set hash and is bound by the frozen recipe; no worker creates a
replacement long input or silently truncates. The predeclared three token strata cover1..2048
without gap/overlap and their six profile counts remain exact, but no performance threshold
becomes an input-overridable number.

Raw JSON is bounded before parsing: default control-envelope64KiB; a trusted caller may explicitly
select only the declared16MiB evidence or64MiB staged-member budget. Wire data cannot choose it.
Lexical nesting is limited to32 before JSON allocation; duplicate fields, float/nonfinite lexical
numbers and >20-character integer literals fail. Python dictionaries and copied/constructed models
are walked **before** model serialization: depth32, mapping/model64 fields, sequence4096,
string262144 characters and2M total nodes, with active-path cycle detection and raw declared-boolean
checks. This permits the legal worst-case token witness while denying recursion/container expansion
or a Literal serializer hiding bool/inexact values. Actual encoded byte caps and cross-field bounds
still apply afterward.

The family hash deliberately excludes model revision/runtime-version/manifest audit and device-only
CUBLAS workspace, while retaining upstream revision, all payload file hashes/sizes, tokenizer/model
rules, both explicit prefixes, the common FP32/eager/deterministic/batch/thread recipe and three
implementation identities. It is not an installed distribution proof or compatibility grant.
CPU/CUDA bundle/proof/model successor revisions cannot contradict one immutable identity.
Actual protected installed-runtime and payload resolution remains mandatory before inference.

Each launch's numerical bytes have one canonical Artifact file set; aggregate evidence references
those members rather than copying them. Public synthetic/capacity samples have no invented corpus
profile refs. All real rows keep their real profile/view/text refs; self exclusion and two QUERY
positions are retained. f32 shape and f64 alignment/range metadata are checked, but actual finite,
norm, vector/score/tie/rank comparisons and Artifact raw-byte/lifecycle/current-source checks are
owner behavior for the next reviewed source step. A counter or `MEASURED` DTO is never PASS,
authentication, cleanup proof, admission, installed acceptance or default activation.

## Minimum real owner, factory and launcher path

Proposed narrow paths, none implemented/activated by this note:

- Catalog `embedding_device_benchmark.py`: pure staged plan/row projection and correctness/ranking
  comparator using the existing vector math and pure performance gate. Supported live Catalog/IAM
  source ports supply reauthorization; this module itself grants none.
- Catalog `embedding_device_benchmark_stdio.py`: one protected native descriptor entrypoint with
  fixed phase program. A configured factory uses `ConfiguredEmbeddingBundle`,
  `ProtectedInstalledEmbeddingRuntimeObserver` and `OfflineNativeEmbeddingBackend` on the admitted
  CPU/CUDA prefix. Add only supported token-witness/synchronization/resource-boundary observation
  seams to the existing backend; do not inspect private model/tokenizer attributes or implement
  a second encoder/tokenizer/host-L2 rule. QUERY output uses the new benchmark result contract.
- Orchestrator `embedding_device_benchmark_owner.py`: one authenticated operator use case and six
  fixed serial child execution associations in existing Job/event/idempotency/capacity boundaries.
  Use an explicit native owner admission branch/result protocol, `worker_role=NULL`; no new queue,
  Codex slot, role pack or index Workflow disguise. If existing native Job stage/application guards
  cannot represent this distinct purpose, review the smallest native admission successor first.
- Orchestrator `embedding_device_benchmark_handoff.py` / `embedding_device_benchmark_systemd.py`:
  supported fixed root-staged no-follow/FD/epoch/O_EXCL handoff and fixed-template invocation/status/
  timeout/uncertain/cgroup patterns. Reuse public primitives or expose a narrow compatible seam;
  no private legacy adapter import or behavior change. Proposed fixed units are
  `eom-embedding-benchmark-cpu@.service` and `eom-embedding-benchmark-cuda@.service`, under the
  reviewed successor runtime identities and `/run/eom-incremental-embeddings/benchmark/` staging.
  Unit, interpreter, args, UID/GID, mount/device policy and output names come only from owner release.
- Orchestrator benchmark Artifact adapter: validate local numerical/witness/timing file set, then
  call the existing public `ControlFileSetPublisher.publish`. Do not broaden the DOCUMENT index
  artifact store or register benchmark/query vectors as indexed source bindings. DB stores only
  typed pointers, small immutable counts/timing values and owner events, not input bodies/vectors.

Readiness is checked before any native Job creation/claim and again immediately before launch.
Operation key binds exact benchmark/revision/request/ordinal; an existing conflicting association
is an error, not a reason to overwrite it. Actual authenticated session freshness and current
`OperatorAuthorizationFence` plus a reviewed benchmark-purpose compute policy are mandatory.
`workflow:start`, a stored permission SHA, old operator session or the separate
`LOCAL_EMBEDDING` / `local-embedding-index` service proposal alone is not a benchmark grant. The manual benchmark
does not invent a background service principal or activate the index Runner.

## Remaining gates and immediate continuation — not a deferral

1. Owner reviews the canonical source schemas/frozen models and negative-test checkpoint below.
   Only after that review implement the narrow shared row-rank/comparator extension and then the
   separately admitted worker/application behavior; current source contracts alone activate nothing.
2. Implement the one real operator-admitted native owner/factory/handoff/launcher/Artifact route;
   fail unavailable before create/claim. Install independently reviewed whole prefixes and exact
   retained archives/RECORD proofs, model/bundle/code manifests and fixed units. Preserve historical
   CPU and all earlier failed/prefetch/source evidence. A raw wheel/source PASS is not this gate.
3. Complete actual source/IAM fencing and permissions; complete shared physical lease migration,
   all-image-entrypoint drain/device/sandbox/cgroup/orphan cleanup and image/trainer regressions.
   Missing migration denies CUDA benchmark/shadow admission, not only default activation.
4. Run the public synthetic and the exactly pinned bounded real CPU/CUDA recipe above. Preserve
   every raw span/vector/rank/resource/input/authority/launch pointer and publish only after current
   source reauthorization and cleanup. Evaluate unchanged numerical/performance/resource gates.
5. If superior and all release/isolation/capacity/image gates pass, publish a CUDA-only compatible
   index successor through the official Artifact/Catalog owner, reauthorize full source coverage,
   pin genuine QUERY routing to the compatible CUDA purpose family, CAS current and actually
   activate/read back released `default_device=CUDA`. Verify bounded delta/replay, permissions,
   GPU query provenance and compatible CPU rollback. Preserve both histories; never mix spaces.

If the prescribed benchmark fails, retain CPU and the exact reasons; if CUDA is superior, stopping
at the comparison or this document does **not** satisfy the overall benchmark/default-activation
goal. This note advances that concrete path without authorizing any pending runtime mutation.

### Source verification checkpoint — 2026-10-12 UTC

Canonical/mirror schema raw SHA is
`sha256:c8105987d684f6a276fe92361b830663487bdaa5df47c1eb47b6407dd1ee07ad`.
Registration/public exports are additive. The new family is explicitly excluded from the existing
historical296-resource freeze test; its original count, byte hashes and inventory digest remain
unchanged. This is a source gate, not an installed prefix, physical lease or benchmark receipt.

- Explicit API focused contract suite:161 tests; source/legacy regression:681 PASS13.28s.
- API Ruff lint and format checks pass on all six owned Python files.
- API and core strict mypy pass on those six files with
  `--strict --explicit-package-bases --follow-imports=silent`.
- Core strict check of the whole Catalog contract package passes54 files.
- Fresh explicit API import of public Catalog contracts loads no torch/transformers/tokenizers/
  safetensors/numpy/triton modules.

Negative coverage includes exact immutable/raw/semantic input association, real rows and four
purpose/device spaces, closed CPU5/CUDA20 pins, claimed runtime mismatch, worker authority/path
rejection, missing/reordered/replayed/wrong-query checkpoint/ACK frames, exact cold/warm/query
timing counts, authorization-inclusive query totals, conservative raw-ns conversion, public empty/
overflow/duplicate/capacity fixtures, f32 range/order/alias and actual token/mask/type/padding
shape, missing CUDA independent memory observations, partial result preservation, f64 range/alignment
and integer-only decisions, duplicate/nonfinite/huge-integer JSON, pre-allocation depth/byte bounds,
and copied/constructed raw bool/extra/cycle/depth/container/node rejection before serialization,
including direct exported-hash/projection/serializer helper pre-dump guards.
All fixtures are synthetic metadata; no real source grant, installed proof, model or device was used.

### Shared scalar and real-row ranking source seam

`eom_catalog_service.inference_transfer_vectors.normalized_cosine_similarity` now owns the exact
existing `math.fsum`/clamp scalar rule. The historical profile ranker calls this same expression;
its normalization, profile ordering and returned shape are unchanged. New
`embedding_benchmark_ranking.rank_benchmark_rows` validates at most18 real DOCUMENT refs/vectors,
excludes all views of the exact QUERY profile and retains all15 maximum remaining rows, not fake
profile IDs or a top-K-only shortcut. Stable ties add view/text hash after the unchanged profile key.

The query and candidate vectors must already be finite, 1024-dimensional unit vectors; this leaf
does not repair them. Raw f32 SHA/bytes and space/provenance remain the Artifact owner's mandatory
input-resolution checks. Exactly six distinct profile identities before self exclusion and five
after it are required. Maps/sets protect row/view uniqueness in O(N); exact scoring is O(Nd),
sorting O(N log N). `cluster_cpu_benchmark_rows` groups descending scores by each cluster's full
max-minus-min span≤4e-5, never a transitive close-score chain. Exact ties retain the stable row key.

These are frozen local values, not new lifecycle entities, cross-service grants or JSON float
evidence. The owner must still seal the actual CPU float64 score/cluster receipt before CUDA and
validate all repetitions, rank decisions, timings, resource/isolation/cleanup gates. No new
dependency, DB/index, worker transport, model run, Artifact or default activation is introduced.
The HOST_L2 module's source SHA changes in a successor runtime descriptor; historical installed
bytes/proofs are not edited or silently treated as the new proof. This is a narrow supported reuse
seam, not a second encoder/ranking implementation or completed device comparator.
