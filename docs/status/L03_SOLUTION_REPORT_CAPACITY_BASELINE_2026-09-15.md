# L03 solution-report capacity baseline — 2026-09-15

Status: `BOUNDED_SCALE_OUT_MEASURED`; `RECOVERY_SOURCE_HARDENING_PASS`

Observed at: 2026-09-15 14:51:56 UTC

The first section is an early read-only L03 measurement collected while M01 was running on one
runner. Its transaction used `REPEATABLE READ` and `SET TRANSACTION READ ONLY`; no Item content,
worker output, prompt, secret, or storage path was emitted. A later section records the separately
reviewed bounded two-runner activation and will compare throughput under the same workload family.

## Measurement identity

The target population is the occurrence-backed original past-exam solution-report campaign using
`knowledge-analysis-request/10.0`. The separately approved trusted-RAG canary remains outside the
520-Item denominator.

Latency uses append-only state events rather than `KnowledgeAnalysisRun.completed_at`. Some
historical records use that field for policy-controlled domain timing, so treating it as wall-clock
runtime would produce a misleading capacity result. The accepted observation time comes from the
single transition event with `new_state = 'ACCEPTED'`; Job queue and execution times come from the
`QUEUED`, `RUNNING`, and `SUCCEEDED` Job events.

## Observed result

| Metric | Value |
| --- | ---: |
| latest accepted sample | 100 |
| analysis create → accepted p50 | 259.199 s |
| analysis create → accepted p95 | 578.120 s |
| analysis start → accepted p50 | 239.078 s |
| analysis start → accepted p95 | 352.035 s |
| Job queue wait p50 | 0.178 s |
| Job queue wait p95 | 0.195 s |
| Job running p50 | 235.965 s |
| Job running p95 | 348.707 s |
| accepted during prior 60 minutes | 13 |

During that 60-minute window, support slot 05 had 12 released knowledge-analysis leases and one
active lease. Slot 06 had no knowledge-analysis lease. At the snapshot boundary there was one
claimed and one pending Workflow command, corresponding to one running and one requested V10
Workflow.

The short queue wait and approximately four-minute Job median indicate that model execution under
the single persistent command consumer, rather than the indexed PostgreSQL claim itself, dominates
the observed wall time. This is a measured inference, not a proof that adding another consumer is
safe or that throughput would double.

## Original decision boundary

M01 continues on the existing supported topology because it is producing accepted successors with
zero current failures. An ad-hoc transient runner is not introduced during the campaign. Before
using slot 06 concurrently, L03 must close the already documented bounded scale-out boundary with:

- one tracked management/install path for the exact second unit;
- distinct generated runner identities and existing fenced `SKIP LOCKED` command claims;
- shared-runtime deployment fencing and deterministic removal before release;
- global and support-pool capacity assertions;
- concurrent duplicate-command, duplicate-Job, and duplicate accepted-successor tests;
- service identity, sandbox, rollback, and post-removal verification; and
- a bounded before/after throughput measurement under the same workload family.

Until those gates exist, the single persistent runner remains the canonical safe runtime.

## Bounded scale-out activation

Those gates were subsequently implemented and committed as `823f7be`. The implementation extends
the existing runner boundary instead of introducing a queue or scheduler: two distinct runner
identities consume the indexed PostgreSQL command queue with the existing `FOR UPDATE SKIP LOCKED`
claim and capacity-lease fencing. The exact installed canonical unit and staged accelerator unit
both had SHA-256
`1688c77a606ea647d498aacbb3f8f75265f459cf888e1495ae82a8d2887b2878`.

At 2026-09-15 15:05 UTC, a repeatable-read preflight showed two M01 commands, one running support
Job on slot 05, slot 06 free, zero current corpus failures, and zero API idempotency claims. The
operator manager then adopted the exact staged accelerator without replacing its bytes. Immediate
post-start verification showed:

| Invariant | Result |
| --- | --- |
| canonical runner | active, PID 3093849, restarts 0 |
| accelerator runner | active, PID 3193838, restarts 0 |
| active target commands | 2 distinct `PROCESSING` commands |
| active support Jobs | 2 |
| knowledge-analysis leases | slot 05 = 1, slot 06 = 1 |
| current target failures | 0 |
| capacity | knowledge analysis 2/2, support 2/2, global Codex at or below 3 |
| accelerator warnings | none |

This section establishes correct bounded admission. The later measurement below records the
available post-start completion window. At M01 completion, the accelerator is removed through the
exact manager path and the single canonical runner state is reverified.

## Bounded scale-out measurement

At 2026-09-15 15:59:28 UTC, after M01 had safely stopped on a new failed leaf, the same read-only
event query measured the completed two-runner window. From the 15:05:22 UTC activation boundary
through the last accepted result at 15:38:50 UTC:

