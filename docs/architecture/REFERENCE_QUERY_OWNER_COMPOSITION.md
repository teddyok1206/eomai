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

## QUERY Job and canonical completion — 2026-10-14 UTC decision

1. Boundary: extend the existing Orchestrator Job/event and file-set owners. Runner
   still owns current Workflow/command/source authorization; no new queue/service.
2. Canonical source: immutable request/launch events and committed Artifact members.
   Checkpoints are bounded immutable continuation metadata, never IAM evidence.
3. Identity: native Job, query-publication producer and receipt producer are distinct;
   one Workflow/step/request key retains its original launch through recovery.
4. Resolution: validate the literal request/launch and new closed checkpoint schema,
   registered protocol hash, event transitions, producer/member/hash/time closure.
5. Access: indexed Job-key lookup, Workflow/command-then-Job locks and ordered event
   prefixes. No text/vector/result bytes in the coordinator's SQL values.
6. Structures: four contiguous ALLOCATION/EXECUTED/PUBLISHED/COMPLETED events,
   existing unique Job key and immutable typed publication pointers; no new table.
7. Scale: O(log J + H) indexed lookup/history, H<=4 checkpoint records; bounded
   metadata and four-member Artifact reads. No repeated corpus encoding or scans.
8. Transactions: caller retains current owner fences in each nonnested root. Record
   allocation before launch; observe units outside SQL; freshly authorize before
   checkpoint/publication. Actual successful unit observations are pinned once.
9. Dependency: pure contracts do not import systemd/SQL; Orchestrator adapts unit
   observations and publishes, Catalog reads committed/approved exact producers.
10. Replay: exact phase replay is read-only; conflicts, gaps, altered jobs and known
    failures fail closed. Preallocated publication identities prevent a crash from
    producing a different owner. Checkpoints grant no permission to restart a unit.
11. Alternative: inferring execution from a PNG/vector file or storing a success
    boolean loses the original invocation/producer closure. Reusing INDEX's protocol
    would mislabel purpose. Separate small QUERY frames preserve both histories.

No numerical execution, activation, service identity or consumer acceptance follows
from these source/storage checks. Those remain explicit gates of the original goal.

Crash review also found that a fresh systemd handle alone cannot distinguish an
unstarted Job from an earlier dispatch whose unit observation was lost on reboot.
Before StartUnit, both source INDEX/QUERY adapters therefore atomically consume a
private, fsynced `.dispatch-attempted` marker under the existing shared capacity
lock. Exact terminal readback remains allowed; fresh-but-consumed handles fail
uncertain without another start. A crash between marker and StartUnit is uncertain,
not permission to guess that execution never happened. Existing installed INDEX
code/templates and the waiting finite canary are not changed by this source fix.

## Original Job, canonical completion and dispatch safety — source implementation

- A separate closed2020-12 checkpoint schema and frozen models preserve released
  INDEX, QUERY input/result/receipt and queue contracts. No migration/dependency.
- Orchestrator keeps one indexed Workflow/step/request native Job with the literal
  QUERY protocol and original launch event. Four contiguous typed events validate
  protocol hashes, state transitions, distinct producer identities, exact files,
  successful unit observations and monotonic/publication time order. Reentry never
  allocates a replacement native Job, overwrites a checkpoint or repairs failure.
- Existing file-set publication gains optional identified QUERY publication and
  purpose-specific self-identifying completion. Catalog resolves its real approved
  producer/member/hash and exact manifest, not just an in-memory receipt. Shared
  INDEX/QUERY helpers contain only file publication/read mechanics; purpose schema,
  timestamps and errors remain independent. Metadata only is stored in SQL.
- The concrete completion owner first fences the actual current Workflow/command/
  step/source, then validates original Job history and canonical receipt/four files,
  reconstructs the exact native input from current approved sources and fences late.
  It checks the attached step's producer rather than trusting a detached object.
  Historical successful unit observations do not require another numerical launch
  or surviving old units just to read a committed result.
- The fixed QUERY launcher can capture exact successful prepare/query invocation,
  template/environment hashes, boot and timing metadata after validating its result.
  INDEX/QUERY consume one atomic/fsynced owner dispatch marker under the existing
  capacity lock. Fresh systemd metadata after an uncertain dispatch cannot restart
  it. A terminal read still reuses the exact result without a new dispatch claim.

These are source/storage boundaries, not a default native executor. The global
QUERY definition remains unoffered. Concrete executor composition and supported
original-claim/pending recovery are still required before activation. No stronger
`VerifiedReferenceQueryRead` is returned by a storage-only adapter. Service identity,
consumer delivery, real seed/delta/query and CPU/GPU selection remain in scope.

