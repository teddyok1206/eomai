# Root-scoped immutable Artifact model reuse

2026-10-17 UTC, design before implementation. No wire/schema/DB change.

1. Boundary: extend the existing pinned Artifact read adapter, not a global cache
   or permission provider. Two current consumers are canonical Item decoding and
   accepted solution-report decoding. Existing legacy readers retain their path.
2. Canonical source remains the exact approved Artifact member and its original
   schema/hash. Parsed frozen models are temporary derived values, never DB/NAS
   records or a second canonical representation.
3. Identity: reuse the existing six-field member key (logical/revision/member/raw
   SHA/schema/media), root Session/thread and the actual trusted decoder function.
   No worker-selected parser, path, authority or implicit latest resolution.
4. Every model read first executes the existing member/provenance resolution and
   exact byte-count checks. A decoded hit cannot bypass a read bound, withdrawal,
   revision/manifest/member mismatch or final provenance/actor/source rechecks.
   Existing raw-member semantics retain physically verified immutable bytes for
   one root; they do not stat/hash the physical file on each cached read. This
   change preserves that boundary, rather than claiming fresh filesystem checks.
   New-root materialization must still reject missing/corrupted physical bytes.
5. Pattern: bounded keyed lookups and LRU iteration; same member decoded once
   during repeated full-scope authority captures. Source capture and report
   reference validation still run on every original phase.
6. Structure: operation-local OrderedDict beside existing raw-member retention.
   One decoder/value per member; switching decoders cannot reuse another meaning.
   Evict decoded values when their raw member is evicted. Only deeply immutable
   frozen models are memoized; mutable results remain uncached, not silently copied.
7. Bound: at most32MiB of raw-byte charge and2048 decoded members, also bounded by
   the existing128MiB raw cache. Raw charge is not an exact Python RSS bound; measure
   synthetic allocation/peak memory and disclose the distinction. Oversized values
   may be read/validated but are not retained. Complexity O(member bytes + parsed
   structure) once, O(1) keyed lookup plus existing validation on repeat.
8. Lifecycle/concurrency: the existing active root and owning thread checks apply.
   No sharing across requests, threads, roots or users; no persistent invalidation
   service. The owning use case still performs its existing fresh final checks.
9. Dependencies: application Artifact ports expose optional typed read capability;
   the pinned infrastructure adapter implements it. Existing Item/report parsers
   own schema and semantic interpretation. No decoder registry/framework or new
   dependency; domain/contracts never import infrastructure.
10. Failure/replay: invalid JSON/schema/models never become cached success. Pointer,
    approval or producer failure remains explicit even after an earlier decode.
    Reusing values does not submit/claim/retry any numerical or worker operation.
11. Simpler alternatives: raising the30s timeout hides the observed failure;
    removing population/source validation weakens authority; a global parsed cache
    introduces cross-user/lifecycle risks. Scoped immutable decoding targets repeat
    work while retaining the original checks and exact emitted values.

Evidence before change: installed API/Catalog source e132c1aa matches current three
read/snapshot modules by raw SHA. The original HTTP context read lasted30018.781ms
and returned503. Synthetic three-Item/four-pass materialization profiling (no real
DB/source authority) measured0.066s warm;12 Item parses/schema validations consumed
0.047s. Cold registry initialization was separately1.968s without profiler (a cold
profile inflated this to5.9s); never extrapolate cold startup as per-Item cost.
An alternative accepted-metadata-only reparse microbenchmark saves only~0.16ms per
Item and was not implemented: its added handoff fields are not justified here.

This optimization is not proof that the operating request now fits its deadline.
Require negative/provenance tests, operation counts and bounded memory/latency
measurements, then compatible installed/live verification of the original request.

## Implemented source and evidence

`CatalogModelArtifactReader` is an optional internal port beside the existing
Artifact port. `PinnedArtifactReadContext` implements it, while legacy batch and
scalar readers keep their original path. The Item parser delegates to the same
strict JSON/schema/alias reader. The solution-report parser delegates to the same
schema/Pydantic validation and reconstructs the proposal from the **current**
receipt on every call. It does not reuse source admission, a whole projection,
accepted DB results, receipt metadata, current permissions or authority flags.

The source tests retain all four full population captures/nine authorizations.
Current bounds, exact pointer/decoder identity, root/thread boundaries, approval/
producer withdrawal, invalid content, raw/model eviction, mutable children/extras,
fresh-root physical corruption and both actual consumer call paths are covered.
Model retention is disabled for mutable results; decoding still succeeds without
reuse. No dependency, wire/schema, database or execution deadline changed.

