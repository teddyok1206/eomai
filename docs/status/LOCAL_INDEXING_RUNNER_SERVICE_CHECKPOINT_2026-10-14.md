# Local indexing service Runner checkpoint

2026-10-14 UTC. Continuation of the
[original incremental RAG goal](../architecture/SYSTEM_RAG_SIMILARITY_AND_INCREMENTAL_EMBEDDING_DESIGN.md)
and [Registry service composition](LOCAL_INDEXING_REGISTRY_SERVICE_CHECKPOINT_2026-10-14.md).
This is not production activation or goal completion. The
[authority design](../architecture/LOCAL_INDEXING_SERVICE_AUTHORITY_DESIGN.md#runner-successor-implementation-boundary)
records the responsibility, concurrency and compatibility decisions before code.

## Preserved contracts and shared execution

- JSON Schema2020-12 request1.2 is service-only; execution-policy1.1 pins the exact
  service reference. The Catalog grant pins the native policy; the reverse policy
  does not pin the grant hash, avoiding a hash cycle. Canonical and packaged copies
  are identical. Contract prefix `2403703410b03d937e120ff196ef8d9ad0d74045` is
  independently committed/pushed after an index-only snapshot gate.
- Original request1.1 future service audits remain parseable but non-executable.
  Policy1.0 stays operator-seed-only. The original4 schema resources, fixed numerical
  DAG and input/result/launch/receipt formats retain their bytes and meanings.
- Two explicit current-actor authorities compose one native owner. Human sessions
  still require current operator permission. Service mode requires the actual
  installed-runtime/DB/current-grant/source fence; audit data is never permission.
  A service has its own actor type, not a fake human, WORKER, ADMIN or generic SYSTEM.
- Registry source selection and scope admission reuse the official Catalog authority.
  Service grant and parent source-policy pins remain separate. Source resolution,
  exact Artifact validation and late reauthorization precede mutations.
- Existing submission, indexed claim, lease, encoding reservations, checkpoints,
  crash recovery, Artifact publication and index registration are shared. No second
  target-scanning runner, new queue, DB migration, dependency or numeric reseal.
- Runtime readiness observes the selected numerical controls; it is not current
  authentication. Real authority remains mandatory in each SQL root before effects.
  Copied/wrong audits, revoked scope, changed control bytes and stale leases fail.

## Executed source and disposable evidence

Final source regression: **87 suites /2,340 PASS** in297.35s. Strict mypy67 source
modules and Ruff lint/format113 Python files PASS. New contract19 and service-owner17
cases are included, not added again. The owner cases use actual temporary control
Artifacts and the shared owner/fence algorithms, with explicitly synthetic IAM/source
IO. They do not prove installed service authentication, PDF pixels or numerical work.

Marker-guarded disposable PostgreSQL: runner/stage **61 PASS** in41.01s, including8
additional service-actor claim cases; encoding reservations **9 PASS** in12.58s.
Registry/native-flow **30 PASS** in81.91s on the corrected fixture, including shared
seed/Graph-delta vector reuse and same-output recovery after actual SQL interruption.
These100 distinct cases prove actual SQL roots, claim concurrency, lease/replay/
locking and legacy isolation while retaining synthetic IAM/source/runtime seams.
The final read-only inspection confirms the correct marker/owner, head0055 and0
other connections. Committed synthetic history remains intact. No production DB,
service grant/unit, GPU/model or NAS Artifact was changed by these tests.

Evidence directory: `/tmp/eom-identity-provider-install.nAaycoDM/`.

- `local-indexing-contract-staged-snapshot.log`:258 PASS with only the staged
  contract prefix extracted; independent of the dirty Runner implementation.
- `local-indexing-runner-regression.log`
- `local-indexing-runner-final-{mypy,ruff,format}.log`
- `local-indexing-runner-service-contract.log`
- `local-indexing-runner-service-owner.log` and final regression above
- `local-indexing-runner-postgres.log`
- `local-indexing-runner-encoding-postgres.log`
- `local-indexing-runner-registry-postgres{,-reviewed}.log`
- `local-indexing-runner-inspect.log`

Earlier failures remain preserved. Adding resources to the frozen4-entry family was
rejected and corrected to a separate successor family. Actual `isinstance` misuse of
a Python type alias was fixed with explicit supported classes. Updated unit synthetic
owners and a spec-bound launcher mock preserve their existing denial assertions.
The first Registry/native-flow rerun had25 PASS /5 failures because its synthetic
SourceOwner lacked the new explicit current-actor/caller methods; the fixture now
implements those same ports and keeps its late source-revocation check. Production
authority is not weakened, and failed runs are not relabeled successful.

## Package verification, not installed activation

Code candidate `1cf47fca0c67afec4cea278520958d20a97a570c` built all3 release
wheels; RECORD verification PASS. Fixed dist:
`/tmp/eom-api-build/1cf47fca0c67afec4cea278520958d20a97a570c.w8QoZo/dist`.
The immutable operator interpreter under `-I -B` imported43 named modules from these
wheels, with no checkout/PYTHONPATH or package installation. Both successor schema
hashes and local reference closure, exact request/policy coupling, separate actors
and unchanged old future-service denial PASS. Numeric environments were not resealed.
No DB connection, service/unit/grant activation, model or GPU execution occurred.

Evidence: `local-indexing-runner-wheel-build.log` and
`local-indexing-runner-wheel-import-reviewed.log` in the same directory. The initial
`local-indexing-runner-wheel-import.log` is preserved: the probe used a nonexistent
loader name. Correcting the probe to the supported public loader passed without
changing source or rebuilding the wheels. It was not a runtime service failure.

## Remaining required gates

`SERVICE_RUNNER_COMPOSITION=SOURCE_PASS_AND_DISPOSABLE_CLAIM_PASS`.
`SERVICE_RUNTIME_INSTALLATION=NOT_ACTIVE`.
`AUTOMATIC_RECONCILIATION=NOT_ACTIVE`.

The actual installed entry/provider and least-privilege DB/service-policy activation
remain separate. Do not replace the still-live finite operator controller or infer
its phase from empty output. Genuine bounded persistent seed, source-add delta,
same-key replay and QUERY are still required before the consumers in the original
order. CPU/GPU numerical comparison has not run; device default is unchanged.

## Official reconciliation follow-up

The source now connects the supported Catalog missing-binding observation to the
existing atomic Workflow/START application. New observations authenticate before
selecting the current corpus head, then pin that exact published Graph and policies.
Historical work still resolves its saved revisions, never latest. A typed prepared
lookup reuses the once-materialized population for deterministic bounded target
selection; no second report scan, target registry, queue, outbox or DB migration.

The service owner resolves the exact published native policy/profile before control
reads and reauthorizes late. Orchestrator publishes a plan before native submission;
retained service/source locks protect the preparation root. Model execution occurs
later through the existing executor, never under those locks. A crash between plan
commit and atomic submission can leave only a reusable validated control, not a fake
completed embedding. Fixed request/encoding keys retain all existing concurrency rules.

Unattended control publication allocates its first actual UTC time under the existing
publication lock, and subsequent exact calls reuse it. Fixed-time and explicitly
allocated publication retain their previous strict time/provenance semantics and
pre-lock file validation. No fake timestamp or new timestamp registry is introduced.
Small plan-control keys distinguish owner-code provenance; numerical encoding keys
do not change, so that distinction cannot force duplicate vector computation.

The result distinguishes no published Graph, no eligible source, accepted-report
wait, unavailable view, up-to-date coverage, queued/replayed work and terminal
incomplete history. Missing reports never get placeholder vectors or empty Jobs.
Saved failures are not reset or bypassed by inventing retry identities. Report
arrival can become new work without relabeling an earlier wait as completion.

Actual marker-guarded PostgreSQL evidence: **70** service/Identity/policy tests,
**63** stage/runner tests, **32** Artifact/Registry/native-flow tests and **9**
encoding reservation tests PASS: **174 distinct cases**, not repeated-run totals.
Four new actual cases verify first-time publication concurrency/recovery and
independent reconciliation roots producing one Workflow/START, plus a real outer
rollback after submission savepoint retaining/reusing its committed plan. Service
IAM/population/runtime are explicitly synthetic in those new execution cases.
No model, GPU, actual service unit/authentication or production mutation is proved.
Final DB inspection: marker/owner PASS,0055,0 other connections, read-only.

Final follow-up regression: **88 suites /2,370 PASS** in306.40s. Strict mypy69 source
modules, Ruff lint/format120 Python files, additional disposable-tooling89 source
tests, shell syntax and diff checks PASS. The new unit cases are included in that
2,370, not summed again.
Evidence in the same directory:

- `local-embedding-reconcile-focused{,-reviewed}.log`
- `local-embedding-reconcile-regression{,-reviewed}.log`
- `local-embedding-reconcile-final-{mypy,ruff,format}.log`
- `local-embedding-reconcile-{policy,stage,encoding}-postgres.log`
- `local-embedding-reconcile-artifact-postgres{,-final}.log`
- `local-embedding-reconcile-{inspect,tooling}.log`

Initial new-owner tests exposed a missing policy-metadata prefetch before member
closure validation. The shared control reader now performs the supported prefetch;
an already-prefetched batch does no additional query. The first full source run had
2,367 PASS/1 fixture failure: a supposed foreign namespace was its unchanged view.
The fixture now chooses a genuinely different view; the production guard is intact.
The earlier type check also caught an accidentally widened fixed-policy timestamp
signature. It is restored; an explicit internal time strategy, not a public None
fallback, distinguishes the new unattended path. All original failed logs remain.

This is a callable source application, **not an activated automatic service**.
Actual installed entry/provider, least-privilege admission, bounded genuine seed,
source-add delta, replay/QUERY, consumers and CPU/GPU comparison remain required.

Code candidate `703f05571c43a9c843d6d393a1b2ca2c7a9e41bc` built all3 wheels with
RECORD verification PASS. Fixed dist:
`/tmp/eom-api-build/703f05571c43a9c843d6d393a1b2ca2c7a9e41bc.S3gsS6/dist`.
The existing immutable interpreter under `-I -B` imported the prior named modules
and new reconciliation application from these wheels only. Successor schema/ref
closure, old audit-only rejection, frozen observations, no default authority and
the distinct observed-time/fixed-time publication APIs PASS. No source checkout,
package installation, DB connection, unit change or numerical execution occurred.
Evidence: `local-embedding-reconcile-wheel-{build,import}.log` in the same directory.

## Purpose-only installed-service source checkpoint

The next source candidate adds a stdlib installed entry, one packaged canonical
systemd template and actual service composition over the existing Runner. No new
queue, service framework, DB migration, dependency, Codex role/slot or operator
impersonation. The template is not installed or started by source tests.

`local-indexing-owner-configuration/1.0` is a closed, non-secret, bounded64KiB
selection contract. Canonical and packaged schema SHA:
`9d31827404897c154c0412b74f00112cf5f8192b0fd668bdf27801a26b7e3e39`.
It pins the exact namespace, source classes, grant, native policy/profile, DB fence
owner and protected numerical verifier/env hashes. It is not a credential or data
grant. The actual captured process reads only the fixed root selection file and
binds it to its own pre-start file epoch. Keeping selection separate from the main
runtime-configuration hash avoids a grant/configuration hash cycle. Existing main
runtime and historical request/policy schema bytes are unchanged.

Native-only Runner construction accepts no fake available roles, does not build
the role executor or read worker YAML, and uses existing command/claim/lease/
heartbeat/recovery. Exact actor selection filters the same bounded FIFO queue;
the real owner must still authenticate and authorize the claimed command. Default
mixed-role composition remains unchanged. The total native-quarantine predicate
also now includes service request1.2: a malformed service-only marker cannot fall
through to an ordinary role workflow.

The Catalog runtime privilege contract previously omitted four embedding tables
and native command/step writes. The existing role's explicit matrix now includes
only required reads/inserts and mutable index/command/step updates. No DELETE,
DDL, role membership, Identity writes or new policy-publication privilege. This
source change has **not** applied GRANT or proved the actual runtime-role matrix.

Final source regression: **93 suites /2,427 PASS** in308.26s. A subsequently added
canonical packaged-unit test passed in a separate **62-case** focused gate; those
overlapping cases are not summed with the regression count. Strict mypy74 source
modules and Ruff lint/format131 Python files PASS. Initial11 regression failures
were stale hand-built Runner fixtures and unspecced verification mocks; fixtures
were corrected without production fallback. A subsequent focused lambda fixture
and one constant's widened type annotation were corrected. Original logs remain.

Current marker-guarded actual PostgreSQL: **67** stage/Runner cases PASS, including
exact actor selection and request1.2 quarantine; **70** service/Identity/policy
cases PASS. SQL/claim/transaction behavior is real, but IAM/runtime/source seams
remain synthetic. They are not actual installed-service authentication evidence.
The **32** Artifact/Registry/native-flow and **9** encoding-reservation cases also
PASS on this candidate, yielding **178 distinct** actual disposable-DB cases.
Final read-only inspection: marker/owner PASS,0055,0 other connections.

The fixed numerical-verifier adapter runs the protected existing no-forward check
with a fresh four-key environment and no controller credentials. Two read-only
invocations under the ordinary eom user passed; the timed one took **12.03s** and
272064KiB maximum RSS. This is a known verification cost, **not** a model-forward,
service-sandbox admission, CPU/GPU comparison or performance improvement claim.

Evidence in the same directory:

- `local-index-owner-regression-{initial,reviewed}.log`
- `local-index-owner-focused-reviewed.log`
- `local-index-owner-final-{mypy,ruff,format}-reviewed.log`
- `local-index-owner-final-added-reviewed.log`
- `local-index-owner-{stage,policy}-postgres.log`
- `local-index-owner-{artifact,encoding}-postgres.log`, `local-index-owner-inspect.log`
- `local-index-owner-numeric-readonly-{check,timed,timing}.log`

Actual installation, supported0053→0054→0055 migration/admission, role reconciliation,
service/grant activation and original-controller quiescence are still pending.
The original finite operator controller was observed alive at2026-10-14 08:59 UTC
with no terminal output. No replacement, extension or inferred success occurred.
Genuine bounded persistent seed, source-add delta, same-key replay/QUERY, downstream
consumers and CPU/GPU comparison remain required by the active goal.