Final57-suite **1,382 PASS**,143.98s; strict mypy14 source modules, Ruff/format22
Python files and diff PASS. The preceding1,371-pass full run predates the durable
dispatch fix; focused80/99 and earlier53/44 gates overlap and are not summed.
Initial test fixtures for canonical UTC/hash and stable conflict codes were
corrected, then the final complete gate was rerun without weakening source guards.
Actual temporary SQLite Job/events, file-set commit/read/replay, hashes, local
concurrent dispatch claims and forgotten-handle no-second-start paths are covered.
Current IAM/source derivation/unit observations remain explicit synthetic seams;
none of these tests prove production authorization or numerical execution.

No production Job/Artifact, DB migration, service restart, model forward, GPU work
or QUERY installation was performed. The prior13-case PostgreSQL QUERY migration
gate remains collected-only, not PASS. The original finite INDEX controller was
read-only observed at00:17 UTC still waiting for its existing input; it was not
replaced or reauthenticated. Source logs are retained in the existing temporary
workspace as `query-canonical-final-regression.log` and
`query-canonical-mypy-final.log`. No new auth window or saved credential was added.

`QUERY_JOB_HISTORY_STORAGE=SOURCE_PASS`, `QUERY_COMPLETION_OWNER=SOURCE_PASS`,
`QUERY_EXECUTOR_COMPOSITION=NOT_CONNECTED`, `QUERY_CLAIM_RECOVERY=NOT_IMPLEMENTED`,
`QUERY_UNIT_INSTALLATION=NOT_PERFORMED`, `GENUINE_QUERY_CONSUMER_READ=NOT_ACTIVE`.

Post-commit packaging: source `3fecb3f332024768fc58150cbbd7a9168d94f1bc`
produced the existing three-wheel release set; build/RECORD/installed simulation
PASS. A separate `-I -B` import in the immutable operator Conda environment loaded
all10 selected modules only from those wheels and validated a synthetic checkpoint
against the packaged/pinned schema and local reference closure. No checkout import,
runtime installation, DB/auth/unit or model action. Evidence remains in
`query-canonical-wheel-build.log` and `query-canonical-wheel-import.log`; wheel set
`/tmp/eom-api-build/3fecb3f332024768fc58150cbbd7a9168d94f1bc.yKggmi/dist`.
All9 actual long-running services were active at final read-only verification.
This documentation follow-up does not replace the tested code candidate or activate it.

## Concrete QUERY executor and original recovery — 2026-10-14 decision

1. Responsibility: compose the existing current Catalog owner, fixed QUERY launcher,
   Job checkpoints and canonical publishers inside Runner; no second numerical path.
2. Canonical source: current official sources/index plus original Job/launch and
   committed artifacts. Local staged bytes are explicit temporary materialization.
3. Identity: allocate native/query/receipt identities once; every later acquisition
   rejoins the exact Workflow/step/request and original launch, never a new attempt.
4. Resolution: derive native input from current sources using original IDs; compare
   launch/input hashes, runtime/policy/bundle and published result/receipt closure.
5. Access: one indexed launch lookup and bounded four-event prefix per fenced root;
   ready-queue polling reuses the existing command queue and unique operation keys.
6. Structures: existing frozen checkpoint union and an internal typed BUSY/UNCERTAIN
   pending value. No new worker/wire schema, DB table, queue, registry or dependency.
7. Complexity: bounded native input (three views), O(log J + H) history H<=4; current
   source/index preparation retains its existing bounded cost. No DOCUMENT encoding.
8. Transaction: fresh Workflow→command→Job locks and actual source/session checks
   surround short mutations. Run/observe numerical units only outside SQL roots.
9. Dependency: Runner owns composition, current claim and continuation; Orchestrator
   alone dispatches/publishes; Catalog owns canonical reads. No domain adapter import.
10. Failure/replay: busy/uncertain remains pending for the same Job. Durable dispatch
    consumption prevents a fresh-looking old unit from rerunning. Known failure is
    terminal and preserved; malformed, revoked or changed current inputs fail closed.
    Claim recovery requires original nonfailed allocated history, not mere expiry.
11. Alternative: treating a timeout as failure/retry, using INDEX results or returning
    a synthetic success loses original ownership. Extend existing native step/claim
    behavior with the purpose-specific owner; keep global admission unoffered until
    the actual installed QUERY/release and consumer gates are verified.

## Concrete executor, pending and recovery — source implementation

