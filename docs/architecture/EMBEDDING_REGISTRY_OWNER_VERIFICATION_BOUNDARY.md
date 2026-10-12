# Current-operator registry verification owner

2026-10-12 UTC. Reviewed proposal before behavior; additive source implementation.
Source-only, bounded Item population;
no transport/controller, background service, schema/migration, live role grant,
NAS publication, model execution or runtime activation is part of this change.

1. **Responsibility and boundary.** Implement the existing registry verification
   port with one concrete Catalog owner adapter. Add one public in-session capture
   operation to the existing Catalog inference-transfer owner rather than expose
   its `_scope`, `_resolve_profile_inputs`, `_materialize_entries` primitives to
   callers. The current `CatalogInferenceTransferSourceAdapter` and snapshot
   adapter open separate read-only transactions; those methods cannot provide the
   registry's caller-owned commit/revocation fence unchanged. Identity fencing
   belongs to an official Identity public boundary, not a new Catalog IAM query
   framework. Artifact publication remains the Orchestrator's responsibility.

2. **Canonical source.** Reuse
   `KnowledgeRetrievalApplicationService.admit_read_only_candidate_pool`,
   `resolve_solution_evidence_by_base_run`, `project_accepted_solution_report`,
   `project_staged_item_entry` and the exact committed Artifact member readers.
   No independent search, Item/analysis table-existence eligibility, model-supplied
   profile/report or persisted permission cache is introduced. The accepted-result
   UTC timestamp, rather than the new capture time, defines deterministic profile
   provenance. Missing reports remain in the admitted source denominator.

3. **Logical entity/revision model.** Keep corpus, Graph logical/revision identity,
   policy revision/content SHA, full source variant, accepted base/V10 successor,
   profile identity/revision/hash, index identity/revision and Artifact
   identity/revision/member/raw SHA separate. Historical replay reauthorizes exact
   original references; it neither selects current Graph/source/profile nor grants
   access because a numerical encoding exists. Multiple admitted base analyses of
   one Item revision are an explicit unsupported ambiguous 1.0 population, not an
   invented snapshot/source unique constraint or silent latest-selection rule.

4. **Pointers and resolution checks.** Match the requested Graph to the published
   corpus/publication and the pinned released policy. Preserve full past-exam
   provenance in population/binding pointers while the released profile retains
   its existing V2 source-core contract. Validate canonical JSON (closed schema,
   duplicate-key/nonstandard-number refusal, exact canonical bytes), raw member
   SHA and semantic SHA separately. Reuse one exact member map per Artifact.
   Shard proof requires the producing `control_incremental_embedding` file set:
   `result.json`, `shard.json`, `vectors.f32`; check approved Artifact/revision,
   successful producing Job, outer manifest identity/hash/descriptor, same-file-set
   result/shard equality, binary length/raw SHA/finite/L2 norm and exact row identity.
   The separately implemented public Orchestrator index owner defines
   `EMBEDDING_INDEX_ARTIFACT_TYPE = control_embedding_index`, sole primary/member
   `index.json`, and `control-file-set/1.0`. Catalog consumes those public constants;
   it does not publish a competing Artifact or infer runtime activation.

5. **Primary access patterns and exact permissions.** Current official source
   scope requires actual active, nondeleted operator with no required password
   change and effective `item:read`, `knowledge_graph:retrieve`,
   `knowledge_analysis:read`; `content_intake:read` is additionally required when
   `PAST_EXAM` is requested. A real assigned ADMIN/EDITOR/REVIEWER role must satisfy
   the pinned policy's allowed requester/answer-bearing roles and source/query/
   budget gates. A role label or permission SHA in a DTO is not authority.
   Candidate lookup is read-only. For shared-index registration, propose an
   additional actual `knowledge_graph:publish` prerequisite for this bounded
   operator-only owner invocation was reviewed and approved; read permission alone is
   not asserted to admit a new public index-mutation endpoint. Background indexing
   still needs its separate purpose-specific service-policy successor.

