# Renderer-safe equation preset successor

Status: implementation decision, 2026-09-08 UTC

## Decision

Add immutable `standard-control-bootstrap/10.0` and
`knowledge-item-control-bootstrap/7.0` manifests. Standard V10 keeps the V9 protocol, references,
role schemas, slots, and policies, but gives the authoring instruction one executable equation
boundary: the only permitted backslash commands are `\frac`, `\max`, `\prime`, and `\times`.
Greek glyphs that do not require equation structure are ordinary Unicode text outside equation
delimiters. A required expression that cannot preserve its meaning within the renderer grammar must
fail before result submission.

Knowledge V7 projects the current released Standard V10 policy only when all four role instruction
bundle revision IDs equal the immutable V10 IDs and the resolved platform/role member SHA-256 values
equal the V10 content hashes, then adds the unchanged, pinned retrieval policy. A V9 current pointer
therefore fails closed. Mock-exam plan V2, generic-item workflow 1.9, and generated-knowledge-item
Content Pack 1.14 remain valid because their typed inputs, role-result schemas, prompt template, and
state transitions do not change. Job materialization already combines the pinned role instruction
with the Content Pack prompt.

## Required design procedure

1. **Responsibility and boundary.** The control plane prevents an authoring worker from proposing an
   equation the HWPX contract will reject. The HWPX package remains the executable parser and
   renderer authority; this change does not broaden that grammar.
2. **Canonical source.** `content_team_equations.SUPPORTED_COMMANDS` and its preflight validator are
   canonical for renderer support. The released V10 instruction bundle is the immutable production
   directive. Older preset revisions are retained byte-for-byte.
3. **Entity and revision model.** The existing `standard-item` logical preset receives a successor
   Execution Preset Revision whose authoring policy pins instruction-bundle revision 10. The existing
   `knowledge-grounded-item` logical preset receives a successor revision that pins the exact current
   Standard policy components and the existing retrieval-policy revision.
4. **Pointers and resolution.** Standard V10 reuses the four exact reference-bundle identities and
   hashes from V9. Knowledge V7 resolves only an active logical Standard preset with a released,
   hash-valid current revision, verifies the four exact V10 instruction revision IDs and five exact
   instruction-member hashes, and pins its component revision IDs and hashes. Missing, stale,
   non-released, incompatible, V9-current, or hash-mismatched targets fail explicitly.
5. **Access patterns.** Schema selection and role/reference selection are keyed lookups. Bootstrap
   reads one current preset pointer and ordered immutable revision history under the existing indexed
   database queries. The fixed scale is four role policies and four references.
6. **Structures and indexes.** Existing immutable Pydantic value models, mapping proxies, unique
   database constraints, and B-tree identity/current-revision lookups remain appropriate. No new
   persistent structure or index is needed.
7. **Complexity and scale.** Manifest and role validation is O(r) time and space for the bounded role
   and reference counts; current-pointer resolution is an indexed lookup. No binary or item payload is
   added to the database.
8. **Transaction and concurrency.** Existing bootstrap services lock the logical preset row, create
   or reuse one matching draft, evaluate it, and atomically release the immutable revision. The
   Standard release must precede Knowledge V7 bootstrap so the latter pins the intended current base.
9. **Dependency direction.** JSON Schemas and workflow contracts remain below orchestrator bootstrap
   services. Renderer behavior is not imported into production control-plane code; a focused test
   checks that the immutable instruction enumerates the current renderer whitelist.
10. **Failure, retry, and idempotency.** Unsupported required expressions fail before an authoring
    result is returned. Bootstrap retries reuse matching artifacts, bundle revisions, drafts, and
    evaluation evidence by stable identity and content hash; conflicting history fails closed.
11. **Simpler alternative.** Editing V9 would violate immutable history. Changing only Pack 1.14
    would also require an unnecessary pack successor and would leave other workflows using the same
    Standard authoring policy exposed. Adding a new renderer command would require parser, HWPX,
    compatibility, and rendering evidence beyond this prevention-only scope.

## Verification

- Canonical and packaged JSON Schemas are byte-identical and hash-registered.
- V10/V7 manifests validate through JSON Schema 2020-12 before Pydantic.
- Tests pin V10's exact renderer command set, Unicode fallback boundary, immutable predecessor
  hashes, reference reuse, protocol 1.19 compatibility, V7's later base-projection timestamp, and
  rejection of a V9-current instruction map.
- Installed-release admission requires both new schema resources without changing plan, workflow, or
  Content Pack admission.
