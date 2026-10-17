# Private Chat QUERY: current source and control owner composition

2026-10-17 UTC. Design before behavior. This implements the missing source owner
for the original private QUERY, not an independent search/native framework.

1. Responsibility: Runner composition joins the existing fixed-peer Chat source
   client, official Identity fence, Catalog public DOCUMENT reader and existing
   Orchestrator control publisher. Workers still have no SQL/NAS interface.
2. Canonical sources: the live Chat turn's exact message/dispatch/claim origin;
   current Graph/source/report/IAM scope; immutable registered index; selected
   private execution policy and runtime bundle. No requested operator ID, ticket
   or saved receipt acts as a grant.
3. Identity: preserve original origin/basis, request, source/index revisions,
   policy semantic hash and Artifact byte hashes. Native input IDs are supplied
   by the existing original-Job allocator, not regenerated during continuation.
4. Resolution: materialize through the actual source port and compare the exact
   expected origin, actor and private basis. Fence the actual current operator;
   read exact canonical controls and the same Catalog source/index methods before
   preparing the question. Reauthorize the origin after all public/control reads.
5. Access: bounded ticket/claim lookup and public population/index reads. There
   is no conversation scan, public enrollment of private text or latest fallback.
6. Structures: frozen root-local selected config and resolved source values;
   temporary question text is excluded from repr. Reuse one pinned Artifact
   context, the existing public prepared scope and native input builder. No DB,
   queue, cache, index or cross-service wire schema is added.
7. Complexity: O(authorized sources + pinned selected rows * dimensions + bounded
   question/control bytes); max1024 public sources. File bytes are materialized
   only at existing owner boundaries and not copied into persistence metadata.
8. Transaction: source resolution requires the exact clean nonnested caller root,
   retains it throughout and does not begin/commit/rollback another root. Chat
   source RPC owns its independent short claim transactions and releases them
   around its own file IO as before. No model/unit/publication work occurs in the
   caller read root. Late private/public revocation or pending ORM writes refuse
   delivery. Command allocation/execution must re-resolve these sources in its
   own original command/lease fence; a returned value retains no authority.
9. Dependency: workflow contracts remain infrastructure-free. Runner composes
   supported Chat and Catalog public interfaces. Orchestrator alone publishes
   the private policy using its existing file-set owner; no cross-component table
   writes or private-method imports. Identity installation remains a prerequisite.
10. Failure/replay: re-read the original message and exact selected controls on
    each resolution. Reject altered/expired origin, actor, basis, control pointer,
    producer or source/index scope with content-free errors. No text in exception
    strings, no automatic new request/key or numerical retry on unavailable RPC.
11. Simpler alternative: copying the reference source/claim/executor would repeat
    its business rules and imply an approved anchor. Instead reuse the existing
    private message builder and public DOCUMENT adapter; keep the two typed
    policy families distinct. Small policy/control materialization stays at the
    existing immutable Artifact boundary, not a new authorization abstraction.

The private policy already has closed JSON Schema2020-12/Pydantic definitions;
publication adds its own Artifact type, not a schema/protocol mutation or release.
The publisher cannot activate it. Public controls use an exact policy.json file
set and configured runtime-bundle pointer. The old reference policy and private
policy are never interchangeable.

This source composition does not admit a Workflow, claim a command, allocate a
Job, launch a unit, publish query results, activate a Chat tool or replace history
authorization. Original-command-bound admission/executor/consumer and protected
installation gates remain required. Tests must distinguish real local control
files/DB/file publisher from synthetic Chat/IAM/public population adapters.

## Next mandatory original-submission boundary

Current-state audit: `PrivateChatQueryWorkflowRequest` pins the message basis but
does not contain the live origin. `NativePrivateQueryAllocation` preserves that
origin only after the first native allocation. Therefore actual submission must
also durably pin the original origin in the same Workflow/START transaction,
including the crash interval before the first claim/allocation. Recovering a
current ticket by conversation/turn or substituting latest would be incorrect.

