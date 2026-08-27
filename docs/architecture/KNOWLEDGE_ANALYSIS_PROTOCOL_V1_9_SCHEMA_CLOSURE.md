# Knowledge Analysis protocol v1.9 schema-closure remediation

Status: implemented design

## Decision

Introduce `workflow-role/1.9.0`, `knowledge-analysis-proposal-result@6.0`, and
`knowledge-analysis@6.0.0` as additive immutable contracts. Preserve
`workflow-role/1.8.0`, its bundle hash, workflow `5.0.0`, preset revision, and all V8 execution
records exactly as historical evidence.

The v1.9 role-input bundle must contain the transitive JSON Schema dependency closure required by
`KnowledgeAnalysisRequestV6`. In particular, when Analysis V4 types reference Analysis V3 types,
both definition families are embedded and every local `$ref` resolves within the bundled schema.

## Boundary and responsibility

The workflow contract package owns role-input and role-result schema composition. The workflow
runner consumes those immutable schemas but must not repair or reinterpret them. Catalog contracts
remain the canonical source of Knowledge Analysis request and proposal domain schemas; the workflow
package materializes a deterministic, self-contained validation bundle at the protocol boundary.

## Canonical source and revision model

- Logical protocol: `workflow-role`
- Historical pinned revision: `workflow-role/1.8.0`, unchanged
- Corrected pinned revision: `workflow-role/1.9.0`
- Historical workflow: `knowledge-analysis@5.0.0`, unchanged
- Corrected workflow: `knowledge-analysis@6.0.0`
- Historical preset revisions and batches remain immutable.
- A new released preset revision may select v1.9; no existing execution plan is rewritten.

The schema-bundle SHA-256 is the immutable content identity. Protocol version and bundle hash remain
separate values and the persistence layer rejects a version-to-different-hash collision.

## Pointer and resolution checks

Before worker submission, resolution requires an existing workflow definition, exact result schema,
exact protocol version, persisted protocol bundle hash equality, a released preset revision, a pinned
capacity policy revision, one matching plan step, and a schema-valid role input. Every `$ref` in the
self-contained role schema must resolve locally. Dangling references fail before Job creation.

## Access patterns and data structures

Schema dependency traversal is a small directed graph. Definitions are keyed by stable schema-family
name in dictionaries, and dependency families are accumulated in an insertion-ordered set-equivalent
map before deterministic serialization. Lookup and deduplication are O(1) average per family; schema
visitation and closure validation are O(V + E) over definitions and references. Scale is bounded to a
handful of versioned schema families, so no persistent index or cache is needed.

## Transaction and concurrency boundary

Schema composition is pure and occurs before the Job transaction. `ensure_protocol_version` is the
only persistence boundary: concurrent registration of the same version and same hash is idempotent;
the same version with a different hash fails closed. Existing v1.8 rows are never updated.

## Dependency direction

Catalog contracts define Knowledge Analysis domain schemas. Workflow contracts import and bundle
those public contracts. Runner and orchestrator application services consume the workflow contract.
No domain package imports runner, PostgreSQL, filesystem, systemd, or Codex adapters.

## Failure, retry, and idempotency

The failed V8 batch and its failed first range remain terminal historical records. They are not
retried or migrated. A corrected batch requires a new explicit batch authorization and a new
idempotency key. Each range retains a maximum of one submission attempt and no automatic retry.

## Alternatives

Changing v1.8 schema composition or supplying an ad-hoc validator registry would make the historical
version validate different bytes and violate protocol immutability. Granting broader database access
or bypassing JSON Schema validation would not address the dangling reference. An additive v1.9
contract is the smallest durable correction.

## Required verification

- Pin the exact historical v1.8 bundle hash.
- Prove v1.8 still reproduces the historical dangling references.
- Prove v1.9 has no unresolved local or external references.
- Validate a production-shaped multimodal `RoleWorkerInput` under v1.9.
- Prove v1.8 and v1.9 protocol rows coexist and hash conflicts fail closed.
- Prove the new workflow compiles to result schema `@6.0` and v1.9.
- Prove runner preflight reaches Job creation eligibility without creating a live Job.
- Preserve batch one-shot and immutable source-revision pointer tests.
