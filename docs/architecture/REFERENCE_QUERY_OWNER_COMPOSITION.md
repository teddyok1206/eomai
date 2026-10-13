# Current-owner reference QUERY composition

2026-10-13 UTC. Continuation of the original system-RAG/incremental-index design.
This note does not activate QUERY, a service identity, a consumer or a numerical runtime.

1. Responsibility: extend the existing Catalog source/index owner with caller-root
   preparation/read methods for the native QUERY owner. Existing convenience methods
   retain their own root and delegate; no parallel source resolver or query service.
2. Canonical source: exact current official anchor, accepted report, Graph/policy and
   registered immutable index. The runtime's QUERY result is auxiliary, never Evidence.
3. Identity: keep context/native request hashes, logical native Job, publication Job,
   Artifact/member revisions, QUERY/DOCUMENT spaces and recipe separate.
4. Resolution: literal input1.0 and input1.1 have separate frozen parsers/validators.
   One explicit supported-version dispatcher selects them; no schema guessing or
   input resizing. Result/context1.0 bytes and meanings are unchanged. Same-root
   source/index reads reject absent/ended/nested caller roots before source IO.
5. Access patterns: at most three keyed views, one bounded official population
   capture at each read boundary, grouped immutable index/shard reads and final
   full-population comparison. The consumer receives only its bounded typed context.
6. Structures: retain frozen values, tuple order, map/set deduplication, existing
   registry/Artifact indexes and owner-private single-root read reuse. No new table,
   queue, cache, mutable singleton or dependency.
7. Complexity: current bounded O(P + V*P*d) read/verification, V<=3 and P<=1024.
   No DOCUMENT re-encoding; version dispatch is O(1) plus the existing bounded parsers.
8. Transactions: native owner supplies its actual current Identity-fenced root.
   Preparation/read wrappers do not commit it or open a second source root. No root
   or permission/read window may span model inference. End population/permission
   checks remain required. Native claim/lease/execution are separate later composition.
9. Dependencies: Catalog application/infrastructure reuses Catalog public source
   and pinned-index operations. Pure input dispatch stays in the existing contract
   module; no contract imports an adapter or database. Orchestrator's existing
   control publisher gains a separate typed QUERY policy method, never writes from
   a worker. Installed activation and actual caller authorization remain external.
10. Failure/replay: unsupported versions, malformed raw values, stale contexts,
    revoked sources, corrupt members or late population drift fail explicitly.
    No old-parser widening, benchmark replay, DOCUMENT-as-QUERY, new identity retry,
    latest fallback or false successful coverage. QUERY policy publication reuses
    the existing canonical/hash/idempotent file-set owner; publication is not release.
11. Simpler alternative: parsing a real batch4 input as batch3 changes the numerical
    recipe; reading source in another root cannot retain the native owner's current
    session fences. Two small public root-preserving entrypoints and literal
    dispatch close these gaps without a new framework or reinterpretation of history.

Required checks: predecessor schema/parser preservation; input1.1 partial batch4
composition and exact result/context/hash closure; unknown/forged versions, strict
raw scalars and corruption; caller-root identity/ended/nested denial; unchanged
capture/read counts and late source revocation for both convenience and same-root
entrypoints; QUERY policy exact canonical publication/replay/conflict and no body
in DB. Source tests do not prove genuine installed QUERY admission or user authority.

Next required boundaries remain the actual current-owner QUERY allocation/queue,
lease, fixed installed purpose/unit, genuine result publication/committed read and
consumer delivery. Automatic indexing authority and CPU/GPU gates are not replaced
by this source connection. The original full goal remains active.

The concrete current-source owner belongs beside the existing native INDEX owner
in `eom_workflow_runner`, not in Orchestrator: Orchestrator must not import Catalog
infrastructure. It composes actual Identity capture/current-session fences, the
configured policy/bundle Artifact members and Catalog's public same-root source
and pinned-index reads. The preparation validator is shared with the context
application rather than reimplemented. Building the exact source-neutral native
input is a separate pure local-value function, never current authorization.
No claim/queue admission is enabled by source preparation alone. Policy publication
and returned immutable values cannot replace fresh claim/publication/read fences.

