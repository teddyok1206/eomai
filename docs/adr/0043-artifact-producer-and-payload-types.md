# ADR 0043: Separate Artifact producer type from payload type

Status: Accepted

Date: 2026-08-25

## Context

Knowledge Analysis support work is executed by the generic workflow `support` role. The
Orchestrator therefore records the logical Artifact's producer type from the durable Job as
`workflow_support`, while the committed immutable file-set manifest identifies its domain payload
as `knowledge-analysis-proposal`. Phase 8 publication previously required both values to be
`knowledge-analysis-proposal`. Production-shaped accepted results therefore could not be consumed
even though their Job, proposal receipt, member hashes, and accepted-result pointers were valid.

The canonical source of producer identity is the immutable Job and logical Artifact relation. The
canonical source of payload identity is the hash-pinned file-set manifest. The primary access
pattern is exact ID lookup followed by constant-time equality checks; no scan, cache, migration, or
new dependency is needed.

## Decision

Pointer resolution validates these concepts independently:

- Job task type and logical Artifact type must both equal the expected producer type;
- Job, logical Artifact, Artifact Revision, logical/revision IDs, and lifecycle must form one exact
  immutable chain;
- the file-set manifest payload type and primary member must equal the expected domain contract;
- the primary content hash and typed member pointers must continue to match exactly.

For workflow-produced Knowledge Analysis proposals the producer type is `workflow_support` and the
manifest payload type is `knowledge-analysis-proposal`. Catalog-produced accepted results retain
`knowledge-analysis-accepted-result` for both concepts.

## Consequences

The graph publisher consumes production-shaped proposal Artifacts without weakening payload
validation. A proposal stored under any other Job type, a mismatched logical Artifact, stale
revision, wrong manifest type, or failed Job is rejected. Existing immutable rows and schema bytes
are not rewritten; no migration is required. Publication remains idempotent and transactional.

The simpler alternative of trusting only the manifest was rejected because it would omit producer
lineage. Rewriting the logical Artifact type or changing generic workflow Job semantics was rejected
because it would reinterpret immutable history and couple the Orchestrator to one support payload.
