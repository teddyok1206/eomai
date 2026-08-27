# Knowledge Analysis Protocol 1.11: Stable Node Identities

## Decision

Knowledge Analysis protocol `workflow-role/1.11.0` makes the ontology node type an
explicit part of every proposal-local stable key. A proposed node now uses both:

- a typed local ID such as `knode_formula_impulse_equals_momentum_change`; and
- a typed stable key such as `formula:impulse-equals-change-in-momentum`.

The worker proposal, request, receipt, accepted result, workflow role messages,
workflow definition, and execution preset receive new immutable versions. Existing
V1.10/V7/V5 bytes and accepted analysis results remain readable and unchanged.

## Responsibility and boundary

The worker proposes bounded local graph identities. JSON Schema rejects an identity
whose stable-key namespace disagrees with `node_type`; Pydantic repeats the invariant
at the trusted application boundary. The orchestrator validates the role result and
the Catalog service alone materializes and commits accepted artifacts. Workers still
cannot communicate directly or write to NAS.

## Canonical source and revision model

The canonical source remains the immutable approved educational-document revision,
page range, page-image manifest, rights snapshot, and execution-preset revision
pinned by the analysis request. A continuation reuses prior accepted analysis run
IDs as immutable pointers; it never copies their artifact bytes or changes history.

## Access patterns and structures

Proposal validation needs ordered iteration plus constant-time identity lookup and
membership checks. The typed models use tuples for deterministic output, while
validators build ephemeral maps/sets for node-ID and stable-key uniqueness and edge
resolution. The batch retains its indexed FIFO ordinal queue and at most one active
range. The expected scale stays bounded at 512 nodes and 1,024 edges per range, so
validation is O(nodes + edges) time and O(nodes) temporary space.

## Transaction, retry, and idempotency

One range claim and state transition remain transactional. Invalid worker output is
not normalized, silently renamed, or committed. The failed historical range is
preserved. A new continuation batch uses one new idempotency key, reuses the exact
accepted prefix by run ID, and records the failed run as the predecessor of the first
new execution. A lost response may replay only the same key and body.

## Dependency direction

JSON Schemas and frozen contract models own the identity invariant. Workflow schemas
compose those contracts. Application services select the new version and orchestrate
validation; infrastructure adapters do not invent or repair identities.

## Failure behavior

- mismatched type/stable-key namespace: rejected by JSON Schema before typed result;
- duplicate stable key: rejected by the typed proposal validator;
- dangling or incompatible edge endpoint: rejected explicitly;
- historical protocol hash mismatch: rejected; no migration or reinterpretation;
- continuation drift, duplicate range, stale revision, or hash mismatch: rejected
  before submission.

## Simpler alternative rejected

Prompt-only guidance was already present and still produced the collision. Silently
renaming a duplicate after generation would make identity depend on adapter behavior
and could alter graph semantics. Relaxing uniqueness would create ambiguous graph
upserts. The additive schema-first version is the smallest durable fix.
