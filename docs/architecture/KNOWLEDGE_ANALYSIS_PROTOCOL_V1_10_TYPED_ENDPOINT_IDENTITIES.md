# Knowledge Analysis Protocol 1.10 Typed Endpoint Identities

Status: implementation design, 2026-08-27 UTC

## Responsibility and boundary

This change closes the worker-result boundary that currently allows an edge to declare endpoint
types which differ from the types of the node IDs it references. The worker remains a stateless
producer. The orchestrator supplies a strict JSON Schema, the Catalog application validates the
returned proposal, and only validated proposal members may become canonical artifacts.

## Canonical source and revision model

The authoritative ontology remains `KNOWLEDGE_EDGE_ENDPOINT_COMPATIBILITY` in Catalog Contracts.
Historical request, proposal, receipt, result, workflow-role, workflow-definition, and preset bytes
remain immutable. A new additive protocol family is introduced; no historical row or artifact is
rewritten. Each new run pins its preset revision, workflow definition, role-schema bundle, request
hash, proposal Artifact Revision, receipt Artifact Revision, and accepted result hash.

## Pointer and resolution contract

Node IDs in the new proposal encode their node type with a reviewed prefix. Edge IDs continue to
point to exact proposal-local node IDs. Before commit, validation requires unique node IDs, exact
type prefixes, resolvable non-self endpoints, ontology-compatible edge type and actual endpoint
types, resolvable anchors, complete page-image observations, and matching request/revision/hash
pointers. Missing, stale, duplicated, or mismatched references fail explicitly.

## Access patterns and structures

Proposal validation performs keyed lookup from node ID to node type, membership checks for anchors,
and ordered page iteration. It therefore uses dictionaries and sets, giving O(N + E + A) time and
O(N + A) auxiliary space for at most 512 nodes, 1,024 edges, and 1,024 anchors. The persisted Graph
continues to use indexed node and adjacency records; this change adds no database table or index.

## Protocol structure

The new JSON Schema uses `anyOf` branches supported by Codex strict structured output. Each node
branch couples one `node_type` constant to its required node-ID prefix. Each edge branch couples one
ontology edge type and its allowed source/target node-ID prefix sets while retaining the existing
explicit endpoint-type object. This makes the previously observed mismatch unrepresentable in the
worker response schema rather than relying on prompt compliance or post-generation repair.

The Pydantic model independently verifies the same prefix and referenced-node invariants. The
authoritative compatibility map generates/reviews the schema parity test, preventing a separately
maintained edge-compatibility list from drifting.

## Transaction, concurrency, retry, and idempotency

Proposal validation and artifact staging occur before the Catalog commit transaction. A validation
failure writes no canonical proposal or accepted result. The batch remains single-active-range FIFO
with unique `(batch_id, ordinal)` and `(batch_id, analysis_run_id)` constraints. Automatic retry
remains forbidden. Recovery creates one explicitly authorized continuation batch that reuses exact
ACCEPTED run pointers and executes only the failed/unstarted suffix with one persisted idempotency
key.

## Dependency direction

Contracts own the ontology and typed proposal. Workflow schemas reference contracts. Application
services choose the immutable version and orchestrate validation. Filesystem, Codex, PostgreSQL,
and NAS behavior remain adapters. No worker, CLI, or GUI acquires domain rules.

## Failure behavior

Unsupported relationships, mismatched type prefixes, dangling endpoints, duplicate identities,
hash drift, and incomplete page observations fail closed before artifact registration. The service
does not rewrite an edge, infer a different ontology relationship, drop evidence, or retry Codex.
Historical failed batches remain queryable evidence.

## Simpler alternative considered

Adding another prompt reminder or silently replacing a declared endpoint type is smaller, but it is
insufficient: two independent textbook ranges already produced the same class of schema-valid but
typed-invalid output. Post-processing would also change worker semantics without evidence. Encoding
the invariant in a new immutable structured-output contract is the smallest reliable boundary.

## Rollout and obsolete runtime handling

Historical schemas stay installed for pinned-history reads; deleting them would break audit and
replay. Runtime selection moves only to the new workflow definition and released preset. Shared
platform deployment restarts and verifies every long-running consumer so no process can retain an
older in-memory model after wheel replacement. Superseded active pointers may be retired, while
their immutable revisions and referenced artifacts remain preserved.
