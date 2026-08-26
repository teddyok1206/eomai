# Knowledge Analysis edge-endpoint protocol V2

Status: implementation decision for the post-V5 remediation line
Date: 2026-08-26 (UTC)

## Problem and boundary

The immutable `knowledge-analysis-worker-proposal/1.0` contract carries an edge type and two node
IDs, but it does not carry the endpoint node types. JSON Schema can therefore validate the shape of
an edge without being able to reject a semantically impossible triple. V5 range ordinal 11 exposed
this gap when a worker returned `ASSESSES_CONCEPT` from `ASSESSMENT_PATTERN` to `CONCEPT`.
Canonical acceptance correctly rejected that proposal; no accepted graph data was corrupted.

This change owns only the worker-proposal protocol and its Catalog/Orchestrator adapters. It does
not weaken the closed Education Graph ontology, rewrite worker output, retry a failed range, or
reinterpret historical proposal bytes.

## Canonical source and revision model

`KNOWLEDGE_EDGE_ENDPOINT_COMPATIBILITY` remains the authoritative in-process domain rule. A new
immutable JSON Schema line makes the same rule visible to constrained generation:

- `knowledge-analysis-worker-proposal/2.0` adds an explicit endpoint contract to every edge;
- `knowledge-analysis-request/4.0` pins proposal schema 2.0;
- `knowledge-analysis-proposal-receipt/3.0` identifies the new edge-member encoding;
- `knowledge-analysis-proposal-result@3.0` belongs to `workflow-role/1.6.0`;
- `knowledge-analysis` workflow definition 3.0.0 selects that role result.

Versions 1.0/2.0, workflow-role 1.4/1.5, workflow definitions 1/2, and their hashes remain
unchanged and readable. A newly released preset keeps explicit 1.4/1.5 compatibility for historical
non-document sources and selects the new 1.6 line only for endpoint-typed Educational Document
executions.

## Pointer contract and resolution

Every proposed edge still pins `from_node_id` and `to_node_id`. Its new endpoint contract also pins
`edge_type`, `from_node_type`, and `to_node_type`. Resolution performs both checks before artifact
commit:

1. both node IDs exist in the same immutable proposal;
2. declared endpoint types equal the types of those exact node IDs;
3. the edge/type/type triple belongs to the closed ontology table;
4. anchors resolve and no self-edge exists.

The proposal receipt pins one Artifact Revision, per-member hashes, schema references, and the
content-set hash. Historical receipts keep their old schema references. Graph publication resolves
the receipt version from the immutable request, never from an implicit latest version.

## Access patterns and data structures

The dominant operation is key lookup of an edge endpoint during proposal validation. A `dict`
maps node ID to node type in O(n) space and O(1) expected lookup, making complete validation O(n+m)
for n nodes and m edges. Identity uniqueness uses sets rather than repeated list membership.
Artifact members remain ordered immutable tuples/JSONL files; no large content enters PostgreSQL.

Expected scale is bounded by the protocol: at most 512 nodes and 1,024 edges per proposal. The
compatibility table is a small immutable map/set. No database index or migration is required.

## Transaction, concurrency, retry, and idempotency

Typed and ontology validation occurs before Orchestrator artifact commit. Any mismatch fails the
single worker job with a stable invalid-result/ontology error and leaves no accepted proposal
Artifact Revision. Existing application idempotency and batch range uniqueness remain unchanged.
This remediation creates no retry and grants no authorization to resume or create a batch.

Protocol versions coexist in the protocol registry under distinct bundle hashes. Re-registering a
version with another hash fails closed; registering 1.6 does not mutate 1.5.

## Dependency direction and ownership

- Catalog contracts own node/edge value objects and ontology validation.
- Workflow contracts own role input/result schemas and constrained-output projection.
- Orchestrator owns validated proposal materialization and Artifact commit.
- Catalog application services choose an immutable workflow/preset pair and dual-read receipts.
- Graph publication consumes validated typed receipts and never repairs proposals.

Domain packages do not import SQLAlchemy, filesystem, subprocess, or HTTP adapters.

## Failure behavior

- invalid edge/type/type triple: rejected by structured-output schema or typed validation;
- declared type differs from referenced node: typed validation fails closed;
- missing/stale/hash-mismatched proposal or receipt pointer: existing stable pointer error;
- unknown request/receipt/result version: explicit unsupported-contract error;
- historical proposal: read only through its pinned historical contract.

No validator changes an edge type automatically. In particular, the system never silently rewrites
`ASSESSES_CONCEPT` to `REQUIRES_CONCEPT`.

## Simpler alternative considered

Prompt-only wording or retrying until a worker happens to comply is insufficient because it leaves
the same invalid state representable. Normalizing the edge after generation would hide a semantic
decision and corrupt provenance. Adding only endpoint fields without constraining their triple
would still allow the original defect. The additive protocol is the smallest solution that makes
the invalid state unrepresentable at generation and independently fail-closed at acceptance.
