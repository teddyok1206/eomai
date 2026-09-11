# ADR 0059: Explicit administrative force-revoke for a held production command

## Status

Proposed for the development-only recovery path.

## Context

Production retirement normally waits for an expired Workflow-command lease. During
development, an operator may deliberately stop the runner while an exact, already
owned mock-exam cohort still has a command marked `LEASED` or `PROCESSING`. Direct
database edits are not acceptable: they bypass the transition table, can race a
late worker, and leave no audit trail.

## Decision

Add a separate, explicitly administrative `force-retire-items` operation. It is
not used by normal retirement and never changes the immutable checkpoint. Before
the transaction it requires the exact owned checkpoint, the runner deployment
hold, an ADMIN-equivalent `workflow:reconcile` permission, and the same immutable
workflow/command pointers used by ordinary retirement. In the transaction it
locks the exact cohort, requires no active/reconciling worker lease, fences only
the cohort's cancellable platform jobs, records a force-revoke audit event, and
transitions only the exact held commands through the existing state table to
`CANCELLED`. The terminal state removes the command from the claimable set; its
owner and expiry fields remain as immutable forensic evidence because the API role
is intentionally not allowed to erase lease provenance. Commands outside the pinned
cohort are never touched. A command that has crossed
`VALIDATING_RESULT`/`COMMITTING`, or a workflow/job CAS mismatch, fails closed.

The operation is intentionally opt-in and should remain disabled in normal
production runbooks. The ordinary lease remains the recovery mechanism for
unattended failures; this path exists only for an authenticated administrator
who has explicitly accepted the exact-cohort cancellation.

## Invariants and trade-offs

- Canonical state remains PostgreSQL Workflow command/event history; no direct SQL
  mutation is exposed to the CLI.
- Access is exact-keyed by execution/checkpoint and actor; no broad sweep exists.
- The dominant access pattern is indexed lookup by the 25 workflow IDs and command
  IDs, so the operation is O(n) in the pinned cohort with row locks and no scan of
  unrelated commands.
- The simpler alternative (editing `lease_expires_at` or deleting a row) is
  rejected because it cannot prove ownership, cannot fence late writers, and is
  not replay/audit safe.
