# Incremental-index consumers and immutable historical reads

2026-10-18 UTC. Necessary completion of the original System RAG goal, not a new search service.

1. Responsibility: existing Catalog/Orchestrator reference readers must consume the growing INDEX18 namespace for new operations while preserving exact historical context reads/replays.
2. Canonical sources: protected current reader/QUERY configuration for initial selection; the original stored Workflow/request and its registered immutable index revision/Artifact/hash for historical selection. Namespace is not permission.
3. Identity: keep index logical ID, revision ID, Artifact member and hash separate. Preserve original C1 operation/key/Workflow/request/result bytes; never recalculate them against a current head.
4. Resolution: validate the exact registered revision and Artifact lineage. Permit only supported OCCURRENCE_BACKED_PAST_EXAM or ALL_ADMITTED_GRAPH_ITEMS populations with identical configured corpus/storage partition, view, encoder space, recipe and projection. Existing fresh actor/source/Graph/policy/lifecycle checks and full-manifest/authorized-subset validation remain mandatory.
5. Access pattern: at most three pinned views, exact primary-key/revision lookup, deduplicated map and stable ordered validation. Initial selection alone may resolve the explicitly configured current namespace head.
6. Structure: reuse existing typed Catalog owner/verifier interfaces; introduce only a small operation-local selection/value or public adapter method shared by Catalog and runner. Do not mutate a global owner or duplicate resolution code.
7. Scale/complexity: one bounded batched indexed read plus O(v) validation for v<=3. Reuse materialized immutable pointers and existing read windows; no extra Artifact copies, repeated full scans or N+1 queries.
8. Transaction/concurrency: select metadata and validate pointers in the existing read transaction/window; keep the original request and source fences. No DB schema, index, queue, durable cache or new write is required.
9. Dependencies: application services select the read operation; Catalog infrastructure resolves registered metadata through public supported methods. Runner consumes that public boundary, never private Catalog modules/tables.
10. Failure/retry: missing/stale/hash/cross-corpus/space/recipe/projection/unknown-population targets fail explicitly. Do not substitute latest, broaden source classes, rekey, rerun the model or repair historical rows. Replays return or validate their original immutable output.
11. Simpler alternative: configuration-only ALL selection breaks historical OCC reads; leaving readers on OCC strands new ALL bindings. An operation-local pinned read is the smallest compatible correction. New queries select existing INDEX18 CONTENT_ONLY ALL namespace, retaining PAST_EXAM source-class restriction and the released access policy.

Verification: current ALL plus original OCC public/context/replay success; exact target/hash/schema/media/permission failures; three-view mismatch/duplicate rejection; original-key replay performs no new current-head lookup; guarded PostgreSQL tests where persistence is involved. Source, installation, activation and actual delivery remain separate evidence.

## Capture-local extraction relation lookup — 2026-10-18

The authenticated15:40 C1 read completed its Catalog checks after the API's
30-second deadline. Its first population admission consumed6,049ms; completion
of the full read was recorded at15:40:35.138 UTC. This is not a performance PASS.

The existing `ItemSourceReadRelations` already owns bounded per-capture component,
decision and work-unit maps. However, the canonical past-exam resolver still
looks up acceptance, extraction batch, source bundle revision and layout by
`session.get` for each Item. Artifact prefetch's discarded local tuples do not
guarantee their survival in SQLAlchemy's weak identity map. Prove the repeated
queries with a resolver-level count before claiming an optimization.

If confirmed, extend that same relation owner with four typed exact-ID maps:

- Canonical source remains the current relational rows plus exact immutable
  provenance members. A map hit is not source admission or authorization.
- Keep Item/revision/Artifact/revision/hash and original index references separate;
  no stored values, schema, index, protocol or namespace meaning changes.
- Access is bounded batch lookup followed by O(1) membership/lookup per Item;
  retain O(n) rows for at most the existing source/work-unit budgets. Fetch only
  selected dependency IDs, using the existing indexed primary keys.
- Layout IDs come only from the current batch's exact typed request references.
  An unselected/missing dependency fails through the existing resolver; never
  fall back to latest or lazily expand a prepared capture.
- Preserve current transaction/session/thread guards, fresh rebuilding on every
  capture, deterministic decision/work-unit order and duplicate rejection.
- Keep standalone resolution's current behavior. With a prepared relation set,
  its lookups must use that set rather than relying on ORM object retention.
- Existing Artifact byte/schema/media/hash checks, actual actor/Graph/policy
  fences and late population/provenance revalidation remain unchanged.
- Infrastructure owns the SQL batching; domain/contracts gain no database import.
  No DB writes, migration, retry, new job/key or shared/global cache is introduced.

Regression evidence must exercise the full resolver rather than only constructing
the maps: bounded query counts across increasing populations, absence of per-Item
metadata SQL, fresh capture after changed/deleted dependencies, and unchanged
missing/ambiguous/stale/hash outcomes. The simpler alternative, retaining only
the prefetch tuples, still leaves correctness/performance dependent on incidental
ORM reference lifetime and does not define explicit selected dependency lookups.
Do not weaken revalidation of model-constructed input or raise timeouts as a
substitute for this measured access-pattern correction.

Implementation checkpoint16:01 UTC: the full synthetic canonical resolver
reproduced2,180 extraction metadata `get` calls for545 Items before correction.
The existing capture owner now retains four typed maps; production supplies its
same exact Artifact reader and existing provenance decoder. Metadata-only callers
retain the explicit standalone layout lookup rather than inventing layout IDs.
No Artifact copies, shared authority cache, timeout change or migration was added.

Source verification:231 focused unit tests, strict mypy on both changed source
files, Ruff/format on five Python files and independent boundary review PASS.
The official disposable PostgreSQL `chat-knowledge-tests` gate passed120 tests
in40.36s, including eight new full-resolver cases:16/545 Items across four fresh
captures, actual constant SELECT counts for all four dependency families,
missing/changed row rejection, canonical standalone output equality and indexed
exact-key query plans. The initial97PASS/23ERROR run is preserved: inherited
temporary fixture tables were created twice; only that fixture setup was fixed.
The official gate now includes the new file, so this protection is not temporary
operator-only coverage. These are source/disposable-DB results, not proof that
the deployed C1 read now finishes within its deadline.
