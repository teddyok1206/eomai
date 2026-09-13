# 0080. Require cohort-wide review before production approval

## Status

Accepted

## Responsibility and boundary

The mock-exam production coordinator owns the transition from 25 independently reviewed Workflow
items to operator approval. It must not approve an eligible subset while another item is still
running, blocked, unconfirmed, or failed. Approval is the irreversible boundary that permits Item
registration, so the coordinator observes all 25 reviews before it submits any approval command.

## Canonical source, pointers, and access patterns

The immutable production checkpoint is the canonical cohort snapshot. Each row pins its Workflow,
knowledge provenance, and submitted review Artifact revision. A review that is merely ready is
kept as a bounded in-process observation until the whole cohort is ready because the immutable
execution contract intentionally permits a review pointer only with approval evidence or an
explicit failure. The coordinator uses the existing map from `workflow_call_id` to the 25 planned
calls for `O(1)` lookup and performs two bounded, ordered scans: one observation scan and, only when
every row has an eligible review, one approval scan. Time is `O(n)` and additional space is `O(n)`
for `n = 25`; ordering remains the plan order. No Artifact bytes or worker results are copied.

## Transaction, concurrency, failure, and retry

Each Workflow observation and approval remains an existing independently idempotent API operation.
The first scan validates review pointers without an approval side effect. If any row lacks an
eligible review, the checkpoint successor records only ordinary Workflow observations and the call
stops. When all 25 are ready, the second scan revalidates and submits approvals using the existing
deterministic operation keys. A response loss is recovered by observing the same Workflow and
retrying the same key; no current or latest Artifact is substituted. Checkpoint compare-and-swap
remains the serialization boundary.

This barrier prevents a late item failure from leaving an already registered partial exam that the
official retirement contract cannot cancel. External, manual approvals remain outside this
coordinator boundary and are still detected through the existing approval-evidence checks.

## Dependency direction and alternatives

The application coordinator depends only on typed Workflow operations and production contracts.
It does not access Workflow tables, NAS, or worker internals. Adding a persistent batch-approval
state or distributed transaction is unnecessary: the fixed-size checkpoint already contains the
authoritative readiness pointers, while deterministic per-Workflow approval keys provide retry
safety. Approving rows as soon as each review arrives was simpler but allowed partial registration
before cohort quality was known, which is unsafe for an atomic 25-item production run.