The canonical QUERY Artifact reader resolves its existing four-member file set
once in the caller root: exact member set, schema/media/lifecycle/raw hashes,
actual publication Job, input/result/shard closure and finite unit-norm binary.
It returns `ResolvedReferenceQueryArtifacts`, deliberately NOT the consumer's
`VerifiedReferenceQueryRead`. The latter additionally requires genuine current
source/claim/unit execution provenance from the concrete QUERY owner. Storage
bytes or a supplied receipt cannot establish that provenance. No input/body or
vector enters SQL; numerical bytes materialize only at this explicit read boundary.

## Implemented source and verification — 2026-10-13 22:52 UTC

- Explicit input1.0/1.1 dispatch is connected to the existing context composer and
  execution validator. The old literal parser and all schema bytes are preserved;
  configured batch4 with one genuine partial row is not resized or padded.
- Catalog's prepare/read convenience methods delegate to their new same-root
  entrypoints. Missing/ended/nested roots fail before source IO. Both paths retain
  the same two population captures/nine scope checks for a three-view read and
  reject late revocation. No reusable authorization snapshot is introduced.
- `CatalogReferenceQueryOwnerAdmission` composes real capture/fence interfaces,
  exact configured policy/bundle members and those public source/index methods.
  The context application's preparation validator is shared. The native-input
  builder emits only bounded exact QUERY rows and no actor/permission/lease token.
- The existing Orchestrator publishes QUERY policy through a separately named
  typed method and distinct Artifact type; same-key replay/conflict is preserved.
- The canonical four-member reader checks actual publication Job, current committed
  lifecycle, exact input/result/shard/binary hashes/shape and supplied history closure.
  A storage resolution is deliberately not a genuine QUERY execution capability.

Final24-suite source regression **657 PASS**,68.99s; strict mypy10 source modules,
Ruff/format16 Python files and diff PASS. The prior656-pass gates overlap and are
not summed. Tests include actual temporary SQLite/filesystem publication/read but
explicitly synthetic Identity/source/index seams and synthetic numerical bytes.
They are not production IAM, PostgreSQL concurrency or installed QUERY evidence.
An early fixture retained a third view not selected by its request; the fixture
was corrected, not the authoritative source guard. Final raw revalidation also
rejects forged bundle fields before a serialization could discard them.

Frozen schemas, numerical backend/vector implementation, workflow admission,
migrations, units and the operating CPU installation are unchanged. All9 observed
services remain active. No auth/model/Job/Workflow/index/policy release occurred
in this source phase; the previously prepared finite INDEX canary remains waiting
for its one operator login. Its root/controller process handles were observed live.

Read-only metadata diagnosis confirms the pinned Graph's1040 analysis associations
comprise520 past-exam Item analyses,25 generated Item analyses and495 document
analyses (10 document revisions). This is not1040 eligible Item identities and does
not justify increasing the existing source limit. Actual caller-authorized
population/profile counts remain pending the supported current-source operation.

`QUERY_SOURCE_PREPARATION=SOURCE_PASS`, `QUERY_CANONICAL_ARTIFACT_READ=SOURCE_PASS`,
`QUERY_QUEUE_UNIT_CURRENT_EXECUTION=NOT_ACTIVE`, `GENUINE_QUERY_CONSUMER_READ=NOT_ACTIVE`.
The fixed QUERY step CHECK/migration, Job/lease/installed-purpose owner, genuine
committed read adapter and consumer activation remain required next work. Service
reconciliation and CPU/GPU/default selection retain their original goal scope.

## Queued QUERY execution — implementation decision

1. Boundary: QUERY uses the existing Workflow command queue and native Runner
   routing boundary. Its own typed owner/executor pair is required; INDEX ports and
   Codex ROLE execution cannot substitute for it. No default production activation.
2. Canonical source: re-resolve the official anchor/report/population, pinned
   Graph/policy/index and configured runtime/policy in each current caller root.
   An old preparation, queue header or completed Artifact is not authorization.
