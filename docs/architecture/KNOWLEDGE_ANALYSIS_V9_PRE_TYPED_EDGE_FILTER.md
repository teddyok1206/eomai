# Knowledge Analysis V9 pre-typed edge filter

Status: implementation decision, 2026-09-09 UTC

## Decision

For `knowledge-analysis-proposal-result@9.0` only, validate the complete untrusted worker result
against its existing canonical JSON Schema 2020-12 document, then deterministically remove proposal
edges that cannot be admitted under ADR 0047, and only then construct
`KnowledgeAnalysisProposalRoleResultV9`. The existing proposal staging validator remains the
authoritative post-Pydantic check.

The filter removes an edge when it is self-referential, names a missing endpoint, declares endpoint
types different from the referenced nodes, or violates the current worker-edge ontology. It never
changes an edge, node, anchor, claim, observation, ambiguity, pointer, ID, or hash. Duplicate node
or edge IDs remain an explicit typed-validation failure because retaining or dropping one duplicate
would invent meaning for an ambiguous immutable identity.

No JSON Schema, protocol version, database record, wire metadata, execution preset, or historical
Artifact is changed. The current V9 instruction already states all four edge requirements; this is
the validation-order correction required for the filtering behavior already adopted by ADR 0047.

## Required design procedure

1. **Responsibility and system boundary.** `eom_workflow.schemas.validate_role_result` owns the
   untrusted JSON-to-typed-result boundary. It applies the existing schema before normalization.
   The Orchestrator continues to own Artifact staging and Catalog continues to own acceptance and
   Graph publication.
2. **Canonical source.** The installed `knowledge-analysis-proposal-result@9.0` JSON Schema remains
   canonical for raw message shape. `WORKER_KNOWLEDGE_EDGE_ENDPOINT_COMPATIBILITY`, exposed through
   its Catalog Contracts validator, remains canonical for worker-edge ontology. The filtered,
   typed proposal passed to existing staging produces the canonical immutable Artifact members.
3. **Logical entity and revision model.** Analysis run, request, preset, workflow, Artifact, and
   revision identities and their SHA-256 values remain separate and unchanged. Previously stored
   proposal and result revisions are never reopened or rewritten.
4. **Pointers and resolution checks.** The filter performs proposal-local node-ID resolution only.
   Existing request/source Artifact revision, member, schema, media-type, lifecycle, permission,
   and hash checks still run in staging and Catalog services. A filter never substitutes a latest
   revision or repairs a pointer.
5. **Primary access patterns.** Validation needs one keyed node-ID lookup followed by ordered edge
   iteration. Edge order is stable, and retained edge objects preserve their exact values.
6. **Data structures and indexes.** A dictionary maps node ID to declared node type, a set rejects
   duplicate edge IDs, and one list collects compatible edges. Duplicate detection uses keyed
   membership. No persistent data structure or database index changes.
7. **Complexity and scale.** For at most 512 nodes and 1,024 edges, time is `O(n + e)` and auxiliary
   memory is `O(n + e)`. Only `output.proposal.edges` is deep-copied; the small enclosing mappings
   are shallow copies and all other payload branches are untouched.
8. **Transaction and concurrency boundary.** Filtering is pure and occurs before Artifact staging
   or any database/NAS write. It has no lock, lease, transaction, worker-slot, or concurrency
   effect. Repeated validation of identical bytes produces an equal typed result.
9. **Dependency direction and adapter ownership.** Workflow validation calls a public Catalog
   Contracts domain validator. No domain package imports an infrastructure adapter, and no worker
   gains orchestration or persistence behavior.
10. **Failure, retry, and idempotency.** Malformed raw shape fails JSON Schema without entering the
    filter. Duplicate identities and every non-edge typed invariant still fail Pydantic. The four
    known failed past-exam runs may receive fresh, explicitly allowlisted successors only after this
    code is installed and all long-running consumers are restarted; their predecessor preset pins
    can remain exact because the correction is runtime validation behavior, not a preset revision.
11. **Simpler alternative and why insufficient.** A further instruction reminder is insufficient:
    the current instruction bytes already require closed, non-self, type-matching endpoints.
    Filtering after Pydantic is also insufficient because Pydantic rejects these three observed
    edge classes before the ADR 0047 filter can run. Relaxing the Pydantic model or rewriting edge
    fields would reinterpret the protocol and could invent graph meaning.

## Verification and rollout gates

- Focused tests prove schema-valid self, dangling, and declared-type-mismatched edges are removed;
  compatible edge order and every non-edge proposal value are preserved; input objects are not
  mutated; replay is deterministic; malformed shape fails before filtering; duplicate node or edge
  IDs are not repaired; and current worker-ontology rejection is filtered.
- Existing staging and Catalog ontology tests remain defense in depth and continue to own Artifact
  counts, hashes, and graph acceptance.
- Format, lint, strict type checking, and focused unit tests must pass from an explicit Conda
  environment.
- Deployment waits for the active exact-run retirement/hold boundary. After wheel installation,
  restart every process that imports `eom_workflow.schemas`, verify their installed source/hash and
  zero active slot-05 work, then admit only the reviewed analysis successor allowlist.
