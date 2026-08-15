# ADR 0006: Human Approval Source Of Truth

Status: Accepted

## Context

Human decisions can race, be retried, or arrive against a stale review attempt. Direct row updates
from a CLI or chat integration would bypass authorization, transition validation, and audit history.

## Decision

- PostgreSQL `approval_requests` and `workflow_commands` are the durable source of truth.
- V0 accepts approval, rework, and cancellation only through `eomctl` adapters that enqueue a
  normalized command. The workflow engine performs every state change.
- Approval commands snapshot the approval request ID and lock version. Row locking, the partial
  unique pending-approval index, and explicit transition tables ensure only one racing decision can
  succeed.
- Reviewer and admin roles may approve or request rework; only admin may cancel or force future
  retry operations. Actor ID and role come from validated local configuration and are recorded in
  events.
- Rework never edits an old step or artifact. It supersedes the old run, links the replacement,
  increments the attempt and rework cycle, and creates new platform jobs and artifact revisions.
- Slack is not an approval adapter and cannot read or change workflow state.

## Consequences

Operators must run the workflow runner after enqueuing commands unless the service is already
serving. Stale, duplicate, unauthorized, and conflicting decisions have stable failure codes and
leave the active approval intact when no decision succeeded.