6. **Structures/indexes.** Use bounded source/base-run maps, exact-pointer maps,
   immutable tuples and the existing indexed candidate/accepted-successor queries.
   Reuse the registry's exact key/anti-join repository unchanged. Materialize each
   unique source/index/shard/binary member only at the owner read boundary. No new
   DB indexes, cache table, queue, permission registry or validation framework.

7. **Complexity and scale.** At most 1,024 admitted sources/entries/bindings, with
   explicit truncation refusal and bounded per-member/aggregate byte budgets.
   Temporary captures are O(B+R) metadata and bounded source/binary bytes; validation
   is linear in captured entries/unique shard rows/member bytes. Numerical bytes
   are validated and discarded, never returned as vectors or stored in Catalog.
   This is not the pending 1.1 paging/root successor or a production fanout claim.
   Before admission, the additive root-Session capture limits relevant published
   Item memberships to 1,025 and refuses overflow rather than return a partial pool.
   This prefetch safety budget can reject a Graph with more than 1,024 relevant
   published memberships even when some are currently ineligible; membership is
   never admission. One set query each fences Item+revision, base/accepted V10 runs
   and canonical Item components; existing official admission remains authoritative.
   `PinnedArtifactReadContext.prefetch` uses exactly three set queries per batch
   (Artifact revisions, logical Artifacts, producing Jobs), refreshes loaded rows,
   and uses one manifest hash/member map per immutable revision. Repeated member
   reads perform no lazy metadata SQL and materialize unique bytes once. Its
   explicit ceilings are 4,096 revisions, 8,192 members and 128 MiB retained bytes;
   declared member/aggregate excess is refused before file IO. Graph member proof
   is at most 64 MiB, source Item content 16 MiB/member, native JSON 64 MiB/member,
   and vector binaries use their exact released bounded byte count. Aggregate
   overflow is an explicit error, not truncation or unlimited-memory admission.
   The numerical binary buffer is request-local proof only and is not returned
   by the registry port or persisted in Catalog.

8. **Transaction/concurrency.** The existing registry's external Catalog root
   transaction owns all verification and metadata commit. Obtain Identity-owned
   current-authority fencing before reading scope; keep that fence until root
   commit/rollback. Existing role revocation, disable/delete and password-reset
   operations lock the target Operator row. Merely taking the global identity
   advisory lock is insufficient because password reset uses the row lock without
   that advisory lock. Catalog currently has SELECT, not UPDATE, on `operators`;
   do not pretend a new `FOR SHARE` row lock is admitted or grant IAM writes to
   Catalog/workers. An official Identity locking interface/security gate is needed.
   Catalog locks admitted mutable Item lifecycle/revision and accepted-analysis
   rows in bounded deterministic batches and re-runs official admission under
   those locks before returning exact counts/profiles. Existing immutable policy/
   Graph/report/Artifact contracts do not become mutable validation caches.

9. **Dependency direction and ownership.** Registry application remains frozen
   and imports only its verification interface. New infrastructure composes the
   public Catalog in-session capture and public Identity/Orchestrator owner leaves;
   no cross-service private imports, worker DB/NAS access, domain SQL/filesystem or
   direct source-owner table mutation. The authenticated caller is captured by the
   supported owner transport, not constructed from a request/model role claim.
   No protocol/controller/transport is wired by this adapter task.

10. **Failure/retry/idempotency.** Missing authority composition is explicit
    unavailable, not a fake approved return or fallback to old independent
    read-only transactions. Revoke, scope drift, missing report/view, over-limit
    population, dangling/stale/schema/media/raw/semantic/binary mismatch fail with
    redacted stable registry errors. Every replay and retained-origin resolution
    reauthorizes the same caller/intent and exact references. Request-local
    immutable decoding reuse, if used, is bound to this owner/root transaction,
    never authorization reuse across requests. No new retry or identity reset.

