# M01 solution-report backfill recovery

Status: `RUNNING`

Evidence time: 2026-09-15 15:05 UTC

This record distinguishes the immutable 520-Item target, historical failed attempts, current
corpus truth, and the operational work that resumed the additive V10 solution-report backfill. It
does not claim that the backfill is complete and does not reinterpret a failed attempt as success.

## Exact target

The authoritative `assessment-learning-corpus-view/2.0` projection and an independent
repeatable-read query agree on the following target:

- 50 source PDFs;
- 520 occurrence-backed approved past-exam Item analyses in Graph revision 68;
- 520 distinct target Item Revisions; and
- at most one accepted `knowledge-analysis-request/10.0` successor per accepted V9 predecessor.

The separately approved trusted-RAG canary Item has no source occurrence in this target Graph. It
is a distinct product lineage and is intentionally not added to the denominator. `520` is therefore
the contract denominator; it is not a missing `521st` solution report.

## Blocker classification

The initial typed projection reported 322 completed, one active, one failed, and 196 pending.
Those two blockers had different causes:

1. The active analysis pinned a Workflow that had already completed, had no active Job or lease,
   and later moved through the supported reconcile boundary to `NEEDS_REVIEW`. Current source
   checked the terminal-failure fence before reconciling active analyses, so an unrelated failure
   could indefinitely strand that state. ADR 0092 and commit `3562c64` move complete bounded active
   reconciliation before the unchanged refill fence.
2. The failed analysis reached `VALIDATING_RESULT` after a successful worker process exit, then
   failed closed with `WORKER_RESULT_INVALID` because one solution step repeated a node identity.
   It committed no result Artifact. The current V10 instruction and validator already require
   sorted, duplicate-free identities, so this was worker-output nonconformance rather than a
   missing protocol or prompt rule.

No database row was edited, no failure was rewritten as success, and no new identity was used to
bypass either condition.

## Recovery execution

Release `87d08a255c9343beabf2bacb05bbe6074e6f3b74` was built, inspected, and installed after a
repeatable-read preflight proved zero active platform Jobs, worker leases, Workflow commands, and
API idempotency claims. Deployment preserved migration head `20260912_0035`, passed runtime
isolation, and recorded rollback metadata at:

```text
/var/lib/eom-api/deployments/87d08a255c9343beabf2bacb05bbe6074e6f3b74.json
```

The installed Catalog service was then inspected from `site-packages`; it reconciles the complete
bounded active set before evaluating the terminal refill fence. All long-running services were
active with zero restart count after deployment.

The existing automatic risk-policy use case accepted the reconciled `NEEDS_REVIEW` result, moving
the corpus to 323 completed without direct state mutation. Only the exact failed analysis identity
was appended to the existing bounded retry allowlist, from 15 entries to 16 of the allowed 32. The
configuration was replaced atomically with owner/group/mode `root:eom:0640`.

The retry used the deterministic idempotency key derived from the failed analysis. Its one
successor completed and was accepted. The original failed row remains immutable history, while the
current corpus failed count became zero.

## Current projection

At the evidence time above, immediately after the bounded second runner began consuming work:

| Field | Value |
| --- | ---: |
| target | 520 |
| completed | 346 |
| active | 2 |
| pending | 172 |
| current failed | 0 |
| status | `RUNNING` |

The bounded scale-out contract in commit `823f7be` was activated through its sole operator path,
`scripts/workflow/manage_runner_scale_out.py`. The manager adopted only the already staged runtime
unit whose bytes exactly matched the installed canonical runner unit at
`sha256:1688c77a606ea647d498aacbb3f8f75265f459cf888e1495ae82a8d2887b2878`.
The canonical and accelerator services were active under `eom-workflow-runner:eom` with distinct
PIDs, zero restarts, and no warning-or-higher accelerator journal entry. PostgreSQL then showed two
distinct `PROCESSING` commands, two support Jobs, and one active knowledge-analysis lease on each
of slots 05 and 06. The exact pinned maxima remained two for knowledge analysis, two for the
support pool, and three globally. This is tracked bounded concurrency, not an ad-hoc worker.

