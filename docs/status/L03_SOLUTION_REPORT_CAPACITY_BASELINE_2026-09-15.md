# L03 solution-report capacity baseline — 2026-09-15

Status: `EARLY_READ_ONLY_MEASUREMENT`

Observed at: 2026-09-15 14:51:56 UTC

This is an early L03 measurement collected while M01 was running. It does not change the runner,
capacity policy, worker slots, queue, database, or Artifact state. It does not authorize a second
runner process. The transaction used `REPEATABLE READ` and `SET TRANSACTION READ ONLY`; no Item
content, worker output, prompt, secret, or storage path was emitted.

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

## Decision boundary

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
