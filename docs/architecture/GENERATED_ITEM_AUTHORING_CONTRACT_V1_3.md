# Generated Item Authoring Contract v1.3

## Decision

The generated-item workflow uses a new immutable role protocol,
`workflow-role/1.3.0`, and `*-result@4.0` schemas. Historical
`workflow-role/1.2.0` and `*-result@3.0` resources remain byte-identical.
The v4 authoring contract rejects a single-choice draft unless it has exactly
one resolvable choice answer, no accepted text answers, complete statement
explanations, and unique content block identifiers.

## Required design procedure

1. **Responsibility and boundary:** workflow schemas constrain worker messages;
   Catalog contracts remain the authority for item-reference invariants;
   Catalog registration alone persists Item and Item Revision records.
2. **Canonical source:** versioned JSON Schema files under `schemas/workflow`
   are canonical. Pack releases and installed package resources are immutable
   snapshots of those contracts.
3. **Entity and revision model:** the workflow pins one definition hash, one
   Content Pack release, and immutable worker artifact revisions. Registration
   creates a new logical Item and immutable approved Item Revision.
4. **Pointers and resolution:** every upstream artifact pointer retains its
   logical artifact ID, revision ID, schema ID, and SHA-256. Catalog validates
   all four before materializing the canonical item-content value.
5. **Access patterns:** schema lookup is keyed by schema ID; protocol lookup is
   keyed by version; workflow step traversal is ordered; artifact resolution is
   keyed by immutable IDs.
6. **Data structures and indexes:** in-memory schema/version maps provide
   constant-time lookup. Existing unique protocol-version, workflow-definition,
   Content Pack version, artifact-revision, and registration-key constraints
   remain authoritative; no new database index is needed.
7. **Scale and complexity:** validation is linear in the bounded choices,
   statements, and blocks (at most small fixed template limits), with linear
   space for identifier sets.
8. **Transactions and concurrency:** workers never write DB/NAS. Orchestrator
   validates and commits worker artifacts; Catalog registration remains one
   idempotent application transaction keyed by the pinned workflow attempt.
9. **Dependency direction:** workflow contracts may reuse public Catalog value
   contract validation; neither package imports Catalog infrastructure.
10. **Failure, retry, and idempotency:** invalid v4 output fails before artifact
    commit. A failed workflow is historical evidence; a new workflow uses a new
    idempotency key. Protocol and pack versions are never changed in place.
11. **Simpler alternative:** changing the v3 schema or only adjusting a prompt
    would either violate stored schema hashes or leave the invalid combination
    representable. A new versioned contract is the smallest safe durable fix.

## Compatibility and deployment

- Workflow definition `generic-item-development@1.4.0` uses v4 role results.
- Content Pack `generated-knowledge-item@1.1.0` binds profiles to v4 results
  and explicitly tells authoring to leave accepted text answers empty.
- Existing v1.3 workflows and the 1.0.0 pack remain readable and unchanged.
- Deployment installs the reviewed platform/API package, imports the new
  definition and pack release, activates it in `development`, and restarts only
  processes that import the changed platform package.
