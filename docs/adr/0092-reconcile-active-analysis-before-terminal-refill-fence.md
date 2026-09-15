# ADR 0092: Reconcile active analyses before the terminal refill fence

## Status

Accepted

## Responsibility and system boundary

The Catalog automatic-learning application service has two distinct responsibilities in one
bounded advance cycle:

1. reconcile analyses whose Workflow was already started; and
2. decide whether it is safe to create or publish more work.

An unallowlisted terminal analysis must fence the second responsibility. It must not prevent the
first responsibility from recording an already completed Workflow outcome. Workflow execution,
result validation, Artifact commit, and analysis acceptance remain owned by their existing
application services. Workers neither coordinate with each other nor write to PostgreSQL or NAS.

No wire protocol, JSON Schema, persistent model, or released worker contract changes in this
decision.

## Canonical state and pointers

`knowledge_analysis_runs.workflow_id` pins the exact Workflow instance for an active analysis. The
Workflow state, step result pointers, Artifact Revision identities, and hashes remain canonical at
their existing boundaries. Reconciliation resolves those exact pinned identities; it never chooses
a latest Workflow or Artifact.

The terminal fence is derived from terminal leaf analysis rows that do not have an accepted
successor and are not in the explicit retry allowlist. It remains a fail-closed scheduling signal,
not a replacement for the state of another analysis.

## Access patterns and data structures

The dominant access patterns are:

- bounded ordered lookup of at most two active analysis rows;
- idempotent key lookup of each pinned Workflow during reconciliation; and
- indexed lookup of the first unallowlisted terminal leaf.

The existing ordered tuple of at most two active rows, B-tree indexes, predecessor relation,
idempotency keys, and accepted-successor unique constraint match these operations. Reconciliation
is `O(A)` time and `O(A)` bounded space for `A <= 2`; terminal selection remains an indexed bounded
query. No queue, cache, new index, repeated corpus scan, binary database value, or parallel
framework is introduced.

## Decision

Within the existing preset-pin shared lock, one advance cycle performs these operations in order:

1. snapshot and reconcile every currently active analysis, in stable order;
2. evaluate the terminal-leaf fence once after all bounded reconciliation is complete;
3. if a terminal leaf exists, stop before retry selection, new solution creation, Graph
   publication, promotion, or any other refill side effect;
4. otherwise continue the existing capacity and scheduling decisions unchanged.

The service no longer tests the terminal fence before active reconciliation or between two active
rows. This allows a completed Workflow to become an accepted analysis even when a different row has
failed. It does not schedule additional work past a failure.

## Transaction, concurrency, retry, and failure

Each reconcile use case retains its own transaction, optimistic state checks, pointer validation,
and idempotent outcome. The outer preset-pin guard continues to protect mutable preset/capacity
decisions. A failure while reconciling stops the cycle immediately. If reconciliation itself makes
an analysis terminal, the post-reconciliation fence observes it before any refill.

An explicitly allowlisted terminal attempt is still omitted from the fence and receives at most one
deterministic successor. An unallowlisted terminal attempt still emits
`LEGACY_ITEM_AUTOMATION_TERMINAL_ANALYSIS`. Re-running the cycle is safe: reconciliation is
idempotent, accepted successors remain unique, and no new idempotency key is invented.

## Simpler alternative and why it is insufficient

Manually reconciling one stale row repairs one incident but leaves the scheduler capable of
recreating the same stale state whenever an unrelated failure appears first. Removing the terminal
fence would keep throughput moving but could amplify a systematic failure. Moving only the first
terminal check while retaining a per-row check could still strand the second of two active rows.
Reconciling the complete bounded active set and then applying the existing fence is the smallest
durable correction.

## Verification

Focused tests must prove that:

- all bounded active rows are reconciled before an existing terminal leaf is raised;
- no retry, new solution, Graph publication, or promotion follows that terminal leaf;
- normal two-row reconciliation, capacity refill, allowlisted single retry, and idle behavior remain
  unchanged; and
- source formatting, lint, typing, and the focused automatic-learning suite pass before release.

