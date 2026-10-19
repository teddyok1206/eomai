# Mixed native INDEX owner admission

2026-10-19 UTC; source-only extension of the existing owner admission boundary.

1. **Responsibility:** admit the explicit request2/definition2/plan2 combination through the existing
   native owner, not a second executor, workflow state machine or authentication path.
2. **Canonical source:** current Catalog/Graph source resolution, released service data policy1.2,
   exact native execution policy1.1, and immutable stored request/control revisions.
3. **Identity:** keep Workflow/command/step/native launch identities and lease generations separate.
   Request2 never rewrites or reinterprets an old request1 revision.
4. **Pointers:** resolve exact source-plan and native-policy Artifact members, hashes and schemas.
   Rebuild the mixed plan from currently authorized sources and genuine base-analysis IDs, then
   compare the whole immutable plan. Missing evidence is stale, not a latest fallback.
5. **Access:** bounded exact source selection, definition PK lookup, immutable control reads,
   root authority fencing and existing command/lease lookup.
6. **Structures:** use the existing frozen resolved scope and explicit request/plan unions;
   source and demand maps retain O(1) expected selection. No cache or registry is introduced.
7. **Scale:** preserve current 1,024-source, control-byte and native resource limits. Work is O(n)
   plus existing bounded file validation, not one new session or query per source.
8. **Transactions:** acquire current service/source authority before control IO and recheck it
   after resolution; preserve the existing command fence and final wall-clock expiry check.
9. **Dependencies:** versioned contracts remain pure. Runner admission composes supported Catalog,
   Identity and repository owners; it does not implement their authority or persistence rules.
10. **Failure:** request2 requires the actual service branch, data policy1.2 and matching definition2;
    old service intents retain data policy1.1. Copied extras, family mismatches, stale plans,
    revoked/expired authority and unsupported recovery fail closed without compute or retry.
11. **Alternative:** copying the owner/state machine duplicates security and recovery semantics;
    widening old wire versions changes history. Closed internal dispatch over additive contracts
    is the smaller extension. No new dependency, auth lifetime or operating activation is added.

## Existing submission and publication extension

The same closed request dispatcher feeds exact persisted request bytes, actor-bound fingerprints,
native FIFO quarantine and claim/replay validation. Request2 uses the same compute protocol1 and
state/event tables but its independently compiled definition2. Mixed namespace queue selection
remains an exact JSON metadata predicate, not a source grant. Coverage-only plan2 returns its
validated value without allocating a Workflow. The existing Orchestrator control publisher gains
explicit plan2 publication methods over its unchanged file-set owner; the admission owner reads
that exact schema/hash with its existing pinned reader. No separate publication or claim path,
new table, retry, source expansion or numerical protocol is introduced.
