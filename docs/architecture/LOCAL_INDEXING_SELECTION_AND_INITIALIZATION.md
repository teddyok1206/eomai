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

## Bounded preallocation retirement for a corrected release

An incompatible Identity/runtime/grant successor cannot adopt the original audit
pins. Rather than invent cross-release authority, add one explicit deployment-owner
maintenance use case: retire ONLY an exact PROCESSING, expired native START whose
exact RUNNING application step has never allocated its deterministic launch Job.
This is NOT timeout-based retry, failed-history repair, force-cancel or automatic
recovery. The observed missing-protocol failure is the closed reason. The owner
supplies the exact request/hash, command/lease generation, current service reference
and intended successor source commit. A closed JSON Schema2020-12 command/receipt
precedes implementation. Both are bounded metadata, not worker input or a grant.

Canonical sources are the original immutable request/START/step, current Identity
metadata and indexed native-launch key. Existing Workflow events store the typed
receipt and its semantic hash; no new registry, queue, binary, migration or NAS
copy. Original IDs, request/source/report/Graph/space/policy pins, START fingerprint
and lease audit stay unchanged. Exact lookup uses PKs and the existing workflow
command/event indexes; a bounded two-row read detects extra commands/steps/events.
Time is O(log N + H) keyed lookup and a workflow-local event scan/append (H is this
single-step Workflow's small history); returned metadata memory is O(1).
Existing Workflow/command/step locks serialize against claims. NOWAIT
locks refuse live races rather than forcing a lease. Existing source fences prevent
an expired prior runner from allocating after these locks are acquired.

The actual PostgreSQL table-owner login (not SET ROLE, ADMIN or a model actor) is
verified for the four affected Workflow tables. On a first mutation, the public
Identity owner operation locks/revalidates the exact current service metadata.
Require the canonical service-only definition, original request/hash/fingerprint,
one exact START and one exact RUNNING step, elapsed lease, no output/platform Job,
and absent exact launch key. A committed launch, unknown outcome, live lease,
extra command/attempt, output, wrong actor/hash/revision or terminal history denies
the operation. No source grant is expanded and no model or Artifact is started.

Use the existing state machines to mark that START, step, Workflow and stage
FAILED with `EMBEDDING_ENCODING_PROTOCOL_UNAVAILABLE`, plus an immutable retirement
receipt that records the intended corrected release. This makes an already
observed failure explicit; it never marks it successful or deletes it. All effects
share one caller-owned root and roll back together. Same command replay returns
the original exact receipt without adding events; a changed command conflicts.
Historical replay remains owner-only and does not require reactivating the old
Identity. No transaction/capability is cached. Dependencies stay application →
contracts/domain and existing public Identity control boundary.

Only AFTER the original is terminal may the normal release controls activate a
successor, and the existing missing-binding reconciler produce its newly authorized
request. That new request is an explicit corrected-release successor, not a retry
with substituted old pins or a bypass of nonterminal/uncertain work. Keep the old
receipt/source/Workflow linked in operational evidence; the actual new request
must still pass ordinary source, current grant, native execution and idempotency
checks. Retiring alone does not grant future submission or prove a successful seed.

The simpler same-authority recovery is insufficient because it cannot run a fixed
source with the old source's immutable runtime identity. A general adoption or
force-resume framework would broaden authority unnecessarily. Tests must cover
actual owner/nonowner, exact replay/conflict, concurrent retire/claim, all negative
preallocation predicates, rollback and unchanged request/lease/Job/Artifact state.

The retirement schema/validator lives only in its removable owner-maintenance
contract module. It does not extend any existing runtime admission schema family,
registry or released bundle hash. Actual new-service execution still uses the
unchanged1.2 service request and1.1 native policy contracts.

## Target-scoped physical reads for native execution

The corrected service's metadata query is85ms, but the first1-target Workflow still
spends minutes before model allocation. Code inspection identifies a separate
linear-cost boundary: every native command/lease/source fence calls full-corpus
`resolve_lookup`, physically parsing all520 approved sources/reports, then discards
all but the immutable plan's selected targets. Concurrent heartbeat roots repeat
that work and approach the existing1GiB owner limit. No claim is made that every
remaining CPU second has been profiled or that model computation is the bottleneck.

Keep full population discovery/missing-binding reconciliation, index preparation,
registration/coverage and user retrieval unchanged. Add one internal frozen
`SelectedEmbeddingSources` value (original lookup scope + sorted bounded revision
IDs) and an explicit Catalog `resolve_selected_sources` operation. It is not a
wire/worker message, source grant, new query engine/cache or global lookup flag.
Only after original policy/plan pointers pass their existing checks may a native
execution fence select EXACTLY `plan.sources`. Current actual actor/service/policy
authorization runs each root as before; the pinned Graph and all selected source,
report, occurrence, lifecycle, schema/media/hash and late lease checks remain.

Pass the small revision selection through the existing operator/service capture
paths into the same official candidate statement BEFORE the limit and physical
prefetch. The existing `(source_kind, source_revision_id)` lookup index and Graph
keys support this access pattern. A missing/ineligible selected revision must
fail explicitly; never substitute all/latest. A valid report wait remains distinct
from an available profile. The full-population APIs do not accept the selected
value and cannot use a partial read as global coverage. No persistent cache, DB
index/migration or released schema/Artifact/identity/hash meaning changes.

For N eligible sources, k pinned targets and M execution roots, physical source
work changes from O(MN) to O(Mk). Initial discovery and final full index assembly
remain O(N). Metadata selection is indexed/bounded; immutable source pointers and
ordered tuple/set comparisons preserve exactness. No data is persisted and no
authorization survives a root. Each read joins the caller transaction and rechecks
actual policy/permission/revocation; existing claim/lease/idempotency own effects.
Failure/replay behavior is unchanged, with no inference retry or larger resource
budget. Layers remain application → typed owner contracts/domain; Catalog owns
the query/prefetch adapters and Runner supplies only verified plan identities.

Tests must prove selection propagation for BOTH actual-principal branches, source
class/answer/occurrence/lifecycle predicates before limit, exact missing/stale/hash
failure, k-source physical reads among a larger synthetic corpus, report waits,
and unchanged global discovery/registration/coverage. The simpler metadata-only
optimization is insufficient because these repeated physical reads remain; a
long-lived parsed-Artifact/auth cache would add invalidation/security complexity.
The current installed Workflow is not restarted or modified to install this
candidate. Actual latency/memory improvement needs its own compatible release
after the current execution is terminal or safely drained.