- `CatalogNativeReferenceQueryExecutor` composes the actual source owner, fixed
  QUERY launcher and canonical completion owner through the existing Runner port.
  Constructor rejects different DB/NAS owners; readiness reads configured controls
  and exact fixed CPU limits without creating a Job or authenticating a caller.
- Execution allocates once, derives current native input using original IDs, stages
  only under a fresh owner root, then runs/observes units outside every SQL root.
  One/two/three available views retain the configured batch4 instead of resizing.
  Successful proof is checkpointed once; repeated observers must match the same
  invocation/environment/result, not overwrite its original observation time.
- Canonical query publication and receipt completion have separate short roots.
  A real SQLite composition test exposed a write-lock conflict when a second owner
  committed while PUBLISHED was uncommitted. Splitting the responsibilities/roots
  fixed it without DB-specific retries, weaker isolation or changing publisher rules.
  Publication checks the observed result hash before any commit. Four before/after
  publication crash cases preserve original producers and never reencode.
- BUSY, uncertain observation and unavailable capacity retain original Job identity.
  The internal pending value is not a worker/wire result. Runner validates its actual
  original history, defers on the same indexed queue (5–60s), and keeps the step
  RUNNING. A late exact completion is canonically validated, not treated as failure.
- Current claims allow a fresh poll or an expired acquisition only with the exact
  original application step and nonfailed allocated history. Expiry alone is never
  proof of nonexecution. Current user/source checks precede recovery and repeat late.
  No new native attempt, identity or direct row repair is used.
- Known failure is recorded only through Orchestrator's supported coordinator,
  including its stable Job error code. Existing failed history is never repaired.
  The shared INDEX/QUERY adapter recognizes already-failed and newly-failed units
  only after empty cgroups, stable invocation and current runtime checks. Timeout,
  changed invocation or surviving children remain uncertain; none authorize restart.
- The declarative QUERY YAML matches the frozen definition/protocol and is still
  unoffered/uninstalled. No new dependency, schema meaning, table, migration, queue,
  numerical code, CPU installation or installed INDEX template was changed.

Actual temporary Job/Artifact/FS tests are distinct from their explicitly synthetic
IAM, Workflow SQL/source and numerical seams. The official disposable
`embedding-stage-tests` gate now includes5 QUERY PostgreSQL commit/crash/replay
cases behind its existing owner/marker/head checks. They were collected, not run;
the prior13 QUERY CHECK cases remain unexecuted too. No production DB is a test
target, and none of these source checks prove genuine numerical or IAM acceptance.

The existing finite INDEX controller3416211/3416258 was confirmed live at00:54 UTC;
its original output log still had0 bytes. This is not proof of a completed capture
or seed/delta; their acceptance remains pending. No replacement process,
new login window or credential persistence was introduced. The full goal still
includes actual seed/delta/reuse/query, official service reconciliation, consumers,
CPU/GPU performance/default selection, installed release and genuine read gates.

`QUERY_EXECUTOR_COMPOSITION=SOURCE_PASS`, `QUERY_CLAIM_RECOVERY=SOURCE_PASS`,
`QUERY_GLOBAL_ADMISSION=UNOFFERED`, `QUERY_UNIT_INSTALLATION=NOT_PERFORMED`,
`GENUINE_QUERY_CONSUMER_READ=NOT_ACTIVE`, `POSTGRES_QUERY_PERSISTENCE=NOT_RUN`.

Final59-suite **1,459 PASS**,205.70s; strict mypy20 source modules, Ruff/format31
Python files, shell syntax and diff PASS. The prior205.77s run had the same count;
after extracting one test factory for SQLite/PostgreSQL and adding the guarded
test-harness branch, the complete gate was rerun. Earlier168/14/39/47/114/focused
results overlap and are not summed. The initial actual SQLite lock ordering bug
was fixed by splitting publication roots; fixture/import and assertion-placement
failures were corrected before the final full gate, without loosening source guards.
The5 new PostgreSQL cases collected in0.50s and were NOT executed.

No production Job/Artifact, migration, service restart, numerical forward, GPU work,
QUERY unit/polkit installation or credential change was performed by this source
work. No default executor/admission was silently activated. The full goal remains
active; source verification does not close its installed, genuine read, automatic
service, consumer or CPU/GPU/default-selection gates.

Build-only verification of code candidate
`16fb1fec2f95f99e1200b20a86305cd0fbebd432` produced the existing three release
wheels and passed RECORD/installed simulation. An isolated `-I -B` invocation of
the immutable operator Conda interpreter imported17 QUERY/executor/publication
modules from those wheels only and validated the packaged checkpoint schema/hash
and reference closure. No checkout import, installation, database/auth/model/unit
mutation occurred. This documentation follow-up is not another code release.

