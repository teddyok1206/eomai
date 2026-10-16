# Fixed exam-cohort similarity observations (C5)

Status: source implementation work, not an installed or activated feature.

This is the C5 consumer of the original
[incremental similarity design](SYSTEM_RAG_SIMILARITY_AND_INCREMENTAL_EMBEDDING_DESIGN.md).
It observes the exact ordered25 revisions already selected by the existing Assembly
cohort contract. It neither creates Items nor changes approval, production, Assembly,
or HWPX eligibility. Numeric proximity never means equal solutions or rejection.

## Boundary and modeling decisions

1. **Responsibility:** a read-only Catalog application composes observations from
   official source/report reads and pinned DOCUMENT indexes. No worker SQL/NAS access,
   new search engine, QUERY encoding, model run, or automatic regeneration.
2. **Canonical source:** existing approved Item revisions, accepted solution reports,
   Graph/access-policy revisions and committed vector/index Artifacts. The observation
   is derived, not a second Item registry or canonical vector copy.
3. **Identity:** reuse `mock-exam-assembly-cohort/1.0`; its ordered membership hash is
   independent of an Assembly logical/revision identity. An observation request and
   result have separate canonical hashes; no existing manifest is rewritten.
4. **Pointers:** pin exact Graph, policy, source/report/profile and up to three index
   revisions. Each view lists at most25 source-position-to-DOCUMENT-row references;
   pairs refer to those positions, rather than duplicating row pointers300 times.
   Official resolution checks permission, lifecycle, media/schema, identity and hashes.
5. **Access patterns:** one exact25-member capture, maps keyed by revision/position,
   one numeric decode per selected shard/view and bounded ordered pair enumeration.
   No25 independent corpus searches or implicit latest fallback.
6. **Structures/indexes:** frozen tuples for authored order, sets/maps for membership
   and uniqueness; existing indexed registry lookups and shared read window. No new
   table, queue, index, migration or persisted cache.
7. **Cost:** at most3 views,25 vectors/view and300 pairs/view. Pair arithmetic is
   O(V*n²*d), necessarily proportional to the requested pair output, with n=25,
   V<=3; pointer output O(V*n), numeric pair output O(V*n²). Materialized numeric
   memory is O(V*n*d), not a copied corpus. Responses are bounded to1MiB.
8. **Concurrency:** actual caller and current policy are checked at the existing
   Catalog root transaction/read window and reauthorized before return. The policy
   must permit25 source results; top_k=1 must not bypass that ceiling. Concurrent
   revocation or changed report membership fails explicitly, not as an old grant.
9. **Dependencies:** contracts own schema/frozen values; pure composition owns pair
   arithmetic; the existing Catalog registry adapter owns SQL/filesystem authority.
   No contract imports service infrastructure. No additional dependency is required.
10. **Failure/retry:** missing accepted reports, absent pinned views and partial
    bindings have exact member/view coverage, never zero-score fake vectors. Invalid
    source/index/hash/authority fails closed. Read replay uses identical pins and
    current authorization, without writes, new keys or model retry.
11. **Simpler alternative:** reusing authoring similarity by inventing an anchor or
    relabeling a DOCUMENT row as QUERY would be shorter but false. This separate
    pair-observation contract reuses document validation and owner resolution while
    keeping authoring's PAST_EXAM/purpose restrictions intact.

## Output meaning

CONTENT_ONLY measures textual proximity; METADATA_ONLY measures category/concept
signals; CONCRETE_FACETS measures extracted concrete features. Keep them independent.
Rounded cosine millionths are display observations, not probabilities, rankings,
proof of shared core insight, or educational approval. No aggregate pass/fail
threshold is introduced. Missing solution evidence is visible even if another view
can be read; it cannot be converted into a positive same-solution judgement.

Every available view includes all combinations of its available member positions,
in authored-position order, not only favorable/high-scoring pairs. Completeness is
relative to all25 members and the explicitly selected views, not the entire corpus.

## Acceptance / activation boundary

Protocol/schema/hash/order/coverage and pure numeric tests come first. The owner
adapter must then exercise exact selected-source capture, shared pinned reads and
end reauthorization without relaxing old consumers. Finally an explicit existing
Assembly/production read composition and installed authenticated smoke are required.
Source tests alone do not complete C5 or the full goal. Missing Graph membership,
reports or an authorized25-item policy remains explicit, not permission to extend a
policy or insert historical data. No new25-item generation/HWPX cycle is required.

## Source checkpoint, 2026-10-16 UTC

- Schema2020-12 is registered as `system-rag-exam-observation` with a byte-identical
  packaged resource and strict frozen Pydantic values. All predecessor resources
  remain unchanged. A result has25 ordered source/report references and up to3
  independent view observations, not query execution or model reasoning claims.
- `compose_exam_similarity_observation` reuses shared source/binding/index closure
  and public unit-vector validation; it never normalizes malformed stored values.
  Identical source-neutral encoding rows may legitimately serve multiple sources:
  the same vector is decoded once, not fabricated as multiple canonical copies.
- `CatalogEmbeddingRegistryVerifier.observe_exam_similarity_in_session` uses the
  actual caller's existing root, exact25 selected IDs and top_k25 policy ceiling.
  All view reads reuse one capture/reader window. A separate capture owner performs
  the final fresh full-cohort/report check; no cached capture serves as that check.
  Root replacement/inactive/nested roots and service identities are rejected.
- Existing reference-purpose/PAST_EXAM/topic/unit restrictions are unchanged. Only
  document-owner configuration, resolved-source projection and pinned-index read
  error mapping are shared; they do not create a generic permission grant.
- Final combined contracts/composition/owner/reference/private-context/binary suite:
  **300 PASS in35.63s**. Separate resource/wheel/dependency suite: **82 PASS in22.86s**.
  These suites overlap and are not summed. Strict typing of5 production modules,
  Ruff/format and diff checks pass. Initial fixture round-trip expected bytes in an
  object-only parser; corrected the fixture to JSON-decode explicitly, not loosen
  the protocol. No DB mutation test is needed for this no-persistence change.
- No production DB, source/report/Graph policy, INDEX/QUERY runtime, GPU/device,
  model or HWPX output was changed. Source and synthetic-owner tests are not an
  authenticated live C5 result. Next: existing Assembly read application/compatible
  transport exposure and bounded actual-user read under the unchanged policy.