Synthetic operation counts and bounded allocation measurements, rather than a
live-latency claim, are recorded in the
[checkpoint](../status/SCOPED_ARTIFACT_MODEL_REUSE_CHECKPOINT_2026-10-17.md).

## Shared past-exam provenance follow-up — design before implementation

Actual installed4222ca9a still returns the original context read503 at the30s
deadline. A same-session, same-key replay reproduced it while pidstat observed
substantial Catalog CPU usage; the sampled disk counters did not establish an
I/O bottleneck. A read-only metadata check found521 accepted reports/6,462,310 raw
bytes, not evidence of exceeding the32MiB model charge. A separately bounded
profile of request/result/receipt metadata is not a profile of the actual whole
read and must not be presented as its full cause or as RAG authorization.

One concrete uncovered repeated path remains: each fresh population capture
creates its own `PastExamSourceResolutionCache`. Its BATCH/ACCEPTANCE/RESULT/LAYOUT
values are not the canonical Item/solution-report decoders added above. Further,
the existing request-local Artifact wrapper does not forward the optional model
read port. Thus root raw-byte reuse does not reuse these shared, immutable source
models across phases. Preserve the four current whole-population captures and
their per-Item/run/Graph/IAM/source/report checks; do not cache resolved admission.

Extend the existing wrapper to forward the existing optional typed model port
(or decode via its existing bounded raw read when the delegate lacks that port).
Split the four existing provenance parsers into stable frozen-model decoders and
the same per-capture map/tuple indexes. The provenance cache still owns its64MiB/
1024-member/100,000-row limits and current max-byte checks. Only model parsing is
reused by the existing root reader, under its unchanged six-field key, decoder,
root/thread,32MiB/2048-member and raw-coeviction rules. No new cache, session-info
registry, DB/schema/worker protocol, dependency, authority grant or timeout.

Dominant access remains exact pointer lookup and O(member rows) index assembly;
four phases should parse retained shared members once rather than four times.
New-root/missing/hash/withdrawal and decoder/budget failures remain explicit.
Legacy scalar readers retain the original parse path. Validate forwarding,
identical indexes, wrong schema/kind/bounds and failed-decode nonretention, then
measure representative shared provenance and re-run the actual original request.
This follow-up alone is not proof that all live latency is corrected.

### Follow-up implementation/source evidence

The request-local wrapper now preserves the existing optional model read port.
For scalar delegates it uses the original raw read/decoder. One exact-size alias
references the SAME already retained bytes, so the typed fallback does not read
the scalar adapter twice. Aliases consume the existing4096-member key budget,
not an extra payload-byte charge; at the bound, normal validated nonretention
still applies. No unbounded secondary cache or global state was introduced.

The four provenance kinds have fixed trusted frozen-model decoders plus the same
map/tuple index assembly. Each phase retains its own indexes and still reads
current membership/source relations. Canonical Item/solution-report consumers
also keep their existing decoder identity and root checks through the wrapper.

Final focused gate: **154 PASS /23.30s** across shared provenance/root model reuse,
legacy provenance, scoped decoding, full-scope reader reuse, pinned context,
prefetch, retrieval, similarity-read service and dependency suites. JUnit at
`/tmp/eom-cpu-private-successor-J6OYgqP1/provenance-source-final.xml`.
Strict mypy2, Ruff/check/format3 and diff checks PASS. No schema/state/migration
changed and no new mutating PostgreSQL gate ran; previous DB evidence is separate.

An initial invocation referenced a nonexistent test filename and collected none.
The first corrected89-test run found a genuine scalar double-read introduced by
the narrower typed bound, plus a fixture expecting ValueError instead of the
preserved JSON Schema error. The bounded alias fixes the double-read; the fixture
now accepts the existing error type. The final154 includes both alias-capacity/
single-byte-charge tests and the unchanged scalar one-read-per-phase assertion.
Earlier overlapping58/89/152/18 results are not added to the final count.

Synthetic valid shared-batch/four-fresh-phase measurements (not live timings):

| Units / raw JSON | Model reuse off | Model reuse on | Full schema validations |
| --- | ---: | ---: | ---: |
|64 /241,688 bytes|188.2ms|55.3ms|4 →1|
|128 /482,576 bytes|475.2ms|108.6ms|4 →1|

Both configurations emit identical value hashes and index cardinalities. Only
existing root model retention was disabled for the baseline; source validators
and raw reads remain real temporary-file operations with synthetic DB metadata.
The benchmark measures neither operator authorization nor whole live latency.
Follow-up code is not yet installed: installed API/Catalog remain4222ca9a, and the
actual original context read is still unresolved, not relabeled as PASS.
