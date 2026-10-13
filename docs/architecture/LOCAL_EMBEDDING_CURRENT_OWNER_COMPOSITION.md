# Current authenticated operator and native source-plan composition

2026-10-13 UTC. Implementation work for the existing incremental-embedding goal;
this note does not activate a runner, grant a role, or authorize a model run.
The installed CPU receipt is preserved. No numerical-runtime reinstall is needed.

## Bounded decisions

1. **Responsibility:** Identity binds its actual authenticated capture to the existing
   `OperatorAuthorizationFence` interface. Catalog resolves current eligible sources;
   the native Runner composes these owners for submission, claim and mutation. No
   alternative authentication, search, queue or worker protocol is introduced.
2. **Canonical source:** existing approved Artifact members, published Graph membership,
   accepted solution-report revisions, and current Identity rows. Request actor and
   permission hashes remain audit values, never authority.
3. **Identity:** preserve request, source-plan, policy, source/report/Graph revisions,
   Artifact revisions and raw/semantic hashes separately. A bounded seed may select
   a strict subset of the admitted corpus; it does not change the corpus denominator.
4. **Resolution:** the configured execution-policy member must match the request.
   Check current Catalog read scope before even plan metadata bytes are read.
   Read both controls through the existing bounded Artifact reader. Resolve the
   selected sources through official Catalog capture, reconstruct the complete plan,
   and compare it exactly. A caller cannot relabel an available profile as missing.
5. **Access:** exact source-revision lookup, input deduplication, deterministic ordering,
   immutable-member resolution, and fresh caller-root authorization.
6. **Structures:** existing indexed queries plus per-operation maps/sets and frozen
   models. Reuse `plan_embedding_delta` for view availability and encoding identity.
   No schema migration, persistent cache or additional index is required.
7. **Scale:** at most 1,024 sources. Plan construction is O(N + B + K log K), where B
   is validated input bytes and K is the selected source/encoding count; memory is
   O(N + B). One batch capture, not a source lookup per encoding. Immutable read reuse
   must remain within the existing explicit caller-root read boundary, never a saved
   permission result or a cross-transaction source snapshot.
8. **Transactions:** use the exact caller-owned root and the existing Identity fence.
   Claim/mutation retain the established Workflow then command lock order. Each new
   root reauthorizes; inference holds no SQL transaction. Runner owns live-command
   lease checks, including its acquired PROCESSING-to-terminal transition; the source
   owner must not reinterpret a historical terminal row as a valid acquired lease.
9. **Dependencies:** infrastructure/application adapters may compose Identity and
   Catalog public interfaces. Contract/domain packages gain no infrastructure import.
   No new dependency is needed.
10. **Failure/replay:** wrong actual actor, revoked session/source, stale plan, changed
    policy or unresolved Artifact fails explicitly before native side effects. Same
    request replay reauthorizes and reuses existing identities. Historical failures
    are preserved. Source tests are not runtime activation evidence.
11. **Simpler alternative:** passing `actor_id` to the existing operator-only fence
    cannot prove an actual current login; trusting the saved source plan cannot prove
    current report/source eligibility. Small owner adapters close these two gaps
    without replacing the existing Identity, Catalog, Runner or Artifact owners.

## Acceptance boundaries

- Tests cover changed actor/session, root/savepoint provenance, policy/member pins,
  missing/foreign/duplicate sources, report availability, empty views, stale profile
  and source hashes, bounded subsets, deterministic encoding reuse, and late denial.
- No test-generated actor or synthetic capture is production authentication.
- Dedicated CPU installation PASS is retained separately from native launcher
  installation, real seed/delta/query, automatic reconciliation and GPU comparison.
  Those remaining goal gates must not be reported complete by this source change.

## Implemented owner boundary

- `CapturedOperatorAuthorizationFence` accepts only the existing Identity capture
  and concrete session fence. It neither mints a capture nor extends login lifetime.
- `build_local_embedding_source_plan` builds the existing schema from one official
  current Catalog capture. Exact selected revisions, missing reports and unavailable
  views are exhaustive; equal encoding input does not merge source/profile bindings.
- `LocalEmbeddingControlArtifactPublisher` uses the existing file-set publisher.
  It stores one canonical plan/policy member, validates the real publication receipt,
  and returns separate Job/Artifact/revision/raw/semantic identities. Same-key replay
  retains the original supplied UTC timestamp and conflicts on changed content.
- `CatalogLocalEmbeddingOwnerAdmission` accepts an owner-configured policy pointer,
  never a policy chosen by the request. It resolves exact approved controls and
  current source scope and reconstructs the plan, including unavailable/missing
  coverage. Identity is checked again after the reads, and no DB transaction spans
  model inference.
- Its root-local command witness contains only acquired lease/request identity,
  initial state and thread. Weak root keys retain neither Session nor source data.
  It cannot carry permission to a later root or approve historical terminal rows.
- This first concrete adapter accepts untouched pending commands. An expired prior
  acquisition is explicitly unavailable until the native executor's supported
  linked-outcome reconciliation is composed. Expiry is not proof of nonexecution.
  No public API/CLI, default runtime provider or production service is activated.

## Dependency check correction

The full dependency suite detected a pre-existing reverse import in
`eom_orchestrator.embedding_native_probe_observation`: the maintenance-only probe
observer imported Catalog's numerical-runtime filesystem, host and prefix adapters.
Move that observer to `eom_catalog_service.embedding_native_probe_observation`,
beside the numerical-runtime admission it observes. It continues to use the public
Orchestrator systemd observation adapter. No validation is removed and the dependency
test is not weakened. The sole repository caller is its focused test; protected
historical maintenance scripts and the installed c2f8eef8 wheel are untouched and
continue to resolve their pinned old module. Future source maintenance uses the new
owner path. This is not a new CPU installation or another numerical proof cycle.
