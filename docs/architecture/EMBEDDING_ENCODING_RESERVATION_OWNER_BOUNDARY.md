# Existing-Job per-encoding reservation owner

2026-10-12 UTC. Source-only implementation boundary, not activated native admission.
Read the approved `INCREMENTAL_EMBEDDING_RUNNER_ADMISSION_PROPOSAL.md`, frozen
`embedding-encoding-job/1.0`, and the registry owner boundary first.

1. Responsibility: one purpose-specific Orchestrator owner implements the existing
   reserve/attach, bind-launch, complete and read Protocol. Storage uses only existing
   Jobs/events. Runner launch, Catalog source policy, Identity authentication/fencing,
   protected inference, Artifact publication and service activation remain their
   actual owners. No new queue/table/migration, worker role or dispatcher is added.
2. Canonical source: an encoding request is the immutable computational identity;
   current official source-plan admission authorizes each requested key separately.
   A persisted winner's operator ID, intent, Graph or entire plan is never a read
   grant. Completion references one canonical committed native result/shard/binary
   file set, verified by the required owner resolver, not a model-held receipt.
3. Identity: `jobs.idempotency_key` is exactly `embedding-encode:` plus encoding SHA.
   Source/profile/Graph/Workflow/batch/command IDs are excluded. Job ID and allocated
   Artifact/revision IDs never change; shared output IDs are distinct and do not
   replace those unused allocations. Existing structured-Job wrapper request hash
   and the contract's request SHA are checked as separate immutable hashes.
4. Resolution: all commands, stored events and returned values reparse through the
   released closed 2020-12/Pydantic contracts. Required injected owner admission is
   bound to actual current authenticated caller and explicit target source scope.
   It has no default, role DTO, saved actor, permission boolean or fallback. Launch
   returns pinned plan/input/resources for the existing pure association validator;
   completion returns exact input/result after actual lifecycle, raw/semantic SHA,
   canonical member and finite/L2 binary proof for the existing completion validator.
   This source vertical does not claim a production implementation of that port.
   Read requires a fresh explicit-scope fence before Job existence/reference lookup,
   then reauthorization of resolved canonical pointers. SHARE locks keep Job state
   and the subsequent event projection consistent; response order follows input refs.
5. Access patterns: bounded key membership/claim, sorted Job locks, exact immutable
   launch replay and indexed append-only events. At most1,024 keys/refs/events enter
   one call; maps/sets perform deduplication, identity comparison and event grouping.
   Owner/borrower/association/completion event queries are set-based on Job IDs and
   fixed event names, not per-key event reads or full-table history scans.
6. Structure/indexes: use actual Jobs unique `idempotency_key`, Jobs primary key,
   `uq_job_events_sequence(job_id,sequence)` and `ix_job_events_job_id`. They are
   existing B-tree access paths; no new index or GIN is required. The first immutable
   ATTACHED record owns a key; later distinct launch attachments never replace it.
   One LAUNCH_ASSOCIATION lives on the existing native launch Job; complete records
   live on reservation Jobs. Events are appended, never rewritten/deleted by this
   use case. Existing tables have no new DB append-only/identity trigger: current
   limited-role INSERT-only event grants and application invariants are not invented
   as stronger historical DDL guarantees.
7. Scale/complexity: request maps and bounded event projection are O(n+e), canonical
   key ordering O(n log n); metadata is O(n), no vectors/text/reports are stored.
   Bulk sorted missing-key insertion occurs before any existing Job row lock, then
   one sorted `FOR UPDATE`/`populate_existing` batch locks exact keys. This avoids
   the inversion from prelocking a later existing key before inserting an earlier
   missing key. No SQL transaction is retained through materialization/inference.
8. Transaction/concurrency: each public call owns one short Session root transaction.
   Current owner/source/command fencing precedes writes; mutation repeats the exact
   live-command/time-expiry fence immediately before commit. Missing keys insert in
   sorted order inside a savepoint. Only PostgreSQL23505 on the actual
   `jobs_idempotency_key_key` admits bounded rollback/reread/retry; other constraints
   and immutable-request conflicts fail. Candidate allocations stay stable across
   that bounded retry. `[a,b]`/`[b,c]` creates one durable owner for `b`; losers attach
   as borrowers and launch only their separately recorded owned subset. All failure
   paths roll back the call, including new Jobs/events and attempted association.
9. Dependency/ownership: application depends on frozen Workflow/Catalog contracts,
   a small required purpose-specific owner admission port and an Orchestrator-local
   storage leaf. No Catalog/Identity private repository is imported. Session factory
   is explicit; no ambient DB URL, mutable global context or worker DB/NAS access.
   Actual IAM/session freshness, released native policy/runtime, source integration
   and command fence composition remain required/unavailable until separately wired.