`WorkflowInstanceRecord.runtime_context` is the existing small metadata field,
not a new registry/table. The next protocol-first admission work must define its
closed private-purpose context, include it in original request/replay closure and
protect it from mutation at the DB boundary before using it for allocation.
Keep the existing private request/launch/checkpoint schema bytes unchanged;
do not add untyped fields to old JSON or let a synthetic step bypass the currently
closed compiler/result CHECK. Source composition above cannot fill this gap by
itself. Actual Runner routing and CPU interactive/orphan admission must also know
the private purpose before any fixed unit is installed/activated.

## Implementation and failure-preserving verification

`CatalogPrivateChatQuerySourceOwner` composes the mandatory live Chat source and
Identity ports with the existing Catalog verifier. Its result is temporary and
excludes the question projection from repr. `build_private_chat_query_native_input`
delegates to the existing canonical owned-question builder with original IDs.
The existing `LocalEmbeddingControlArtifactPublisher` publishes the distinct
private policy through its existing immutable file-set owner. No old schema,
native definition admission, DB schema, live config or operating service changed.

Adversarial source testing reproduced a real sequencing gap: public source
revocation during the final private-origin RPC was not observed. The failing
test reported DID NOT RAISE before correction. Source resolution now captures the
public scope again after that RPC, compares it to the original scope, and then
rechecks producer provenance/root. This is one extra current-authority capture
on the new private path, using the same immutable decoding context, not a grant
cache or changed reference/authoring route. Source tests cover that interleaving;
the guarded DB inventory also includes it.

Earlier guarded runs are preserved and never counted as final PASS:

- `private-source-owner-NkiLf8bh`:66 PASS/2 FAIL. Test index metadata and execution
  bundle used different model/runtime spaces. The runtime correctly refused the
  mixed controls. The late-failure oracle was tightened to require reaching final
  authorization, so an earlier unrelated rejection cannot falsely pass it.
- `private-source-owner-V9z6owvK`:64 PASS/4 setup errors. A test selection helper
  still derived QUERY from a fixed default model. It now derives from the exact
  selected DOCUMENT model/runtime; the old default stays byte-compatible. Two
  pure tests protect default and runtime-aligned spaces.
- `private-source-owner-MQ2NHVm3`:66 PASS/2 FAIL. Normal composed read passed;
  subsequent independent fixtures reused the same immutable bundle identity
  under different local Artifact roots. The reader correctly refused that
  substitution. Each independent fixture now owns a distinct bundle revision and
  verifies its committed path lies under its exact configured local root.

All three disposable databases/roles were cleaned up through the supported
manifest/marker guard. Evidence directories under
`/opt/eom/embedding-benchmark-os-evidence/` retain those exact names and logs.
No production pointer, namespace, policy or source authority was relaxed to make
the fixtures work; no existing Artifact was moved or overwritten.

Final focused source regression **386 PASS across11 suites**, including28 private
owner tests, exact selected model/runtime fixtures, reference owner/executor and
shared publisher/public DOCUMENT/dependency regressions. Prior255/383/385/181
runs overlap and are not summed. Strict mypy2 production files and Ruff/format8
files, shell/diff checks PASS. The source/claim/Identity population seams are
synthetic in these tests; the local canonical control files and publisher are real.

The final supported `embedding-tests` gate passed **69/69, no skips, disposable
cleanup PASS**: the preserved64-case Artifact/registry/public-read cohort plus
five new private-owner cases. The new cases cover real registered index/shard/
vector and canonical policy/bundle files together, actual PostgreSQL read roots,
late private claim expiry, late producer failure, public-source withdrawal during
private reauthorization and two concurrent first policy publishers with one
committed identity. The explicit late-stage witness prevents unrelated early
errors from satisfying negative cases. Chat/Identity/source populations are still
synthetic fixtures, not installed runtime authorization or model execution.

Evidence:
`/opt/eom/embedding-benchmark-os-evidence/private-source-owner-PdCsMYAr`;
root helper raw SHA256
`45f426e77f4fdc29a0aa67c40875a490e94b39c8770d6935b26f4e2b6768d339`;
test stdout raw SHA256
`68fcb7f88630b3a485df7e52d219ed1babe8538c4a97a586c5644090607e48d4`.
Operating DB tests, model calls, service restarts and activation0. No new login
prompt, credential persistence, TTL modification or query re-key occurred.
**SOURCE_PASS / DISPOSABLE_DB_PASS / NOT_INSTALLED / NOT_ACTIVE; C4/full goal OPEN.**
