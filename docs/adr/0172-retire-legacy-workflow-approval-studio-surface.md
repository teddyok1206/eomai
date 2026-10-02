# ADR 0172: Retire the legacy Workflow approval surface from Scientific Studio

- Status: Accepted
- Date: 2026-10-02

## Context

Released Workflow definitions before `generic-item-development@1.16.0` paused before
registration and required a human Workflow approval. The current product registers an immutable
Item Revision first, builds HWPX from that exact revision, and records human approval against the
registered revision. Keeping both approval surfaces in Scientific Studio made the older route look
like a supported path for new work.

At retirement time the operational lookup was keyed by Workflow state and indexed approval
relationship. It found exactly 50 `AWAITING_HUMAN_APPROVAL` Workflows, each with one PENDING
approval and one `human_approval / WAITING_FOR_HUMAN` step. They were approved through the
existing idempotent Workflow command boundary. No Item, Artifact, past-exam analysis, or database
row was rewritten directly.

## Decision

Scientific Studio no longer exposes the legacy approval tab, Web BFF mutation, gateway method, or
legacy workbench action. `studio-workbench-overview/1.0` remains byte-identical, while the Web
endpoint moves to successor `studio-workbench-overview/2.0` without the legacy action variants. A
legacy Workflow that somehow remains non-terminal is excluded from the user workbench rather than
being presented with an action that no longer exists.

The core Workflow approval command, state machine, Application API, CLI, events, and immutable
approval records remain available for historical replay and operator recovery. This is presentation
retirement, not deletion or reinterpretation of released protocol history.

The current post-registration Item/HWPX approval path is unchanged.

## Access patterns and complexity

The one-time drain uses the indexed Workflow state and active-approval keys, then enqueues one
idempotent command per Workflow: `O(n)` time and `O(n)` bounded command records for `n=50`.
Normal workbench projection remains a bounded page and performs one pass with keyed typed objects.
No new schema, index, queue, or persistent aggregate is introduced.

## Failure and rollback

Approval commands retain their existing compare-and-swap, authorization, lease, retry, and event
history. A failed command is preserved and is never converted by direct database mutation.
Rollback of the Web release may restore the historical UI code, but it does not reverse approved
Workflow history. The core operator CLI remains the recovery surface if an immutable historical
Workflow needs inspection.

## Rejected alternative

Leaving a hidden or disabled legacy page was rejected because it keeps an obsolete mutation route
and duplicates the current approval concept. Deleting the core approval protocol was rejected
because released Workflow history must remain reproducible.
