# Original six-launch numerical assessment

Design before behavior,2026-10-18 UTC. Extends the existing benchmark1.0
execution/timing composition; thresholds and released schemas stay unchanged.

1. Responsibility: pure comparison of the original six completed launch values,
   token witnesses and bounded immutable f32 members. No source authorization,
   installation, execution, cleanup, publication or device activation is inferred.
2. Canonical inputs remain the original request/staged-input Artifact and six
   registered launch Artifacts, resolved by the existing authorized application.
   This leaf receives their already materialized bytes; it performs no IO.
3. Keep request/Job/execution/Artifact/revision/raw and semantic hashes distinct.
   Require one original Job, six unique executions and CPU/CUDA/CUDA/CPU/CPU/CUDA.
4. Revalidate invocation/result/witness hashes, sample program, exact row order,
   purpose/space, member ranges and token IDs/masks. Resolve and validate the exact
   CPU1 reference pointer; regenerate it from CPU1's actual f32 values and require
   byte equality. Actual publication-before-CUDA remains the calling owner's duty.
5. Operations: ordered six launches, keyed member/sample lookup, paired rows,
   bounded exact ranking. Immutable tuples/frozen values and maps/sets suffice.
6. Work is O(total input/member bytes + S*N*d + Q*N^2), with fixed six launches,
   at most18 document rows,2 queries,1024 dimensions and prescribed repetitions.
   Decode each immutable f32 member once per operation; never rehash model files.
   No DB/index/cache/queue or dependency is added.
7. No transaction or side effect occurs. Concurrent calls share no mutable state.
   The caller keeps its existing source/IAM fence around Artifact resolution and
   publication, not around numerical inference performed elsewhere.
8. Contracts/f32 codec/ranking remain lower-level dependencies. This Catalog leaf
   neither imports adapters/SQL/filesystem nor reaches into private modules.
9. Invalid structure/hash/token/finite/norm evidence fails with a stable,
   content-free error; no repair, normalization, new execution or retry occurs.
   Returned norm_failures is0 because the canonical f32 reader rejects malformed
   norms. Tolerance failures are evidence counters, not exceptions or approval.
10. Cross-device cosine>=0.99999, component error<=1e-4 and query score error<=2e-5
    stay fixed. Every prescribed paired sample is compared; same-device cold,
    warm/query repetitions and repeated synthetic/capacity rows are checked.
    Directional cosine divides by the observed norms without modifying vectors;
    existing ranking retains its normalized-vector dot rule. Allowed f32 norm
    roundoff must not make two identical directions fail the cosine threshold.
    same_device_failures counts failed row comparisons plus failed repeated-rank
    assessments, not failed components. Existing CPU complete-span/tie/top5 rules
    decide rankings. The existing numerical DTO/f64 decisions describe the ten
    prescribed CUDA query rankings; additional repeated-document rank observations
    remain explicit frozen local results for the future Artifact owner, not a new
    wire schema or an invented ninth-gate PASS.
11. Comparing only CPU1/CUDA1 or supplied medians is simpler but silently omits
    cold/repeated drift and original input closure. Reuse the released program,
    f32 reader, CPU seal and ranking rules instead of another benchmark framework.

Implementation/source tests are not real six-run acceptance. Actual authorized
Artifact loading, sealed CPU chronology, nine-gate assessment/publication,
performance/device decision, coherent QUERY/DOCUMENT routing and CPU rollback
remain distinct operating requirements.

## Source verification —2026-10-18 UTC

The pure leaf now returns the existing NumericalEvidence1.0, its exact f64 member
and frozen repeated-rank observations. Positive synthetic-worker fixtures verify
six distinct original executions in one Job, the exact CPU1 f64 prefix,1,050
canonical pair decisions and150 additional cold/warm/query rank observations.
Each of the28 immutable f32 members is decoded once, not once per sample/rank.
Duplicate synthetic text is compared by actual input hash across case ordinals;
both capacity batches and every original cold/query/warm program are covered.

Four related source suites passed **140 tests/140.74s**; three additional distinct
decode-count/capacity cases passed **3 tests/26.57s** against the same production
bytes. This comprises44 new cases and99 existing CPU-reference/ranking/timing
cases, not real CPU/GPU performance evidence. Strict mypy1 production module and
Ruff/format2 files PASS. Real worker serialization/temporary f32 bytes are used
with a synthetic encoder; source/Artifact authorization and device/OS are absent.

Initial tests exposed a fixture's incorrect64KiB token-witness parser budget and
an omitted-default hash during new evidence construction; both now use the
existing explicit16MiB output budget/canonical full value. A negative fixture
also incorrectly removed mandatory COMPLETED timing/resources; it now carries a
validly rehashed foreign pin. Failed histories are not reinterpreted. Production
schemas, limits, thresholds and existing validation rules were not weakened.

No root, model, GPU, network, service, operating DB, credential or runtime/default
mutation occurred. Actual source-authorized reading/publication and the original
six-model/resource/default/rollback requirements remain OPEN.

Independent review requested a mixed-score composition test rather than only
all-equal fixture vectors. Two additional cases now exercise allowed complete-span
near-tie top5 swaps and rejected non-transitive cluster crossings. Both assert
the exact per-row f64 CPU/CUDA values, exhaustive non-aliasing offsets and sealed
CPU prefix. The root's final combined run passed **145 tests/165.36s**, comprising
46 new numerical cases and99 existing reference/ranking/timing cases. The final
test fileSHA256 is `a952ab53d8a75e9e6e5cf05ac362c278c875b66825918d54d054f401e672d0e5`.
Strict mypy1 and Ruff/check/format2 PASS. These remain synthetic-encoder source
results, not six actual model executions or authority/device-default acceptance.
