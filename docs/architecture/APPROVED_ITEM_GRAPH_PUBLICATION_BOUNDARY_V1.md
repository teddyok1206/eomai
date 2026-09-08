# Approved Item Graph Publication Boundary V1

1. **Responsibility and boundary.** The Catalog application publishes only explicitly selected,
   accepted analyses produced after the ordinary one-Item workflow. Workers neither orchestrate
   this operation nor write Graph or NAS state.
2. **Canonical source.** The current published integrated-science Graph snapshot, accepted
   Knowledge Analysis records, active/current approved Item Revisions, and their registered
   Artifact Revisions are canonical. The command carries identities, not copied Item payloads.
3. **Entity and revision model.** Item logical IDs, immutable Item Revision IDs, analysis run IDs,
   Graph Snapshot Revision IDs, Artifact IDs/Revisions, and SHA-256 values stay separate. A
   successful operation creates one immutable successor Graph Snapshot Revision.
4. **Pointers and resolution.** The boundary pins the expected current Graph revision/hash, access
   policy revision/hash, accepted analysis IDs, aligned originating Workflow IDs, and authorization
   time. It re-resolves accepted-result and source members through the existing Graph
   publication service and rejects missing, stale, wrong-media, wrong-schema, or hash-mismatched
   pointers. Only `APPROVED_ITEM` sources backed by current active V2 Item content are eligible.
5. **Access patterns.** The dominant operations are keyed lookup of the current corpus/snapshot,
   exact 25-member lookup for analysis and Workflow IDs, indexed Item/current-revision lookup,
   evidence retrieval, and append-only Graph publication.
6. **Structures and indexes.** Commands use aligned exactly-25 tuples; uniqueness is enforced before
   side effects and membership checks use sets/maps. Existing primary keys, unique idempotency key,
   source-history index, snapshot-membership key, and Item current-revision foreign key serve the
   lookups. No binary payload is persisted in PostgreSQL.
7. **Scale and complexity.** A request is exactly 25 Items. Validation and assembly are O(n),
   plus indexed database lookups and the existing bounded Graph retrieval/traversal policy. Result
   space is O(n) pointer identities; Graph artifacts remain canonical in NAS.
8. **Transactions and concurrency.** Evidence bundles and the structure artifact are immutable
   commit boundaries. All 25 additions enter one final Graph database transaction and one successor
   snapshot; compare-and-swap rejects a competing publication instead of silently rebasing. The
   publication row persists exact UTC authorization time separately from processing time.
9. **Dependency direction.** Socket/API/CLI adapters depend on this Catalog application service and
   contract. The service composes existing retrieval/publication adapters; contracts import no
   infrastructure, and workers remain unaware of Graph persistence.
10. **Failure, retry, and idempotency.** Validation occurs before evidence writes. Evidence requests
    and the final publication use deterministic keys. Reusing a caller idempotency key with changed
    input fails explicitly; exact semantic replay resolves the original immutable publication. An
    already-present analysis without that replay identity is rejected. Replay compares stored
    authorization time and the immutable analysis-to-Workflow mapping.
    Partial/stale input never substitutes a latest revision. `APPROVED_ITEM` publication adds no
    past-exam occurrence binding.
11. **Simpler alternative.** Direct SQL insertion or reusing the legacy batch selector would be
    shorter, but would bypass pointer validation, contaminate generated Items with past-exam
    provenance, duplicate orchestration policy, and weaken concurrency/idempotency guarantees.
