# L03 solution-report capacity baseline — 2026-09-15

Status: `BOUNDED_SCALE_OUT_MEASUREMENT_IN_PROGRESS`

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

This section establishes correct bounded admission, not a throughput conclusion. The before/after
event-window comparison remains pending enough post-start completions. At M01 completion, the
accelerator is removed through the exact manager path and the single canonical runner state is
reverified.
