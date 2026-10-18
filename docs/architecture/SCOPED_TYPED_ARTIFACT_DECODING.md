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
At that source checkpoint the follow-up was not installed. Subsequent actual
7fcd0865 installation, normal drain/restoration and startup/health are recorded
in the [operating release](../operations/SHARED_PROVENANCE_READ_RELEASE_2026-10-17.md).
The actual original context read subsequently returned503 at17:10:01, so delivery
acceptance remains unresolved. Source measurements and installed health are not
relabeled as live latency PASS.

## Bounded read-stage diagnostics after installed503

The installed7fcd0865 original context still fails503. Do not assume another
particular decoder is the remaining bottleneck or raise the30s deadline. Add
small application-side elapsed-time observations around the existing full
capture/read stages before another performance change. Responsibility stays in
Catalog; the diagnostics neither resolve pointers nor own authorization/cache.

The dominant operation is ordered measurement of a fixed stage inventory, O(1)
state per measurement and a bounded number of metadata events per read. Record
only a closed stage enum, integer elapsed milliseconds and COMPLETED/ABORTED;
never caller input, actor, query, Item/report, pointer, exception text or secret.
Use the existing structured logger; no dependency, metrics service, persistent
table/schema, configurable callback or background task. Different operations may
interleave: these events measure their own stage, not a new cross-request trace.

Recompute all source/permission/hash/lifecycle checks exactly as before. Preserve
exception identity and never let logger failure replace the business outcome.
Monotonic timing surrounds caller-owned work, not an extra DB/NAS/model operation.
Test fixed field inventory, deterministic timing, aborted work, bad logging and
unchanged existing full-capture/read regressions. Installed timing and the actual
original HTTP result remain later gates; source tests alone prove neither.

### Stage diagnostics source gate —2026-10-17 UTC

**SOURCE_PASS / NOT_INSTALLED.** The existing full source capture has five timing
scopes (locks, provenance prefetch, candidate admission, solution profiles, staged
entries); the completed-context reader has four outer scopes. They use the same
small closed enum/context manager and existing logger, not a new trace framework.
No authority/result schema or production exception handling changed.

Ten disjoint focused suites pass260 tests (92/21.80s and168/10.92s), including24
closed-field/logger/clock/exception/nesting cases, full-scope reader reuse,
snapshot/registry adapters, current source retrieval and dependency boundaries.
JUnit files `read-timing-focused.xml` and `read-timing-capture-regression.xml` are
in `/tmp/eom-provenance-read-release-BnDPXZZA`. Strict mypy3, Ruff/format4 and diff
checks pass. AST comparison of `read` and `_capture_population`, after removing
only the timing wrappers, exactly matches the pre-change business methods.
No new mutating PostgreSQL test is required by a logging-only diff; previous
persistence evidence is not presented as new execution. Actual install/observed
stage times and HTTP delivery remain pending. This instrumentation is not a fix
claim for the actual503.

Subsequent df408fef actual installation/restoration and health PASS are recorded
in the [operating evidence](../operations/SIMILARITY_READ_STAGE_DIAGNOSTICS_2026-10-17.md).
The existing observer's preparation replay was denied403 at its fresh-auth gate,
before context read. Actual per-stage measurement therefore remains pending;
do not report the new release as either measured503 or latency PASS.

## Canonical analysis metadata interpretation — design before implementation

2026-10-18 UTC. The original completed-context read on installed685 reached
Catalog but exceeded the unchanged30s API deadline. Sanitized stage observations
recorded approximately81s of server work, including four full captures with
candidate admission about7s, solution profiles about7.3s and entry projection
about3s each. Server completion after the client deadline is not delivery PASS.

1. Extend the existing root-scoped immutable interpretation boundary, not source
   admission or whole-population caching. Repeated schema/Pydantic interpretation
   of canonical analysis request/result/receipt metadata is the target.
2. Canonical sources remain the freshly selected DB rows and exact Artifact
   revisions. A temporary frozen typed interpretation is derived, never authority.