| Slot | Accepted | Job run average | Job run p50 | Job run p95 |
| --- | ---: | ---: | ---: | ---: |
| 05 | 8 | 243.292 s | 227.928 s | 306.204 s |
| 06 | 9 | 213.986 s | 180.309 s | 293.600 s |
| total | 17 | — | — | — |

Both slots completed useful work with an approximately even distribution. The observed interval is
about 33.5 minutes, corresponding to roughly 30 accepted results per elapsed hour while work was
available. The earlier single-runner observation was 13 accepted during its prior 60-minute window.
This is evidence that bounded scale-out improved throughput for this workload; it is not a durable
SLO or a controlled benchmark because the windows differ and model latency varies.

The latest-100 sample retained a 0.176-second Job queue p50 and a 232.068-second Job runtime p50.
This reinforces the earlier conclusion that model execution dominates indexed queue wait. The
capacity remained global Codex 3, knowledge analysis 2, support pool 2, with slots 05 and 06. No
capacity ceiling was raised during measurement.

The stop itself was correct. A worker returned duplicate node identities in a V10 solution step;
the existing validator rejected it before Artifact commit and the automation terminal-failure fence
stopped refill. At that boundary the typed corpus was 362 completed, 157 pending, 1 failed, and 0
active, with zero active Jobs, leases, or Workflow commands. M01 recovery is recorded separately;
the failed history is not a capacity failure and is not rewritten.

## PostgreSQL recovery inventory

The fixed NAS backup root contains ten dump/manifest pairs. The newest observed pair is:

| Field | Value |
| --- | --- |
| created | 2026-09-12 10:03:59 UTC |
| dump bytes | 754,489,658 |
| dump SHA-256 | `27e15767eb32361b597290c27c132d9fa6f0add4374df5d90cf581521096084f` |
| file shape | regular, single link, `eom:eom`, mode `0660` |
| manifest | strict historical six-field format; exact hash and size match |

The source candidate now defines JSON Schema 2020-12 and a frozen Pydantic model for new
`postgres-backup-manifest/1.0` records. A shared validator performs direct-child resolution below
the fixed root, `O_NOFOLLOW` reads, regular/single-link checks, bounded manifest parsing, stable
descriptor identity, exact file-name/size/hash binding, and streaming hash verification. The backup
writer uses this typed contract and atomic no-replace hard-link publication from same-directory
`.incomplete` files. The restore dry-run validates the exact pair before any Docker copy or
disposable database creation and uses a per-process restore identity. Historical manifests are
accepted only by an explicit exact-key legacy adapter; their bytes are not changed.

Verification at this milestone:

- typed backup contract, shell-boundary, and infrastructure doctor: 17 tests passed;
- combined scale-out and backup/infrastructure focused suite: 24 tests passed;
- JSON Schema 2020-12 schema check and Pydantic semantic validation: passed;
- strict mypy, Ruff check/format, Bash syntax, and Git whitespace: passed;
- newest 754 MB dump streaming hash and strict legacy adaptation: passed.

No new backup was created. The latest dump was not restored during the active M01 campaign because
the current operator session has no Docker/sudo authority and a 754 MB restore on the same
PostgreSQL host would add avoidable load. Repository history records an earlier production backup
and restore dry-run acceptance, but no exact restore receipt for the newest 2026-09-12 pair was
found. Therefore `LATEST_POSTGRES_RESTORE_DRILL=NOT_VERIFIED_THIS_SESSION`.

## Remaining disaster-recovery boundary

Only PostgreSQL dump storage is visible below the backup root. No repository-owned Artifact-store
backup, independent NAS snapshot/replication policy, or combined PostgreSQL-pointer plus Artifact
restore drill was found. This does not prove the NAS appliance lacks snapshots; its management
plane is outside this session. It means the application cannot yet claim that fact as verified
recovery evidence.

Current honest status:

- `POSTGRES_BACKUP_BYTES=VERIFIED_EXISTING`;
- `POSTGRES_BACKUP_CONTRACT=SOURCE_PASS`;
- `LATEST_POSTGRES_RESTORE_DRILL=NOT_VERIFIED_THIS_SESSION`;
- `ARTIFACT_STORE_RECOVERY=NOT_VERIFIED`;
- `RTO=NOT_MEASURED`;
- `RPO=NOT_DEFINED`.

An end-to-end recovery exercise remains an operator task after M01 is quiescent: establish the NAS
snapshot/replication failure domain, create a fresh typed PostgreSQL backup, restore it in an
isolated database, resolve a bounded set of restored immutable Artifact pointers against the
corresponding snapshot, and measure elapsed recovery time. It must not restore over production or
copy the canonical Artifact store into Git.
