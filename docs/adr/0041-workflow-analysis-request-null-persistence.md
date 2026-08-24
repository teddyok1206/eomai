# ADR 0041: Preserve required nullable fields in persisted analysis requests

## Status

Accepted.

## Responsibility and boundary

Knowledge Analysis request schema `knowledge-analysis-request/2.0` requires both
`predecessor_analysis_run_id` and `prior_graph_snapshot`, while allowing either value to be `null`.
The workflow repository previously serialized every `WorkflowRequest` with recursive
`exclude_none=True`. That representation was convenient for unrelated optional item-workflow
fields, but it removed the two required analysis fields after the request had passed JSON Schema
and typed validation. The runner consequently could not reconstruct the immutable request at its
agent-execution boundary.

The repository now remains the sole persistence adapter for workflow request documents. It keeps
the established sparse top-level representation, but serializes a present typed analysis request
without excluding `null`. JSON Schema and `KnowledgeAnalysisRequestV2` remain the authoritative
protocol contracts and their immutable bytes are unchanged.

## Canonical source, pointers, and access pattern

The canonical source is the validated `KnowledgeAnalysisRequestV2`, including its immutable source
revision pointer, preset revision pointer, risk-policy revision pointer, optional pinned predecessor
and graph-snapshot pointers, and `request_sha256`. The dominant operation is one key lookup followed
by constant-size typed deserialization. No large payload or artifact bytes are added to PostgreSQL.

For workflow rows written by the defective serializer, the reader may restore only the two absent
nullable keys and only for schema version `knowledge-analysis-request/2.0`. Typed validation then
recomputes and checks `request_sha256`, so the compatibility path cannot invent a predecessor or
silently resolve a latest graph revision. The persisted historical row is not mutated.

## Transaction, concurrency, retry, and idempotency

New workflow creation writes the complete nested analysis request in the existing creation
transaction. Its business fingerprint intentionally retains the historical semantic normalization
that treats an omitted nullable value and explicit `null` equivalently; this prevents a repaired
writer from bypassing active/successful-equivalent deduplication. An expired command lease may be
reclaimed through the existing queue contract and resumes the same step attempt and deterministic
job idempotency key. No analysis API submission is replayed.

## Dependency direction and alternatives

The compatibility logic belongs to the workflow persistence adapter, not the domain model or API.
Changing the immutable JSON Schema to make the fields optional was rejected because it weakens the
pointer contract. Making every Pydantic nullable field optional was rejected because direct typed
callers could then bypass schema-required presence. Serializing all top-level `None` values was also
rejected because it would alter unrelated historical workflow representations without need.