The accelerator must be stopped and its exact runtime unit removed at M01 terminal completion or
before any shared-runtime release. Completion is still determined by the typed corpus projection,
not by runner process state or the count shown at this intermediate snapshot.

## Verification and remaining gate

- focused automatic-learning suite: 33 passed;
- combined automation and past-exam solution-contract suite: 52 passed;
- Ruff format/check: passed;
- strict mypy for the changed service: passed;
- release wheel/RECORD inspection: passed;
- installed-source ordering and service health: passed;
- deterministic failed-attempt successor: accepted;
- bounded scale-out source/identity/fencing suite: 81 passed;
- live two-runner service, command, Job, lease, and capacity verification: passed;
- current corpus uniqueness and final quiescence: pending completion of the remaining 172 Items.

Monitoring must stop new refill on any new unallowlisted terminal leaf. A timeout alone must not
create a new retry identity. Completion requires 520 accepted successors, zero current failed,
zero active/pending target work, and a final target-set/uniqueness/quiescence audit.

## 15:38 UTC validator stop and prepared recovery

At 2026-09-15 15:38:36 UTC, the terminal-failure fence stopped refill on one new exact failed leaf.
The typed corpus at the subsequent read-only audit was 362 completed, 0 active, 157 pending, and 1
failed. Global active Jobs, held/reconciling leases, and active Workflow commands were all zero.

The failed Workflow is `workflow_08d2f382c9744aa2ad78159ca754d1ea`; its analysis is
`analysisrun_86f074e5d7404c18b76b18eca5130b32`. The support worker on slot 05 exited zero, but the V10
result repeated one node identity inside `solution_steps[0].node_ids`. The existing role-result
validator rejected the non-unique array as `WORKER_RESULT_INVALID`; the Workflow and analysis
failed closed, and the Job committed zero Artifact Revisions. This is the same bounded class as the
earlier worker-output nonconformance, not evidence that the current schema or instruction omits the
uniqueness rule.

No deterministic retry exists for this exact failed analysis. The current ordered retry allowlist
contains 16 unique entries and excludes it. A single successor file has been staged at
`/tmp/eom-m01-legacy-item-automation-86f0.env`, adding only that exact identity; its SHA-256 is
`eb1df08ba08052afbdf24c7a775b26913b62b3689f5e87f020ada692591a5bec` and its count is 17 of the
maximum 32. The staging script passed Ruff, format, strict mypy, exact source-byte, metadata,
uniqueness, no-replay, and quiescence gates.

The installed environment was not changed because non-interactive operator sudo was unavailable.
Recovery remains the existing supported sequence: atomically install only the exact staged file,
restart only `eom-catalog-application-runner.service`, require exactly one deterministic retry, and
verify that it is accepted before refill resumes. Direct row updates, a new retry key, failed-history
reinterpretation, or a second retry are forbidden.

## 16:21 UTC deterministic recovery and resume

The operator subsequently ran the reviewed exact installer. The installed environment is
`root:eom`, mode `0640`, link count one, and has SHA-256
`eb1df08ba08052afbdf24c7a775b26913b62b3689f5e87f020ada692591a5bec`. The installer left no incoming
or rollback file and restarted only `eom-catalog-application-runner.service`; the service returned
active/running with restart count zero.

The read-only postcondition found exactly one deterministic retry row with idempotency key derived
from the failed analysis. It created analysis `analysisrun_0f8227785d3e4200942d81617d946442`,
pinning the original accepted predecessor `analysisrun_a21030e75e8b4eea89b33179fcd52ba0`, and entered
`RUNNING`. No second retry row or duplicate accepted successor exists.

At 2026-09-15 16:21:10 UTC, the typed projection was 362 completed, 2 active, 156 pending, 0 current
failed, and 0 duplicate accepted successors. Two Jobs, two leases, and two Workflow commands were
active, matching the bounded two-support-slot policy. This is a recovery milestone, not final M01
acceptance. Subsequent monitoring remains at the requested 30-minute cadence and must stop on a new
unallowlisted terminal failure.
