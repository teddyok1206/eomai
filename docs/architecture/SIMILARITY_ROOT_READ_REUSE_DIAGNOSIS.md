# Same-root immutable read reuse: live timeout diagnosis

2026-10-16 UTC. Investigation/design, not an implemented fix or operating PASS.
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
