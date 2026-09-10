# Trusted evidence receipt registration gate

This note supplements [ADR 0055](../adr/0055-graph-grounded-evidence-usage-attestation.md) at
the Catalog application boundary. `WorkflowCatalogService` may register a Graph-grounded `@10`
workflow only after resolving the trusted authoring and review validation receipts. The Catalog
does not interpret orchestrator event rows directly: an `EvidenceUsageReceiptResolver` application
port owns that read-side boundary, and the SQLAlchemy adapter implements it.

The orchestrator job event is the canonical receipt source. There must be exactly one terminal
`ARTIFACT_COMMITTED` event for each pinned authoring/review job, and its bounded
`evidence_usage_validation_receipt` value must pass JSON Schema 2020-12 and frozen Pydantic
validation, including its self-hash. The adapter also binds the event to the exact succeeded job,
approved logical Artifact, approved Artifact revision, result schema, revision content hash, and
manifest hash. It rejects missing, duplicate, stale, mixed-plan, or mismatched pointers; it never
selects a latest revision or repairs a receipt.

The dominant access pattern is exact lookup for two immutable result pointers. The adapter performs
bounded set-based queries and constructs maps keyed by job, Artifact, and revision ID, plus an event
list per job so duplicate terminal events remain visible. Resolution is `O(n)` time and space for
`n=2`; there is no new persistent structure or index. Existing primary, unique, and job-event
indexes serve these lookups, so no migration is required.

Registration validates both receipts before staging derived item content or calling the Item
Registry. The registered authoring and review components already pin their logical Artifact IDs,
revision IDs, and content hashes; their metadata additionally records only the corresponding
receipt SHA-256. Complete receipts and evidence text are not duplicated into Item records. A retry
resolves the same immutable pointers and produces the same component metadata and registration
key. Resolution failure is deterministic and fail-closed, leaving no derived Catalog write.

The transaction that creates the receipt remains the orchestrator's existing Artifact-success
transaction. Catalog performs a read validation followed by its existing idempotent registration
flow; it does not mutate orchestrator tables or widen that transaction. Infrastructure depends on
the application port, while workflow contracts remain independent of Catalog and persistence.

A simpler check for an `evidence_usage` field in worker JSON is insufficient because worker output
is self-asserted. Checking only job success is also insufficient because it does not prove the
orchestrator validated the exact evidence chain. The typed terminal-event receipt is the smallest
trusted value that preserves the required provenance without copying large payloads.
