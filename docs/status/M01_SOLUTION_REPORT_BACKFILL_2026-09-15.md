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