3. Keep logical IDs, revision IDs, raw Artifact hashes and semantic model hashes
   distinct. Derive interpretation identity from the complete current canonical
   JSON value, schema and trusted decoder identity; never from a row ID alone.
4. Read current rows and compare lifecycle, source, permission, membership,
   predecessor, manifest, byte count and exact historical accepted/receipt hash
   representations on every original phase. A changed value must miss or fail.
5. Access is repeated exact-value interpretation within one active root/thread.
   Canonical serialization/hashing remains O(value bytes); repeated schema/model
   decoding becomes a bounded keyed lookup. No DB query/index changes are needed.
6. Use the existing decoded OrderedDict and its32MiB/2048 limits, not another
   cache. Retain only deeply immutable typed outputs, not caller dictionaries.
   Three related solution-row models may be one small typed interpretation rather
   than three entries. At545 sources, naive separate Item/report/request/result/
   receipt entries exceed2048 and can cause sequential LRU thrashing; tests must
   report capacity/count behavior, not silently increase either bound.
7. Existing raw128MiB retention, current provenance checks and root/thread/session
   guards remain. Canonical-byte charge is not an exact Python RSS measurement.
8. Artifact/application ports may expose optional typed-value interpretation;
   Catalog's existing infrastructure owner implements it. Two actual users are
   accepted solution metadata and original candidate-analysis request decoding.
   Legacy readers retain strict direct decoding; no generic registry/dependency.
9. Public projection validators continue rejecting forged models. Any subsequent
   immutable projection reuse must use complete exact validated inputs, keep fresh
   authority checks, and demonstrate useful savings under the same shared bounds.
10. Invalid decoding is never cached. Changed input, schema or decoder cannot
    inherit success. Root exit invalidates reuse; no TTL, retry, refresh, workflow,
    model, wire contract, migration or external side effect changes.
11. Merely reducing four captures to two still costs roughly36s for these measured
    stages. Raising the deadline or reusing a captured authority population is not
    the correction. Test strict output equivalence, current-state/late-revocation
    failures, bounded retention and interpretation counts before installed replay.

An offline installed685 call-count probe used one valid synthetic solution row
four times across16 repetitions:64 request,64 accepted-result and64 receipt model
validations plus128 JSON Schema validations,2.447s total. The actual V10 request,
V10 accepted result, V9 receipt and solution-report models all pass the existing
deep-immutability predicate. This isolates uncovered repeated interpretation; it
does not profile the real545-source population or establish live deadline PASS.

### Canonical metadata source gate

`CatalogModelValueDecoder` now provides optional exact-current-value decoding on
the existing root owner. Member and canonical-value interpretations share the
same decoded LRU and unchanged bounds; canonical values are neither retained as
mutable dictionaries nor tied to a row ID. Solution metadata uses one frozen
request/result/receipt interpretation per complete input value. The accepted
JSON-mode Artifact hash and typed receipt Artifact hash retain their distinct
historical encodings. Fresh row, descriptor, lifecycle and chain comparisons
still execute after every hit. Legacy readers retain strict direct interpretation.

The authoritative solution resolver also returns its required validated
`accepted_at` timestamp. The profile adapter uses that exact value rather than
issuing a second accepted-Artifact query and interpreting the same V10 result
again. No current-time/default fallback or additional LRU entry is introduced;
every original phase still runs the complete current solution resolver first.

The focused source gate passes98 tests in11.38s, including original four-capture
root reuse, existing Artifact-model bounds/provenance and solution contracts.
Strict mypy for3 changed production modules, Ruff and diff checks pass. A545-value
four-phase count test retains545 solution envelopes alongside1090 tiny synthetic
occupancy entries:2180 interpretations become545, entries1635 and raw-byte charge
17,800,770 bytes. These occupancy values are not real Item/report memory models.

A separate finite metadata-only benchmark measured14.901s direct versus3.930s
reused (reused phases3.436/0.167/0.164/0.163s), with identical output signatures.
It excludes DB/source/IAM checks, real Item/report/provenance memory, candidate
admission and subsequent strict profile/entry projection. In particular, adding
every request/profile/entry as separate cache entries can exceed the existing
count/byte bounds. This is not evidence that the actual C1 now fits30s. Installed
verification and actual successful original completed reads remain required.