3. Identity: keep operator-bound Workflow fingerprint, immutable QUERY request,
   command acquisition, native Job, publication Job and receipt producer distinct.
   Store pointers/hashes only in step output; no native text/vector in SQL.
4. Resolution: recompile the exact definition and check its hash/protocol, actual
   request actor and original request closure at create, claim, mutation and replay.
   Completion requires the executor's canonical receipt verification, including on
   terminal replay. A pass-through fixture is explicitly not live acceptance.
5. Access: FIFO peek, exact-PK claim, Workflow-then-command lock order, immutable
   request comparison and bounded latest-step lookup. A failed native preflight
   must not claim or route through ROLE. Existing native routing quarantines even
   malformed/cross-purpose metadata.
6. Structures: retain the single indexed command queue and existing
   unique submission/step keys, immutable typed request union and per-root command
   acquisition witnesses. Shared mechanical command fences serve INDEX and QUERY;
   source/current-execution rules remain purpose-specific, not generic callbacks.
   Add a third internal readiness/claim family for QUERY, not another queue. The
   total native quarantine predicate still excludes every native marker from ROLE;
   QUERY-marked rows are excluded from INDEX too. Otherwise an unconfigured QUERY
   at the native FIFO head could starve an independently ready INDEX operation.
7. Scale: queue lookup/claim is existing indexed O(log N); exact request validation
   is bounded by three views. Source resolution retains the preceding O(P+V*P*d)
   bound. No new queue, table, index, dependency, cache or authorization registry.
8. Transaction: owner reauthorization precedes savepoints/lease assignment and is
   repeated before root commit. No SQL root survives inference. The existing
   heartbeat uses a fresh root with the captured immutable request and actual
   current owner. Terminal command transition retains the same unexpired lease.
9. Dependency: pure workflow contracts stay infrastructure-free; Runner owns the
   application lifecycle and Catalog composition. Orchestrator remains the sole
   Artifact commit owner. A paired injection is a necessary composition boundary,
   not proof of physical QUERY-purpose admission.
10. Failure/replay: exact idempotent submissions reuse their Workflow; failed history
    is never repaired. Until durable QUERY launch/checkpoint recovery exists, an
    expired acquisition is explicitly unavailable, never a fresh inference grant.
    Uncertain physical work cannot be retried by changing an identity.
11. Alternative: using the INDEX result schema, a ROLE job or a fresh ad-hoc queue
    would erase purpose/current-owner guarantees. Extend only the existing fixed
    application-step CHECK with the exact QUERY key/result pair in additive0054;
    preserve0053 bytes and refuse downgrade if any QUERY history exists. This is
    source/disposable-DB work, not permission to migrate the live database.

The source head follows0054. Protected release bookkeeping therefore gains only
the additive context/admission1.3 with literal target0054 and exact0053 predecessor
callbacks. Released1.0/1.1/1.2 schemas, target mappings and0051 wrapper stay frozen.
The current deployment selector moves to0054; this does not execute a migration or
reconfigure an already installed service. Build-only and live states stay separate.

The global QUERY definition remains unoffered until the concrete physical-purpose
executor and genuine canonical completion owner are present. Source lifecycle
tests may exercise that seam with explicitly synthetic ports; they must not claim
installed QUERY execution, IAM, numerical or consumer acceptance.

## Queued boundary source implementation — 2026-10-13 UTC

The existing queue now has separate ROLE/INDEX/QUERY readiness families. This is
three bounded nonlocking peeks over one existing indexed queue, not three queues.
Total native/QUERY marker predicates prevent malformed history from falling into
ROLE or INDEX. Exact Workflow→command locks, immutable candidate comparison and
late current-owner/lease checks remain required before assigning a generation.

QUERY submission is operator-bound/idempotent, rechecks the current owner before
and after its savepoint, and preserves schema-required nulls. The fixed step runs
only outside SQL roots; success/terminal/replay require canonical completion from
the QUERY executor. Step state/output stores only a request hash and receipt
pointer carrier. Wrong purpose, changed input, invalid receipt, late revocation,
terminal tampering and an old acquisition never get repaired into success.
Fresh command identity also cannot bypass a preexisting unfinished QUERY attempt.

