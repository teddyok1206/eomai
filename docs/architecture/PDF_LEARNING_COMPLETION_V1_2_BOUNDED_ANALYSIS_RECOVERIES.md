# PDF Learning Completion V1.2: Bounded Analysis Recoveries

1. **Responsibility and boundary.** The Catalog Stage-C source proves the analysis history for the
   exact 520-item PDF cohort. The Orchestrator remains the only component that publishes receipt
   bytes to NAS.
2. **Canonical source.** PostgreSQL `KnowledgeAnalysisRunRecord` rows and the pinned published Graph
   snapshot are authoritative. The receipt is an immutable proof, not a second mutable source.
3. **Identity and revision model.** Each terminal Item pins its Item Revision, V9 analysis request,
   accepted result Artifact Revision, and Graph Snapshot Revision. A failed retry predecessor and
   its accepted successor retain distinct immutable run and request identities.
4. **Pointers and resolution.** Existing Item, analysis-result, Graph, corpus-completion, and receipt
   Artifact pointers continue to require exact revision, schema, media type, and SHA-256 checks.
5. **Access patterns.** Resolution uses keyed sets/maps for 520 accepted leaves, their referenced
   failed predecessors, and successor adjacency. It requires exact set equality and rejects extras.
6. **Structures, indexes, and bound.** Hash sets provide membership and uniqueness; an adjacency map
   proves one successor per predecessor. V1.2 permits 1..32 recovery lineages, matching the existing
   automation retry allowlist maximum. No database or index change is required.
7. **Scale and complexity.** The scoped V9 history is at most 552 rows. Validation is O(n) time and
   O(n) memory with deterministic ordering by immutable analysis-run identity.
8. **Transaction and concurrency.** The source reads one repeatable-read snapshot; the existing
   semantic observation claim and post-publication recheck preserve replay and drift detection.
9. **Dependency direction.** The JSON Schema and frozen contract model own the bound; Catalog builds
   and validates the proof; the Orchestrator adapter implements Artifact publication; CLI only
   composes those boundaries.
10. **Failure, retry, and idempotency.** Zero, more than 32, dangling, duplicate, multi-successor,
    non-failed, hash-drifted, or extra scoped V9 rows fail closed before publication. Receipt
    publication remains keyed by the semantic completion identity and replays byte-for-byte.
11. **Simpler alternative.** Raising the old fixed count from four to six would fail if another
    already-authorized automation retry occurs before the 520-item run finishes. An unbounded list
    would exceed the deployed admission policy and weaken the proof, so a new versioned bound is
    required.

V1.0 and V1.1 retain their original schemas and exactly-four-recovery semantics. The builder emits
V1.1 for the historical collision-bearing four-lineage case and V1.2 only when that exact corpus has
a different bounded nonempty recovery count.