## Completed QUERY consumer read — implementation decision

1. Responsibility: a Runner composition adapter implements Catalog's existing
   `SimilarityReferenceQueryReadPort`; Catalog must not import Runner tables.
2. Canonical source: the exact completed Workflow, original native Job's four
   checkpoints, committed receipt and query file set, plus current official sources.
3. Identity: trusted composition pins one Workflow ID and exact request; it never
   looks up latest or accepts arbitrary Artifact paths/producer claims from a model.
4. Resolution: actual captured operator, installed policy/bundle, current source/
   index preparation, terminal Workflow/step, native admission provenance and all
   canonical member hashes must match before returning the stronger read value.
5. Access: primary-key Workflow lookup, unique step lookup, indexed original Job
   identity and bounded immutable file-set reads. No scan for an equivalent result.
6. Structures: existing frozen pointers/DTOs and original checkpoint tuple; no new
   DB table, registry, cache, queue or wire schema. This is an internal read port.
7. Complexity: bounded preparation/index validation and O(query rows × dimension)
   file verification; bytes exist only at the declared local numerical boundary.
8. Transaction: one fresh read root, current identity before any history read and
   a late identity/source fence before return. No lease acquisition or writes.
9. Dependencies: Runner composes Catalog/Orchestrator public reads; shared canonical
   completion logic is reused instead of duplicating storage/lifecycle rules.
10. Failure: missing/stale/revoked/mismatched/unfinished history fails explicitly;
    read never starts a unit, creates a Job, repairs history or renews a session.
11. Simpler alternative: storage-only reading cannot prove actual current authority
    or genuine QUERY execution. Conversely, requiring a live execution command
    lease to read a completed result would force unnecessary execution/recovery.

The adapter alone does not offer the QUERY workflow or activate any consumer. Its
tests distinguish actual temporary Job/Artifact bytes from synthetic IAM/Workflow
SQL/numerical seams; live source and installed purpose gates remain mandatory.

### Completed-read source implementation

`CatalogCompletedReferenceQueryRead` pins one trusted Workflow/request and implements
the existing Catalog port. Each call resolves actual current operator and official
source/control/index scope in a fresh root, checks the exact successful terminal
Workflow/step and original four-checkpoint native Job, and reads the canonical
receipt/four-member file set through the existing owner readers. It rechecks the
current source/terminal closure after materialization before returning the stronger
read value. There is no latest lookup, cached grant, command acquisition, unit-state
requirement, numerical invocation, registration or history repair.

`NativeReferenceQueryCompletion.resolve_publication` is shared by completion and
read composition: storage producer/manifest/hash/current-input derivation checks
have one implementation. `validate_completed_native_workflow` shares the terminal
shape/pointer checks with INDEX/QUERY terminal replay. The completed reader alone
requires the fourth checkpoint; a publisher legitimately validates the first three
before it appends completion. Scope errors use one public registry-to-context mapping
at both adapters; Identity/terminal errors become stable context failures, not raw
Workflow exceptions or uncaught API errors. No old guard was removed.

The guarded PostgreSQL suite now has6 cases, including original completed-query
read/replay. These remain collection-only; this source implementation does not
replace the official PostgreSQL/IAM/installed-purpose/model/consumer gates.

`COMPLETED_QUERY_READ_ADAPTER=SOURCE_PASS`,
`GENUINE_QUERY_CONSUMER_READ=NOT_ACTIVE`, `QUERY_GLOBAL_ADMISSION=UNOFFERED`.

Final60-suite **1,499 PASS**,264.06s; strict mypy24, Ruff/format36, shell syntax
and diff PASS. The earlier1494/134/69 results overlap and are not summed. Tests
cover actual temporary Job/Artifact/file reads and immutable original identities;
current Workflow SQL/IAM and numerical execution remain explicit synthetic seams.
The6 PostgreSQL cases collected in0.52s and were NOT run; the old13 CHECK cases
also remain unexecuted. A test-only invalid constant import and old error-message
compatibility assertions were corrected before the final gate; no invariant or
negative test was weakened. The shared adapter maps owner/Identity failures into
stable context errors, and tests cover canonical member corruption, partial/failed
history, foreign context/operator and revocation/source change during reading.

This work changes no released schema, DB head, installed runtime, service, native
unit/polkit rule, production Job/Artifact, model/GPU or credentials. Existing live
canary/session handles were not replaced. Actual seed/delta/reuse/query, compatible
QUERY installation/admission, automatic service reconciliation, consumer activation
and CPU/GPU/default policy remain separate required goal gates.