The actual Catalog QUERY owner now has same-root submission/claim/mutation seams,
with current Identity and official source/index resolution. INDEX and QUERY share
only mechanical command acquisition, transaction and terminal persistence code;
their source/execution validation remains separately typed. No source/result cache
or source lock spans inference. No pass-through production executor is supplied.

Additive0054 changes only the native step CHECK, retains the exact0053 predecessor
predicate and refuses downgrade before DDL if any QUERY definition/request/step/
carrier marker exists. The protected release context/admission1.3 and its exact
callbacks pin only0054 with0053 predecessor. Old schema bytes, callbacks/targets,
the0051 wrapper and numerical implementation are unchanged. Source head0054 is
not the installed API/DB head0053; no live migration/activation occurs here.

The official disposable `embedding-stage-tests` gate includes13 new PostgreSQL
QUERY CHECK/downgrade cases. They have not been executed in this source phase:
sudo is unavailable in this shell and the existing finite canary is waiting for
its operator input. No second auth window was started and no credential was saved.
Actual SQLite SQL routing/truth-table and temporary Artifact tests are distinct
from PostgreSQL concurrency, current production IAM or genuine numerical execution.

The global QUERY admission table is deliberately unchanged: even injected ports
cannot create/claim it in production until the concrete installed-purpose executor
and canonical completion owner are ready. `QUERY_QUEUE_LIFECYCLE=SOURCE_PASS` does
not mean `QUERY_PURPOSE_UNIT=ACTIVE` or `GENUINE_QUERY_CONSUMER_READ=PASS`.
The full goal still includes real seed/delta/reuse/query, service reconciliation,
consumer delivery and CPU/GPU/default-selection gates.

Final38-suite **1,004 PASS**,105.47s; strict mypy16 source modules, Ruff/format31
Python files, bash syntax4 scripts and diff PASS. Source Alembic reports the single
head0054. The preceding996-pass run and50/1-case focused runs overlap and are not
summed. Actual SQLite query routing and144-case CHECK truth-table complement the
synthetic current-Identity/numerical lifecycle tests; none prove production IAM.
The PostgreSQL13-case suite was collected, not executed. Initial fixture/closed
callback assertions were corrected and the final complete gate was rerun; source
guards were not weakened. Earlier failure logs remain in the temporary workspace.
At23:23 UTC all9 actual long-running services were active, including the installed
`eom-hwpx-application-runner`; no service, model, policy or DB write was performed.

## Fixed CPU QUERY handoff and invocation — next implementation decision

1. Responsibility: Orchestrator's fixed numerical launch/handoff adapters extend
   the existing CPU mechanism to QUERY; worker still receives only descriptor-bound
   numerical input. Runner's current source/command owner remains upstream.
2. Canonical source: official current preparation and its exact native input are
   selected before staging. Owner-local/root-handoff files are temporary explicit
   materialization, never a source grant, database or canonical Artifact.
3. Identity: one original native Job/execution suffix, exact QUERY request/hash,
   workflow request, policy, bundle and launch association; unit invocation and
   Artifact producer identity are separate. No lease token reaches the worker.
4. Resolution: reparse the five existing frozen schemas and validate their exact
   closure. Root prepares only from private UID990-owned files after a hash-bound
   launch marker. Worker sees input/result/binary descriptors, not actor controls.
5. Access: keyed workspace/exact unit lookup, fixed bounded file reads, one capacity
   lock and bounded active-unit/cgroup inspection. Never restart a nonfresh handle
   or treat an observation timeout as proof of nonexecution.
6. Structures: keep the same existing INDEX CPU-capacity lock path for INDEX/QUERY,
   fixed purpose→unit-pair mapping, immutable typed prepared values and file sets.
   No queue/table/registry/framework/dependency or numerical implementation change.
7. Complexity: O(1) bounded input/output plus O(U) active native-unit/cgroup checks;
   U is bounded by the one-active-launch policy. No re-encoding DOCUMENT vectors.
