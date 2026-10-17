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
