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
