# Same-root immutable read reuse: live timeout diagnosis

2026-10-16 UTC. Source implementation/validation in progress, not an operating PASS.
Actual evidence is in the
[release preparation and C1 discovery](../operations/C5_OBSERVATION_RELEASE_PREPARATION_2026-10-16.md).

The actual authorized original HTTP request reaches READY and exact replay, then
its context read503 ends at30039.625ms, the fixed Catalog-client deadline. Source
inspection shows `CatalogSimilaritySessionContextReader` prepares a full population;
`read_similarity_views_in_session` recaptures it before reading and again at its
end; the pure composer then performs another full reauthorization capture. This
is four population materializations. In addition, the completed QUERY owner makes
several current anchor/control reads, each constructing its own immutable Artifact
reader. These are identified repeated work, **not yet a measured decomposition of
the live30s**. Do not assert the server finished successfully after disconnect.

## Required design before changing the existing read boundary

1. **Responsibility:** extend the existing Catalog/QUERY read adapters, not a second
   search engine or an async retry queue. Keep genuine QUERY and source authority.
2. **Canonical source:** committed Artifact revisions and current Catalog/Identity
   records; any reused bytes/decoding are derived, never an authorization grant.
3. **Identity:** cache identity remains exact logical Artifact/revision/member/hash/
   media/schema in the existing `PinnedArtifactReadContext`, not file paths/latest.
4. **Resolution:** current caller/policy/membership/report checks stay fresh. Reader
   reuse still checks root, thread, settings, pointer and current provenance.
5. **Access:** repeated same-key immutable reads within one root; exact metadata
   lookups, selected-source scope and bounded document-view iteration.
6. **Structures:** reuse existing keyed metadata/member caches and current read
   window. No global authority/cache, new database/index/table or service.
7. **Scale:** up to1024 sources/three views; seek one physical immutable read per
   retained member per root rather than one per phase. Keep existing128MiB retained
   byte and revision/member limits; eviction must retain its normal revalidation.
8. **Concurrency:** bind reuse to actual caller/root/thread. Source/report mutation,
   permission revocation and root replacement remain explicit failures. Preserve
   the final whole-scope current check, including unselected/no-report members.
9. **Dependencies:** adapters pass the existing typed reader at its owned boundary;
   domain/wire contracts gain neither SQL nor filesystem/cache implementation.
10. **Failure/replay:** same immutable QUERY and original key only, no computation
    retry or new identity. Do not replay an expired900s session or extend TTL. Any
    eventual read deadline change must be bounded/consistent with supported source
    materialization budgets and separately verified, not the sole correction.
11. **Simpler alternatives:** just increasing30s hides repeated I/O; truncating the
    population to the two old indexed bindings changes denominator/authorization;
    cross-request permission caching is unsafe. Existing root-local immutable reuse
    and measured removal of duplicate materialization are the appropriate boundary.

Before implementation, inspect the full existing Artifact-reader and source-owner
public interfaces. Add count/timing evidence using representative synthetic inputs,
then tests for actual reader reuse, missing/hash/lifecycle changes, actor/root/thread
substitution, final reauthorization and unchanged exact results. Source call counts
and isolated benchmarks do not establish live latency. Actual-user read/replay is
still required after a compatible installed fix; preserve the prepared C5 candidate
as evidence instead of relabeling its admission for different source/wheel bytes.

## Implemented source boundary

- `CatalogSimilarityContextReadService` creates one existing
  `PinnedArtifactReadContext` for its root. It passes this through initial/late
  completed-source reads, canonical QUERY publication reads and all common source
  preparation/read/end phases. Native/read source-owner adapters accept that
  optional typed owner-local value; it is not a wire input or permission flag.
- `CatalogEmbeddingRegistryVerifier` checks root/thread/settings before using a
  borrowed reader. Registration/indexing authority cannot borrow it. Each fresh
  capture with reused bytes performs the existing three-batch current Artifact/
  producer provenance recheck. Reference controls and the outer result boundary
  independently retain their owned provenance checks.
- All four population captures and view authority checks remain. Cached immutable
  bytes do not replace source/report/membership resolution. A final current DB
  approval withdrawal is rejected even when earlier ORM metadata and bytes are
  still retained. C5's two exact-cohort captures reuse the same local reader too.
- The native execution path's optional-reader default and all released wire,
  receipt, policy, schema, claim/lease and output identities remain unchanged.
  No service/worker permission, migration, model, source selection or timeout has
  been changed. In particular the Catalog client's30s deadline is still30s.

An isolated520-member/four-phase temporary-file benchmark measured2080 physical
reads with independent readers versus520 with one root reader. One run measured
230ms versus66ms. Immutable metadata **prefetch** calls were12 versus3; these are
not total authorization/provenance SQL calls. Real fresh permission/source checks
and additional current-provenance checks remain outside that microbenchmark.
There is no timing threshold assertion. A real Catalog-adapter seam test retains
four full captures/nine scope authorizations while its one temporary immutable
member is physically read once; a late replaced approval row still fails.

Initial regression fixture failures came from synthetic methods not forwarding the
new typed internal keyword. Those seams now assert/forward the actual root reader;
late-denial assertions were not removed. One interrupted diagnostic pytest run
also hit pytest's temporary-fixture cleanup exception; no production service or
database was touched. Terminal reruns, rather than that interrupted run, determine
source acceptance. Full source/package gates and real installed latency remain
separate; actual authenticated completion is still required.

Final source checkpoint:404 related regression tests PASS in177.93s; independent
schema-resource/wheel/dependency/API/OpenAPI suite81 PASS in32.68s. Inventories
overlap and are not summed. Strict typing6 production modules, Ruff/format and
diff checks pass. The new root-reuse suite also covers wrong root/settings/thread,
registration denial, exact forwarding through every fresh phase, current control
approval withdrawal and identical outputs. Wire/schema/OpenAPI bytes are unchanged.
These are source/temporary-file/SQLite seam checks, not actual installed IAM,
operating latency, full corpus coverage or full C1–C5 completion.
