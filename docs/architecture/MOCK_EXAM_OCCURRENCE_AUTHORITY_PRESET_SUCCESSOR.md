# Mock-exam occurrence authority preset successor

Status: implementation decision, 2026-09-09 UTC

## Decision

Add immutable `standard-control-bootstrap/11.0` and
`knowledge-item-control-bootstrap/8.0` successors. Standard V11 keeps workflow-role 1.19, plan V2,
generic-item workflow 1.9, Content Pack 1.14, all role-result schemas, and the renderer-safe equation
grammar unchanged. It makes the typed `mock_exam_slot` the occurrence-specific authority over
broader source prose for the same dimensions and makes the orchestrator-validated, materialized
reference files the worker's source boundary. Review cannot demand provenance fields absent from
authoring-result@9.0 or report reference transport failure as a content finding. Knowledge V8
projects only the exact released V11 instruction bundle revisions and member hashes before adding
the unchanged Graph retrieval policy. V10/V7 and all predecessors remain byte-identical.

## Required design procedure

1. **Responsibility and boundary.** The control plane defines instruction precedence and the
   reference-materialization trust boundary. The typed request owns occurrence values; the
   orchestrator owns pointer resolution and workspace materialization; workers author or review
   content but do not reimplement storage verification.
2. **Canonical source.** A resolved production request and its `mock_exam_slot` are canonical for
   that occurrence. Its exact difficulty, material profile, inquiry requirement, score, and
   knowledge mode override generic/default reference prose for those dimensions. The immutable V11
   instructions record this rule; the referenced source bytes remain canonical for dimensions the
   typed request does not specialize.
3. **Logical entity and revision model.** Existing `standard-item` and `knowledge-grounded-item`
   logical IDs receive immutable successor revisions. Standard instruction bundles advance to
   revision 11; Knowledge V8 pins those exact revision IDs and hashes. No prior manifest,
   instruction, schema, or artifact is edited.
4. **Pointers and resolution checks.** Before invocation, the orchestrator validates reference
   target and pinned revision existence, schema/version, media type, lifecycle state, permission,
   and SHA-256, then materializes bytes under `references/...`. A missing or unreadable required
   file fails the role before a result is returned. Knowledge bootstrap repeats exact Standard
   current-pointer, bundle identity/revision, state, schema, manifest pointer, and member-hash
   checks; missing, stale, mismatched, or dangling pointers fail explicitly.
5. **Primary access patterns.** Schema, role, and expected instruction lookup are key lookups;
   bootstrap resolves one indexed current-preset pointer and a bounded ordered revision history.
   Review iterates one bounded authoring result and the occurrence slot once.
6. **Structures and indexes.** Frozen Pydantic models, JSON Schema discriminants, immutable tuples,
   mapping proxies, existing unique constraints, and B-tree logical/current-revision lookups match
   those operations. No list-scan registry, binary DB value, new table, or new index is introduced.
7. **Complexity and scale.** Manifest and pointer validation are O(r) time and space for four roles
   and four references; keyed expectations are O(1). Workspace files are materialized once at the
   existing input boundary, and only typed pointers and hashes cross components.
8. **Transaction and concurrency boundary.** Existing bootstrap services lock the logical preset,
   reuse at most one matching draft, record evaluation evidence, and atomically release it.
   Standard V11 must be released before Knowledge V8 resolves and pins it. Worker execution and NAS
   commit boundaries are unchanged; workers never write NAS.
9. **Dependency direction and adapter ownership.** Canonical and packaged schemas remain in the
   workflow contract layer; orchestrator application services select and validate them. Storage,
   filesystem materialization, Codex, and NAS behavior remain infrastructure adapters. Domain and
   contract packages do not import infrastructure.
10. **Failure, retry, and idempotency.** Unreadable required references fail invocation rather than
    returning `REFERENCE_SOURCE_UNAVAILABLE`. Content mismatches retain their typed review findings.
    Bootstrap retries reuse stable identities and content hashes; conflicting current pointers,
    drafts, revision numbers, or hashes fail closed without implicit-latest substitution.
11. **Simpler alternative.** Editing V10 would break immutable history. Changing only the source
    prompt would conflate generic guidance with occurrence planning and require a new shared source
    revision. Adding provenance fields to authoring-result@9.0 would duplicate data already verified
    at the materialization boundary and unnecessarily force workflow, pack, and result successors.

## Verification

- Canonical and packaged V11/V8 schemas are byte-identical, Draft 2020-12 valid, and hash-registered.
- Tests pin every V11 instruction member, exact occurrence precedence wording, explicit reference
  failure behavior, predecessor immutability, V8 revision IDs/hashes, and rejection of V10-current
  or forged V11 bundle components.
- Focused formatting, lint, type, schema-mirror, deployment-inventory, and bootstrap tests must pass
  before release installation. Live bootstrap and deployment remain separate operator actions.
