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

## Remaining required gates

`SERVICE_RUNNER_COMPOSITION=SOURCE_PASS_AND_DISPOSABLE_CLAIM_PASS`.
`SERVICE_RUNTIME_INSTALLATION=NOT_ACTIVE`.
`AUTOMATIC_RECONCILIATION=NOT_ACTIVE`.

The actual installed entry/provider and least-privilege DB/service-policy activation
remain separate. Do not replace the still-live finite operator controller or infer
its phase from empty output. Genuine bounded persistent seed, source-add delta,
same-key replay and QUERY are still required before the consumers in the original
order. CPU/GPU numerical comparison has not run; device default is unchanged.