## Fresh per-capture Item relation batching — design before implementation

2026-10-18 UTC. Candidate admission still issues per-Item component, decision,
accepted work-unit and compatibility-component queries. An offline official
source-resolver seam (current SQL calls replaced by synthetic metadata only)
constructs8720 such queries for545 repetitions across four phases:4360 component,
2180 decision and2180 work-unit queries. This is not a real DB timing profile.

1. Responsibility stays in Catalog's existing source-read use case and resolver.
   Batch current relational inputs, not accepted admission or whole populations.
2. Canonical sources remain current Item revisions/components, extraction decisions
   and accepted work units. No new persistent or derived canonical record exists.
3. Key components by pinned Item revision; decisions by exact acceptance/proposal/
   item number; work units by exact acceptance/result. No current/latest fallback.
4. Preserve source/lifecycle/approval/lineage/Artifact/PNG checks and exact missing/
   duplicate behavior. All current maps are rebuilt for every original capture.
5. Pattern: one bounded set selection followed by O(1) per-source keyed lookups,
   replacing O(sources) SQL round trips and repeated row materialization.
6. Use small owner-local typed relation maps, preserving duplicate tuples and the
   existing work-unit ordering. Reuse the already-supported compatibility
   `components=` argument; do not cache a compatibility decision.
7. Bound selected revision/key counts and returned rows. Exceeding a bound fails
   the complete read explicitly rather than truncating or substituting a source.
   Space is O(selected current rows); no decoded/raw cache budget increases.
8. Bind relation values to the same session/root/thread and one snapshot-cache
   construction. Never attach them to Session.info, the shared root reader or a
   cross-phase reuse context. A later phase performs fresh batched current reads.
9. Infrastructure owns SQL and maps; the existing application/source adapter
   consumes the typed values. Domain/wire contracts gain no SQL or new dependency.
10. Legacy public source helpers retain their original SQL fallback. Missing,
    malformed, duplicate, withdrawn or changed current inputs retain explicit
    failure; there is no retry, model, auth, TTL, schema or migration change.
11. Descriptor indexing alone measured0.357s for2180 synthetic545-member-manifest
    lookups and is not established as the7s admission cause. Eliminating the
    demonstrated N+1 round trips at their current owner is a smaller, better
    supported correction than another root cache or removal of fresh captures.

### Fresh relation batching implementation and gates

`knowledge_analysis_sources.read_item_source_relations` reads current selected
Item revisions, canonical/compatibility components, exact decision triples and
accepted work-unit pairs in four bounded queries. The original work-unit
`created_at / extraction_batch_id / work_unit_id` order and duplicate tuples are
preserved. `ItemSourceReadRelations` checks the owning session/root/thread.
The candidate-pool owner constructs it afresh for each capture; neither the
cross-call immutable reuse context nor root Artifact reader retains these maps.
The public source helpers retain their original SQL fallback. Current Artifact,
Item/decision/acceptance/lineage and image checks are unchanged.

`tests/unit/test_item_source_read_relations.py` covers four fresh16/545-source
captures, constant query count, equal fallback output, missing/duplicate rows,
lineage ambiguity, later withdrawals and session/root/thread/selection denial.
The metadata/Artifact decoding, source, candidate admission, read-only transaction,
accepted solution, profile/item projection, snapshot and same-root regression
inventory comprises340 tests:337 PASS /3 pre-existing failures in16.09s, with
zero skips/deselections. Evidence:
`/tmp/eom-c1-consumer-u2HajatK/c1-source-combined.xml`.
The three failures are the unchanged
`test_read_only_knowledge_transaction.py::test_shared_cache_retention_bounds_fall_back_without_truncation`
parameters: scalar zero-retention fallback reads16 times instead of8. The same
three failures were separately reproduced against installed685 without the new
source path. Their assertions were not relaxed; they remain a separate source
gate correction before claiming a fully clean combined run.

