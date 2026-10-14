# Local indexing selection and initialization

2026-10-14 UTC. Follow-up to the existing incremental-index design, not a new queue.

## Observed boundary failures

The first service-owned Workflow reached its application step, then stopped with
`EMBEDDING_ENCODING_PROTOCOL_UNAVAILABLE`. The encoding protocol must be prepared
explicitly before service startup; runtime reads must not create or repair it.
The original Workflow, command, step and immutable request remain authoritative.
No vector/binding/index was committed. A metadata-only population query also hit
its 10-second statement timeout after a bounded planner-statistics refresh.

## Selection

Catalog owns the single candidate-selection statement used by both capture and
source resolution. Its canonical inputs remain pinned Graph/source revisions,
accepted analysis, exact occurrence, source class and lifecycle. The operation is
ordered set membership, not enumeration of all node/pointer combinations.

Keep the uniquely keyed `(graph_snapshot_revision_id, analysis_run_id)` association
as the outer relation. Use a correlated EXISTS over matching pointers AND existing
nodes, with source-class/answer-bearing predicates inside that EXISTS. Keep the
exact occurrence EXISTS, accepted-run and active-Item/revision predicates before
the ordered `maximum_candidates + 1` limit. This avoids a multiplicative outer
join and subsequent GROUP BY without changing source eligibility or ordering.
Capture hydrates that bounded selection through a keyed MATERIALIZED CTE JOIN,
not an IN subquery that PostgreSQL can repeatedly evaluate for outer members.
The bounded CTE keeps its own ordered limit; source IDs are unique by the existing
association key. Output is ordered again and retains the same bound. Both EXISTS
alone and a plain derived-table JOIN still timed out in the PostgreSQL scale
fixture. An actual EXPLAIN ANALYZE test requires one CTE evaluation and520 rows,
including72,800 duplicate matching pointers. Temp fixtures copy the relevant
production key/index shapes and refresh their own statistics, not production's.
Existing B-tree/unique keys suffice initially; no schema/index migration or cache.
Space is bounded by admitted source IDs, not all matching pointer/node rows;
actual query plans and timings must establish improvement, not cost estimates.

The simpler statistics-only refresh was insufficient: the actual query still
timed out. Omitting the node check, applying filters after LIMIT, increasing limits,
or retaining authorization between transactions would change protected semantics.
Selection is metadata only and never replaces original authorization, source
materialization, hash checks or late actor/lease fences. No cross-layer dependency
or worker DB/NAS access is introduced. Test exact results against the former join,
including duplicate pointers, orphan nodes, answer-bearing nodes, source classes,
occurrence/revision mismatches, additive reports and overflow. Measure the same
pinned metadata query separately from full canonical-source admission.

## Explicit protocol preparation

The deployment owner prepares only the existing released encoding protocol's
exact installed schema hash through an idempotent Orchestrator storage operation.
Require an active root transaction and the actual PostgreSQL table-owner login;
do not SET ROLE, grant privileges, invent an actor or overwrite a different hash.
Concurrent preparation uses the existing protocol primary key and INSERT ON
CONFLICT DO NOTHING, followed by exact re-read. No Job/model/Artifact is created.
Runtime preflight checks the same record before a command can be claimed. Reads
remain fail-closed, including when a protocol has been removed or mismatched.
Preparation is transactional; failure rolls back only its uncommitted insert.
Existing successful history is not rewritten. No new dependency or wire schema.

## Recovery constraint

Never re-submit with a new key to bypass the original nonterminal Workflow.
An expired command with an allocated launch must use the existing exact-launch
recovery. A stopped pre-allocation command must not be treated as allocated:
recovery needs an explicit proof that the original exact launch key has never
been committed and that no execution can precede that atomic allocation. Record
and test this crash window before changing its admission; no direct DB row repair.
The supported case is an expired LEASED/PROCESSING command with the exact original
RUNNING application step, no platform Job and no output, and an absent deterministic
launch key. Workflow/command/step locks serialize recovery. Launch allocation
commits before reservation/publication/staging/numerical launch, so this case may
re-enter allocation with the SAME Workflow/step/key after current source admission.
The command receives a new normal lease generation, fencing the prior runner.
An absent launch with SUCCEEDED step, output or platform Job remains denied;
allocated/unallocated/failed launch histories retain the existing recovery rules.
Installed source/Identity pins may change only after the prior service process
has stopped; its original Workflow remains subject to supported recovery.

### Source-upgrade boundary is separate

The actual service request pins its Identity revision, runtime and grant. A new
source release needs a successor Identity/runtime/grant, and may NOT simply
process an old request as the new service reference. The pre-allocation recovery
above is same-authority recovery, not an implicit cross-release adoption grant.
Do not activate a successor then requeue the old request, mutate its actor/pins,
or submit another source list to bypass the original. The current process is
already stopped; preserve that Workflow while an explicit supported release
handoff is established. Installing an inactive wheel and metadata benchmarking
does not perform that handoff, and must be reported separately from seed success.
