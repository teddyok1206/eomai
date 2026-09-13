# 0079. Bind structured authoring output to the resolved evidence plan

## Status

Accepted

## Responsibility and boundary

The orchestrator owns the worker response schema for one workflow-role attempt. For an
`authoring-result@10.0` step with `EVIDENCE_CONTEXT` access, that schema must bind the evidence
identity fields to the immutable `resolved-execution-plan/3.0` that was already selected for the
workflow. The worker still chooses citations and authored content; it does not choose the bundle,
retrieval, Graph revision, or material hashes.

## Canonical source and revision model

`ResolvedExecutionPlanV3` is the canonical source. Its pinned plan revision points to one Evidence
Bundle revision, one retrieval request, one Graph snapshot revision, the semantic manifest
self-hash, and the context Artifact member hash. The generated response schema is temporary input
materialization for a single attempt and is not a new persistent revision or cache.

## Pointers and resolution checks

Before constructing the response schema, the orchestrator validates the stored canonical plan as
`ResolvedExecutionPlanV3`, including its self-hash and nested Artifact pointers. It then projects
the six worker-visible evidence identity strings as JSON Schema `const` values. Canonical result
validation and the existing pre-commit evidence receipt validator still independently resolve and
verify the manifest, context member, citations, anchors, media types, lifecycle states, and hashes.

The same plan owns the sorted `required_item_elements` retrieval filter. If it requires only an
image or only a table, the temporary authoring schema requires at least one visual and restricts
its item type to that family. If both are required, it requires both available visual positions and
states the one-image/one-table rule. The V3 plan does not own the reviewed panel count, so the
projection does not invent it: the existing material-requirement validator remains authoritative
for exact count, order, labels, DATA blocks, inquiry presence, and derived layout. The projected
citation instructions repeat the exact paths checked by the trusted evidence validator.

## Access patterns and structures

Plan lookup is an indexed lookup by workflow ID. Step selection is an ordered scan over at most 64
immutable steps. The projection performs keyed dictionary lookups, a set conversion over at most
eight required element names, and bounded schema mutations, so its time and extra-space complexity
are `O(steps + required elements)` and `O(required elements)` respectively. No large payload is
copied or persisted.

## Transactions, concurrency, retry, and idempotency

The plan is read before the worker is invoked. The generated schema has no side effect. Every
retry resolves the same pinned plan and therefore produces the same evidence constants. A missing,
malformed, non-V3, or contradictory evidence plan fails before worker execution with a stable
control-plane error; it is never repaired by selecting a current plan or latest Artifact revision.
Artifact commit and evidence receipt persistence retain their existing single-transaction boundary.

## Dependency direction

The application/orchestrator parses the stored plan through the workflow control contract and
passes the typed value to the workflow schema projector. Contracts do not import the orchestrator,
database, filesystem, or Catalog implementations.

## Alternatives

Prompt-only copying is insufficient: a syntactically valid worker result can invent IDs and hashes
and consume an expensive worker attempt before the pre-commit validator rejects it. Silently
rewriting worker output would destroy attestation semantics. Binding immutable values in the
attempt-specific response schema rejects or prevents that invalid output while keeping the
pre-commit validator authoritative.
