# One DB screen for registered and past-exam Items

Status: implementation decision, 2026-10-28 UTC.

1. **Responsibility and boundary:** Scientific Studio presents `문항 DB` and `배치` as two tabs in one DB view. The latter contains both manual assembly and the existing automatic mock-exam plan. The existing API/Catalog Graph-pinned read boundary remains authoritative; no Graph evidence, source, or item-bank API is deleted.
2. **Canonical source:** accepted Graph snapshot, immutable Item Revision, and typed examination occurrence reference. The DB view is a projection, not another corpus.
3. **Identity/revisions:** search results pin Graph snapshot, Item Revision, manifest hash, and, for past exams, occurrence revision and placement hash. Assembly saves those exact pointers.
4. **Resolution:** the API continues to validate source class, Graph pointers, lifecycle and HWPX eligibility. The Web gateway forwards only validated fields; stale/missing pointers do not fall back to latest.
5. **Access patterns:** indexed Graph candidate list, optional curriculum lookup, and past-exam year/month/item-number filtering, then bounded ordered pagination and one selected-detail view.
6. **Structures/indexes:** reuse the existing `assessment_item_occurrence_references` unique `(graph_snapshot_revision_id, analysis_run_id)` lookup and examination composite index. A correlated `EXISTS` filters candidates without a client-side full scan or N+1 lookup. No migration is needed.
7. **Scale:** one SQL query selects at most `limit+1` rows; existing page-local pointer/unit materialization is linear in page size. UI rows and assembly order remain bounded by the existing contracts.
8. **Concurrency:** Graph snapshot and cursor scope remain pinned. UI selection switches invalidate older responses. Assembly save uses the existing idempotency key and immutable placement sequence.
9. **Dependencies:** Web → BFF → Application API query → Catalog Graph/Item models. The DB screen does not query PostgreSQL/NAS directly or reproduce Graph eligibility rules.
10. **Failure/retry:** wrong filters are rejected by typed route constraints, stale cursors fail explicitly, and an unavailable candidate is not fabricated. Existing assembly/HWPX errors and histories stay intact.
11. **Simpler alternative:** merely hiding the old menu would drop year/month/number search and the 1:1 variation action; moving its DOM without a shared query would retain two competing item-bank UIs. This change consolidates presentation while preserving the supported backend contract.

The former mock-exam server-plan form remains a separate automatic assembly path below the manual DB draft in the `배치` tab; it does not silently consume the manual selection or accept unregistered legacy source documents. GraphRAG authoring/review retrieval is unchanged.
