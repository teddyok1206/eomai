# ADR 0033: Workflow Operator Actor Authorization

## Status

Accepted for Application API V0.

## Context

Application API authentication identifies a human with the immutable canonical
`operator_<32 lowercase hex>` ID and persists that ID on workflow commands. The workflow runner
previously authorized approval, rework, and cancellation only by looking up an unrelated static
actor ID in `human-actors.example.yaml`. An API-created approval was therefore accepted at the
HTTP permission boundary but rejected later as an unknown workflow actor.

The API idempotency record and the workflow command also used different command identities. The
HTTP record was scoped by the raw API key, while a human workflow action derived its durable
command key only from workflow/action/version/actor/payload. A new HTTP key after an immutable
FAILED approval could therefore resolve the old FAILED command instead of creating a new command
occurrence.

## Decision

The workflow-runner application owns a typed `WorkflowActorAuthorizer` port. Production composes:

1. an Operator Identity adapter for validated canonical `operator_*` IDs;
2. the existing static actor configuration adapter for CLI and internal actors; and
3. a composite that routes the namespace deterministically and never falls back from an Operator
   ID to static configuration.

The Operator adapter reads the authoritative Operator and current active role assignments when a
command is processed. It requires `ACTIVE` state, the action-specific built-in permission
(`workflow:approve`, `workflow:request_rework`, `workflow:cancel`, or `workflow:reconcile`), and a
workflow role allowed by the pending gate or required administrative action. The command and
workflow events retain the canonical Operator ID. API request
permission checks remain in place as a first boundary; runner authorization is a fresh,
defense-in-depth check and does not trust role strings or permission snapshots in a command.

Static actor behavior remains compatible. Its configured role is translated to the same typed
action capabilities, so the runner has one authorization decision contract rather than two
separate code paths.

For workflow actions, the API derives the durable command idempotency key from the authenticated
Operator, endpoint action, and raw HTTP Idempotency-Key using the existing keyed digest. The raw
key is never persisted. Same-key replay returns the same command; a new key can create a new
immutable command occurrence after an earlier command failed. Approval row locks and immutable
approval snapshots continue to decide races between distinct commands.

## Design Checks

- **Responsibility and boundary:** API owns HTTP identity; the runner application owns the
  authorization port; Identity SQLAlchemy access stays in an infrastructure adapter.
- **Canonical source:** Operator rows, active role assignments, role-permission rows, and the
  permission catalog are authoritative. YAML remains authoritative only for the static namespace.
- **Identity and provenance:** `workflow_commands.actor_id` and workflow events preserve the
  canonical Operator ID; username and static aliases are never substituted.
- **Access patterns:** Operator lookup is primary-key indexed; active assignments use the existing
  partial lookup index; effective permissions use indexed foreign-key joins. Work is proportional
  to one Operator's active roles and permission set.
- **Structures:** immutable decisions use frozen dataclasses and frozensets; namespace routing is
  an anchored canonical-ID validation, not a list scan or username heuristic.
- **Transaction and concurrency:** authorization reads current identity state immediately before
  the approval transaction. The approval row is then locked and its immutable snapshot/version is
  validated. Concurrent decisions preserve the existing single-resolution invariant.
- **Failure and retry:** unknown, disabled, malformed, or permission-revoked actors are denied.
  Identity backend failure is distinguished internally from a normal denial. Existing FAILED
  commands are never rewritten; a new API key creates a new auditable command occurrence.
- **Dependency direction:** workflow contracts/domain do not import identity persistence. The
  runner application depends on a port; the SQLAlchemy Identity adapter implements it.
- **Simpler alternative rejected:** adding `review01` or an Operator ID to YAML would duplicate
  identity state and retain stale permissions. Rewriting the actor to `reviewer_01` would destroy
  audit attribution. Trusting the API's permission snapshot would allow queued commands to retain
  revoked authority.

No database schema or public HTTP contract changes are required.