The main operator ran the official guarded disposable PostgreSQL
`chat-knowledge-tests` suite:89 PASS /19.36s, including all four new
`tests/integration/test_inference_transfer_candidate_admission.py` cases:
fresh four-query545-source captures/current withdrawal, ambiguity/original
work-unit order, existing index shapes and different-session/finished-root
denial. Evidence: `/tmp/eom-c1-pool-db.OYfxwCPJ`. This verifies the real SQL on a
fresh temporary DB at head57, not production authorization or actual HTTP latency.
Strict mypy for six changed production modules and focused Ruff/diff checks pass.
No timeout, decoded/raw retention bound, schema, model or freshness setting changed.

## Truthful optional reader capability — design before correction

The three unchanged zero-retention failures expose a wrapper ownership defect:
the scalar request wrapper advertises `CatalogModelArtifactReader` even when its
delegate does not implement that optional port. Provenance therefore reads the
same member twice when retention is disabled (16 rather than8 reads for two
passes over four members). Retention must not be required for correct behavior.

1. Boundary: the existing request-local Artifact wrapper preserves only actual
   delegate capabilities; no new service, wire contract or database change.
2. Canonical source remains the exact member owned by the existing reader.
3. Logical identity, pinned revision, original member/hash/schema/media and
   request/root ownership are unchanged.
4. Raw member verification stays with the scalar base. A small model-capable
   subclass forwards the existing typed port only to a typed delegate; it does
   not implement a second scalar decoder or bypass pointer/current-state checks.
5. Access is the same bounded exact-key lookup and original ordered source reads.
6. A private factory selects the base or typed subclass by the existing optional
   protocol at the three production construction sites. No registry, flags,
   constructor metaprogramming, extra cache or dependency is introduced.
7. Bounds and complexity do not increase. Scalar zero-retention readers perform
   one read/strict decode per member; typed readers retain their root decoder
   reuse. Existing raw-byte alias/charge semantics remain unchanged.
8. Request/root/thread lifetime and four fresh authority captures are unchanged;
   neither subclass stores source admission or mutable database decisions.
9. Application consumers depend on the existing Artifact ports; infrastructure
   implements typed decoding. The wrapper forwards behavior, not authority.
10. Original failures remain explicit; no retry or fallback masks a typed reader
    failure. Tests retain the original8-read zero-retention assertions and cover
    factory capability, exact forwarding, byte bounds and late withdrawal.
11. Keeping a scalar fallback on a universally advertised model port is simpler
    syntactically but creates a second read/parse path and false capability.
    Raising retention budgets or weakening read-count expectations hides it.

Implemented by a scalar-only base, one model-capable forwarding subclass and
the private factory at all three production construction sites. The original
three zero-retention tests now pass with their8-read assertions unchanged.
The same18-suite source inventory plus four factory/forwarding cases passes:
344 PASS /15.90s, zero failures/skips/deselections. Evidence:
`/tmp/eom-c1-wrapper-final.fMWJbojA/c1-source-combined.xml`.
The four-suite wrapper/source/transaction regression is116 PASS /6.07s;
strict mypy for the changed production module and Ruff/format/diff checks pass.
No SQL or integration test changed after the official89-case temporary-DB run.
These are source/temporary-DB results, not live latency or operating acceptance.

Root final gate adds the three dependency/consumer-boundary suites to that exact
inventory: **394 PASS/26.84s**, zero failures/skips/deselections. Evidence:
`/tmp/eom-c1-consumer-u2HajatK/c1-root-final-source.xml`. Strict mypy6 production
modules and final Ruff/format/diff checks PASS. The unchanged integration file's
rawSHA256 is `88c27a8a978924a5655dedd746fff07885184c5a15f9a6d733d52ab89098fe50`;
its last write09:00:59 precedes the actual89-test PostgreSQL run09:02:27–50.
Supported cleanup completed09:03:05 for that exact disposable database only.
Original installed685, the first authenticated503 and current partial indexing
remain the operating baseline until the correction is actually installed/read.