10. Replay/failure: exact intent/event/association/completion replays append nothing.
    Changed immutable request, changed intent under the same launch identity, altered
    Job allocation, borrowed-key launch or changed canonical completion is refused.
    Bind requires the exact whole owned set, separate from the original plan. Complete
    requires the exact whole association atomically; no partial-success rewrite.
    Reservation states traverse the existing transition table (transient QUEUED is
    never externally committed): reserve ends CLAIMED, bind ends RUNNING logical
    launch-associated work, not proof of a process or device. Completion follows
    VALIDATING_RESULT/COMMITTING/SUCCEEDED only after committed output verification.
    Native launch history remains the authority for actual execution. FAILED and
    CANCELLED are terminal, never reset. Required owner read observation can mark
    an unproven expired launch UNCERTAIN while retaining its original owner/capacity;
    historical completed reads instead reauthorize the fresh caller's exact sources
    and canonical output, without treating an expired old command as authority.
11. Simpler alternative: batch-only idempotency duplicates shared `b`, Catalog's
    committed encoding uniqueness is too late, and a new reservation table/queue
    duplicates existing durability. `submit_structured_job` alone lacks source,
    command, immutable-owner and shared-row proof. Reusing its exact Job identity
    model with narrow purpose-specific orchestration is the smallest coherent step.

Owned source paths: new `embedding_encoding_reservations.py` and
`embedding_encoding_reservation_storage.py` under `eom_orchestrator`; focused unit
tests/fixtures and marker-guarded disposable integration tests. Frozen native schema,
Registry/Identity/runtime/install/release/models/migrations remain unchanged.
Synthetic admission doubles prove call ordering/refusal only, not live grants or
canonical NAS publication. Prepared actual DB races are executed only by the root
guarded disposable test runner; no DB/root/runtime action belongs to this source task.

## Reviewed additive completion batch leaf

The scalar Workflow completion validator reparses/hashes the whole owned input and
result for each row. Calling it1,024 times would be O(n²). Root approved an additive
`validate_embedding_encoding_completions` in the existing encoding-job contract
module/public export, with unchanged schema bytes and scalar API semantics. Scalar
and batch share one semantic event/context leaf. Batch reparses the association once
and each completion once, builds one keyed owned-job map, and requires the exact
whole sorted unique owned set. The existing Catalog exact-result validator remains
the single authority: its historical constant-two full input/result parse pipeline
runs once per batch (two, not one, full parses of each input/result). Raw input/result/
shard hashes are computed once each, not per event. This is O(n+bytes) without adding
an API, unchecked frozen bypass, caller `already_validated` flag, permission or cache.
Synthetic operation-count tests must report that actual constant-two parse bound and
three raw-member hashes at1,024 rows. Actual binary/lifecycle/current authority still
belongs to the required trusted owner resolver; pure validation never grants it.

## Frozen source gate and prepared database coverage

Source gate:237 PASS in19.59s across the new owner/batch suites and existing native
admission/workflow/state-machine suites; Ruff format/check and strict mypy PASS on
all eight owned Python files, including fixtures and prepared integration tests.
The1/16/1,024-row operation-count tests observe exactly two full input parses, two
full result parses, three raw-member hashes and one semantic leaf per event. All
four native canonical schemas and packaged mirrors retain their original raw SHA
pins; no schema/old scalar API, migration/model, Registry, Identity, runtime, install
or release behavior was changed by this reservation vertical.

Eight database tests are prepared/collection-checked, NOT_EXECUTED by this agent:
sequential overlap/original allocations/no Artifact placeholders, exact whole owned
bind and completion replay, partial owned-set and changed allocation refusal, late
reservation/completion fence rollback, immutable intent/stale reference refusal,
terminal no-reset, fixed batched statement counts, and independent-process singleton
same-key plus `[a,b]`/`[b,c]` races. Each child reloads the exact passed guarded state
and manifest, rejects URL database/role mismatches before connecting, and rechecks
actual database/current user/app owner/marker/search path/privileges/source migration
before reserve. A saved parent URL is not database authorization; diagnostics never
print credentials, SQL parameters or source IDs.

The prepared completion gate validates approved/SUCCEEDED immutable DB member
metadata only, explicitly NOT actual canonical NAS bytes, finite/L2 binary proof,
current IAM/session/source authority or native execution. Those production obligations
remain required adapter composition, not inferred coverage or active grants. No DB,
root, migration, package/model/GPU/network/NAS or Git operation was executed here.