8. Concurrency: hold the shared flock through prepare/run/terminal readback. After
   controller death inspect both purposes' prepare/main units and surviving cgroups
   before reuse. No SQL root may span any of this. Publication reauthorizes later.
9. Ownership: share mechanical file, capacity and exact-invocation rules; keep
   INDEX/QUERY schema/result checks separate. Root prepare cannot read model/DB/NAS.
   The numerical worker keeps the existing frozen CPU installation and isolation.
10. Failure/replay: exclusive files and same-byte replay only; partial/conflicting
    bytes, missing seals or changed invocations fail explicitly. Known failure and
    uncertainty retain original identity; neither permits a new inference identity.
11. Simpler alternative: a separate QUERY lock or duplicated launcher would permit
    overlap after owner crash and drift in recovery rules. Three small callbacks
    in one fixed-purpose execution function share the actual two use cases without
    introducing a general worker framework or changing released wire contracts.

Deployment is a separate gate: no QUERY unit/polkit activation while an old INDEX
controller may use its INDEX-only surviving-unit check. Quiesce/update controllers
to the shared guard first. The existing finite INDEX canary and frozen CPU prefix
are not replaced/restarted here. Actual QUERY Job/checkpoint/producer closure and
the stronger consumer read remain required even after this physical adapter exists.

## Fixed CPU physical adapter source — 2026-10-13 23:52 UTC

- Added separately typed QUERY staging/materialization and fixed QUERY launcher.
  The five existing request/policy/bundle/association/input schemas are reparsed;
  native Job suffix, paired spaces and exact fixed CPU resource profile are checked.
  Only source-neutral numerical input reaches the worker. Shared no-clobber private
  writes/root descriptor creation retain mode/inode/epoch/bounded-read checks.
- INDEX and QUERY use one fixed CPU execution function and the original INDEX lock
  path. One start or exact terminal reuse; timeout/nonfresh/changed invocation is
  uncertainty, never another execution. Both purposes' prepare/main units and
  surviving cgroups are inspected after a controller crash.
- Actual read-only systemd metadata revealed the installed INDEX prepare uses its
  default per-template slice, unlike the main's explicit system.slice. The guard
  now checks both fixed kernel locations, closes FDs on refusal, rejects symlinked
  parents/missing kernel base and distinguishes an absent terminal group from an
  unobservable membership file. Frozen INDEX template bytes remain unchanged.
- QUERY now has explicit root-prepare dependency and system.slice, separate pinned
  owner environment and exact source-only polkit start exception. The protected
  bootstrap preserves legacy INDEX arity and adds only literal QUERY. Worker/API
  start/restart/stop/enable, prepare-unit and malformed-suffix requests are denied.
  No new rule/template/environment is installed or activated by these source edits.

Final50-suite **1,263 PASS**,119.95s; strict mypy8 source modules, Ruff/format14 and
diff PASS. systemd-analyze verify of the new prepare/query templates PASS with no
diagnostics. A separate actual kernel/systemd inventory read PASS confirms current
native capacity is quiescent; it performs no lock/launch/auth/model/DB mutation.
The earlier1,256-pass run missed the real per-template-slice layout; after that
discovery the additional path/member/FD checks and full regression were rerun.
Focused72/115/152 and earlier full gates overlap and are not summed.

Temporary file IO/flock and Node-composed polkit evaluation are actual; numerical
backend/root UID/unit observations in source tests are explicitly synthetic. No
protected QUERY admission, privileged QUERY probe, genuine model execution, Job,
Artifact or caller-authorized seed/delta/query is proven here. Existing numerical
code/installation, all released schemas/admission, INDEX units and installed rules
remain unchanged. No dependency or DB migration was added in this physical phase.

`QUERY_PHYSICAL_ADAPTER=SOURCE_PASS`, `QUERY_UNIT_INSTALLATION=NOT_PERFORMED`,
`QUERY_JOB_CANONICAL_COMPLETION=NOT_CONNECTED`, `GENUINE_QUERY_CONSUMER_READ=NOT_ACTIVE`.
Next is the original native Job/checkpoint/provenance and canonical receipt owner,
not activation based only on this physical helper. The full original goal remains.