11. **Simpler alternative and tests.** Calling the existing snapshot adapter is
    smaller but commits its read transaction before registry commit and leaves a
    concurrent-revocation gap. Duplicating its private scope/projection code loses
    one authoritative source boundary. Add unit composition tests for current
    permissions, exact caller/corpus/Graph/policy/source/report/Artifact closure,
    missing/duplicate/changed pointers and bounded shared-member work. Prepare
    guarded same-transaction revoke-vs-register tests only after the official IAM
    fence is admitted; do not claim concurrency/live admission tested by mocks.
    Dependencies stay unchanged. Installed/source-only/runtime/live results must
    remain separate.

## Review seams required before behavior

- One existing Catalog-owner in-session capture method, including a current source
  row fence and exact caller/policy scope, instead of many exposed primitives.
- One official Identity-owned authority fence that cooperates with all current
  operator-denial mutations without granting Catalog IAM UPDATE or worker access.
- The separately implemented Orchestrator index Artifact owner's explicit public
  constants are consumed; publisher runtime admission is still a separate gate.
- The reviewed operator-only registration guard above is not an indexing-specific
  permission, service purpose or background grant.

## Final additive owner seams and historical compatibility

`CatalogEmbeddingRegistryVerifier` implements the existing four-method registry
port without changing the frozen application/repository or released schemas.
Trusted construction pins the complete space, recipe, partition, population scope,
corpus and source classes; configuration is not authority. The caller is the actual
authenticated operator context and the exact command/query is reauthorized on each
scope, population and retained-reference invocation.

`CatalogInferenceTransferSnapshotSourceAdapter.capture_in_session` is one additive
Catalog operation. `AUTHORIZE_SCOPE` performs no source/member IO; population mode
fences mutable rows and calls existing official admission/profile/Item projection.
The existing `capture()` and separate read-only behavior remain unchanged.
Reader injection exists directly on `admit_read_only_candidate_pool` and the
existing private profile-input method, with the existing `CatalogArtifactReader`
protocol annotations for solution proposal/evidence readers. Supplying both an
injected reader and a historical reuse context is refused. No historical reuse
context factory, nested/root-transaction restriction or default-reader identity
check is loosened.

`PinnedArtifactReadContext` is owner-local, bound to exact Session, active root
transaction and thread, and unusable after root completion or from another Session.
Its batch metadata capture and scalar resolver share one authoritative semantic
and filesystem leaf. It caches immutable bytes/decoding, never permissions; each
use still checks captured current approval/terminal producer metadata. Existing
scalar APIs and their narrow historical Item manifest compatibility are preserved.
No `already_validated` boolean, private cross-service import or mutable global
service patch is introduced.

## Pending concrete Identity fence security proposal (not implemented)

The only new Identity source surface is required interface
`OperatorAuthorizationFence.fence_current_operator(session, operator_id)`. There is
no concrete/default implementation, helper, schema migration or EXECUTE privilege
in this change. `None` composition fails before member reads or registry writes.
Source tests simulating the fence are not evidence of live revocation serialization.

The minimal next Identity-owner proposal is a fixed-purpose security-definer
function (candidate name `identity_fence_operator_authority`, not an existing API)
that takes only a validated exact operator ID, locks that one indexed Operator row
`FOR SHARE`, and returns no grant or arbitrary SQL result. Its Identity-owned
definition must use fixed schema-qualified relations and a fixed safe `search_path`,
revoke PUBLIC execution, and admit only a separately reviewed Catalog owner role
to EXECUTE. It must not grant Catalog/workers IAM UPDATE or NAS/root privileges.
The official Python method would require the caller's active root Session, call
only that fixed helper, refresh current operator state in that same Session, and
keep the fence through commit/rollback. It must prove every supported role revoke,
disable/delete/password-reset writer cooperates with the same row lock, and specify
transaction-isolation/freshness behavior rather than reuse a stale authorization
snapshot. The helper definition, exact deployed role, permission grant and guarded
independent-process revoke-vs-register tests require a separate reviewed security
gate. Until then, no production composition, background service admission or
concurrent-revocation coverage is claimed.
