# Chat similarity scope bridge

Design before protocol/behavior, 2026-10-18 UTC. Part of
[the full incremental RAG goal](SYSTEM_RAG_SIMILARITY_AND_INCREMENTAL_EMBEDDING_DESIGN.md).

## Identity gap found during actual consumer composition

Chat's frozen `ChatKnowledgeSnapshot.sha256` is the Graph snapshot's semantic
content hash. Native QUERY requires `KnowledgeGraphSnapshotPointer`, including
the distinct manifest Artifact revision/member/raw hash. These hashes are not
interchangeable. Chat has no supported inner read that returns that complete pin.
Do not invent a manifest path/hash or use an implicit latest Graph to bridge it.

1. Responsibility: extend the existing Catalog conversational RAG read owner with
   one pointer-only `RESOLVE_CHAT_PRIVATE_QUERY_SCOPE` operation, not another graph
   resolver/search engine, worker tool or permission grant.
2. Canonical state: the exact published Graph record/manifest, approved Artifact
   revisions and the existing released access-policy revision/current actor.
3. Input is actual operator ID plus the already selected semantic Graph/policy
   scope. Output is that same scope and the exact full manifest pointer. A request
   semantic hash binds replies; no new entity/DB aggregate/history is introduced.
4. Validate closed JSON Schema2020-12/Pydantic, bounds and hash, then existing
   actual actor/policy authorization and official `resolve_snapshot_pointer` plus
   `_scope` manifest validation. The semantic hash is checked against manifest
   content; the raw manifest hash is checked against bytes, never against each other.
5. Indexed Graph/Artifact/policy/actor lookup and existing bounded manifest read.
   No corpus enumeration, candidate selection, question text or model execution.
6. Reuse existing typed pins, maps and read transaction. No migration, index,
   queue, persistent cache, new dependency or duplicate canonical manifest.
7. O(indexed lookups + one manifest's bytes), bounded by the existing32MiB Graph
   read cap; O(pointer metadata) response. This is an explicit validation boundary.
8. The existing Catalog owner closes its read-only transaction before returning.
   Reads are replay-safe but never cached as authority. No state mutation or Job.
9. Domain contract stays in Catalog contracts; service reuses its own RAG owner;
   Unix routing/client are adapters. Chat-owner kernel peer is admitted only to
   this exact read operation alongside its existing reads; workers gain no access.
10. Missing/stale/unpublished/hash-invalid/denied scope fails with no partial pin.
    No latest substitution, role impersonation, TTL change or transport retry.
11. Passing Chat's semantic SHA as the native manifest SHA is invalid. Copying
    resolution/auth into Chat would cross ownership; reusing this Catalog owner
    is the smaller correct extension.

The actual Chat owner must derive the actor from its live worker ticket, not
worker-supplied IDs. Native private admission independently reauthorizes current
origin/Identity/public sources and exact policy at use; this pointer read does
not replace that boundary. Frozen V4/tool2/origin1 and private prepare1.0 stay
unchanged. Candidate filtering, canonical companion publication and live delivery
remain subsequent requirements, not acceptance implied by this read contract.

## Source checkpoint — 2026-10-18 UTC

The additive closed contract is `chat-private-query-scope/1.0`, source and packaged
resource raw SHA `096505224a270455ecb603e0aed693d00e0d67ebbef8c458a922490edee4862c`.
Requests/replies are bounded to4096/16384 bytes including the canonical newline.
The existing Catalog handler admits the Chat owner to this exact read only; the
existing service owns actor/policy checks and Graph resolution in one read-only
repeatable-read transaction. The Orchestrator client makes one bounded exchange,
with no automatic retry, credential acquisition or latest substitution.

Seven focused suites passed **161 tests in28.02s, no skips**:

- `test_chat_private_query_scope.py` (closed contracts, hash separation, rejection,
  service ordering and actual temporary Unix framing/peer/client routing);
- `test_chat_rag_resolution.py` (existing current actor/role/source and manifest
  checks, including distinct semantic/raw hashes);
- `test_general_chat_rag_owner.py`;
- `test_catalog_application_boundary.py`;
- `test_embedding_prefix_snapshot_input.py`;
- `test_catalog_contract_resources.py` (wheel resources/RECORD and installed
  resource reads without source-checkout dependence);
- `test_dependency_boundaries.py`.

Strict mypy4 production modules, Ruff/format9 files, diff whitespace and fresh
process no-ML-import checks passed. The temporary sockets are genuine OS sockets;
their UID/GID, service replies and SQL/source authority are **declared test
fixtures**, not a live user, production Graph resolution, native computation,
protected-service peer proof or migration/activation. No PostgreSQL-mutating test
was run on any operating database. Prior guarded SQL evidence is preserved with
its original scope, not relabeled as acceptance of this new operation.

Earlier results are retained:113 PASS/1 FAIL was a multiline JSON fixture hitting
the legacy first-line parser before the new canonical-frame branch. The fixture
now uses valid single-line noncanonical JSON; no parser was relaxed. The next
138 PASS/1 FAIL exposed a historical318-schema inventory test inadvertently
counting this additive resource and the previously added private-prepare resource.
Excluding those post-baseline names restores the **same318 entries and original
aggregate hash** `sha256:69baab14da4b9fca83ea011f3daef1b846115a9fcd946213db06e54ccb50a24c`;
no predecessor schema/hash was changed. The final161 result is not summed with
these earlier runs.

Status: **SOURCE_PASS; NOT_INSTALLED; NOT_ACTIVE**. Frozen Chat V4/tool2/origin1,
private prepare1.0, DB schema, policies, credentials and CPU default are unchanged.
Actual Chat candidate delivery/provenance, C1–C5 consumer activation, complete
seed/delta/current coverage and genuine CPU/CUDA comparison/default/rollback
remain requirements of the original goal. This prerequisite does not close them.