Build-only verification of code candidate
`0d4ad53858855e998da2cc665dcd0eb9f1f1deab` passed the existing three-wheel build,
RECORD and installed simulation. The immutable operator interpreter imported21
modules from those wheels only under `-I -B`, including the new consumer adapter,
shared terminal validator and Catalog error mapping, and validated packaged schema/
hash/reference closure. No checkout import or installed/runtime/model mutation was
used. A final read-only systemd check at01:57 UTC found all9 related services active;
this is service health, not genuine QUERY/seed/delta or consumer acceptance.

## First actual PostgreSQL QUERY gate — storage identifier decision

The guarded disposable gate exposed that the full checkpoint JSON schema version
`native-reference-query-coordinator/1.0` exceeds the existing protocol registry's
32-character key. SQLite source fixtures did not enforce that SQL length. Preserve
the released JSON schema/version/hash and the registry column; use the explicit
internal registry key `native-query-coordinator/1.0` with that exact schema hash.
This is a storage protocol identity, not string truncation, a schema alias, latest
fallback or a reinterpretation of existing bytes. Actual PostgreSQL could never
have committed the overlength key; no production QUERY history is migrated or
repaired. Missing/hash-mismatched protocol records still fail explicitly. Add a
source column-bound regression and run the actual commit/crash/read/replay suite.

The same gate exposed test-only assumptions: an old fixed head, mutation of
immutable fixture snapshots after insertion, and two queue families when there
are now three. Seed the intended synthetic identities at INSERT, retain all
immutability/downgrade checks, compare the unchanged actual admitted head and
require exactly one indexed peek statement per family. Do not disable triggers,
weaken constraints, stamp history, repair rows or use production as a test target.

Committed synthetic claim history made an old positive "empty database" assumption
invalid on the second run. That one positive0053 DDL case now uses empty PostgreSQL
temporary table schema copies (`LIKE ... INCLUDING ALL`, no copied data), seeded
before mutation with the exact CHECKs. Its local search path and DDL roll back in
the existing guarded outer transaction; the test also asserts the real app CHECK
is unchanged. All history/immutability/negative tests still use actual app tables.
No old row, failed event or trigger is removed or rewritten to make a test pass.

### Actual disposable PostgreSQL acceptance, 2026-10-14 UTC

The existing official private state
`/tmp/eom-api-testdb-20261007114938_c6970ffc` passed owner/schema and database/role
marker checks. Read-only inspection (including server `transaction_read_only=on`)
found head0050 and no other connections. The existing supported migration purpose
performed0050→0054,0054→0053→0054 and control/immutable-trigger checks successfully.
No root authentication, fresh DB/role, credential copy, production mutation or
manual stamp/row repair was needed. The protected existing test state is retained.

Actual complete gates, not collected-only or summed overlapping retries:

- stage/runner/QUERY47 PASS,27.94s; same DB replay47 PASS,28.11s. Includes the
  previously unrun13 QUERY CHECK and6 commit/crash/read/replay cases;
- Artifact/index/bundle/registry/application/completion/native executor28 PASS,
  77.52s;
- encoding reservation/concurrency9 PASS,12.40s.

These are84 different PostgreSQL cases. Query publication/receipt/Job/index bytes
and transaction/concurrency behavior are actual; IAM/Workflow/numerical seams in
the composed tests remain explicitly synthetic, not installed or real-corpus
acceptance. Initial21 failures (26 PASS) and the next1 isolation failure (46 PASS)
are preserved in logs. The actual32-character defect, immutable-seed/head/peek
fixture assumptions and retained-history positive isolation were fixed without
weakening the application guards, deleting rows or changing released schemas.

Final60-suite source **1,501 PASS**,263.42s; strict mypy24, Ruff/format39,
shell/diff PASS. Focused94/95 and earlier1499/1494 counts are not aggregated.
Final disposable inspection found head0054, server read-only mode and0 other
connections. Production API live/ready returned LIVE/READY at02:14 UTC. No
production migration, service/unit/polkit, model/GPU, credentials or runtime
activation was changed. The original finite INDEX controller3416211/3416258 was
confirmed live at02:09 UTC; its original log remained0 bytes, not capture/seed
completion evidence. No replacement process, auth-pane capture or new login was
performed.

`POSTGRES_QUERY_CHECK=PASS`, `POSTGRES_QUERY_PERSISTENCE=PASS`,
`POSTGRES_EMBEDDING_BOUNDARIES=PASS`, `QUERY_GLOBAL_ADMISSION=UNOFFERED`,
`GENUINE_QUERY_CONSUMER_READ=NOT_ACTIVE`, `REAL_SEED_DELTA=PENDING`.
