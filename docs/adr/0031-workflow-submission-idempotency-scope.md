# ADR 0031: Workflow Submission Idempotency Scope

## Status

Accepted

## Context And Existing Identity Path

Application API command idempotency and workflow occurrence identity currently collapse into one
permanent key. `POST /api/v1/workflows` first claims
`(operator_id, workflow_start, HMAC-SHA-256(Idempotency-Key))` in
`api_idempotency_records`. The router then discards that command identity and hashes
`(workflow_start, actor_id, validated request body)` into an `api:<digest>` value. The command
adapter passes that value to `create_workflow_instance`, which looks up
`workflow_instances.idempotency_key`. PostgreSQL has a global UNIQUE constraint on that column,
and the lookup does not consider workflow state.

The validated body includes definition key/version, `request_name`, image mode, Content Pack and
environment, source Intake IDs, registry mode, and optional Item revision targets. Actor identity
is in the router's old domain key but not in the stored `request_hash`. The HTTP Idempotency-Key is
used by `api_idempotency_records` but does not participate in the old workflow key. Therefore a new
HTTP key with the same actor and body returns a prior FAILED workflow forever.

There is no separate workflow-submission table. `workflow_instances.idempotency_key` is the
submission idempotency identity, `workflow_instances.request_hash` is the deterministic business
fingerprint, and `workflow_instances.workflow_id` is the occurrence identity. Existing snapshot
triggers make all three immutable. The workflow states actually stored by V0 are REQUESTED,
RUNNING, AWAITING_HUMAN_APPROVAL, REWORK_REQUESTED, APPROVED, REGISTERING, COMPLETED, FAILED, and
CANCELLED. COMPLETED, FAILED, and CANCELLED have no outgoing transitions.

## Decision

Keep the three identities separate:

1. API command idempotency remains the existing operator/operation/raw-key claim. A stable keyed
   digest of that same identity becomes the workflow submission idempotency key; the raw key is
   never stored. Same-key recovery therefore resolves the same occurrence even if the API response
   claim must be recovered.
2. The existing deterministic `request_hash` remains the business fingerprint. It covers the
   pinned workflow definition hash and normalized workflow request, but it is not globally unique.
3. Every accepted occurrence has its own `workflow_id`. FAILED and CANCELLED occurrences remain
   immutable and a new submission key may create a new occurrence with the same business
   fingerprint.

Equivalent REQUESTED, RUNNING, AWAITING_HUMAN_APPROVAL, REWORK_REQUESTED, APPROVED, or REGISTERING
work returns the active occurrence instead of creating a parallel active duplicate. PostgreSQL
enforces this with a partial unique B-tree index on `request_hash` for exactly those states. A
non-unique B-tree index supports fingerprint audit and terminal lookup. Insert uses a savepoint so
a concurrent unique-index loser can resolve the committed active occurrence without aborting the
outer command transaction.

COMPLETED preserves the V0 API behavior: an equivalent successful occurrence created by the same
actor is returned. FAILED and CANCELLED are terminal unsuccessful and permit a new occurrence.
This is submission recovery, not `RETRY_STEP`; no state, attempt, event, command, or artifact is
copied from the prior occurrence.

## Design Checks

- **Responsibility and boundary:** the API adapter owns HTTP-key derivation; workflow repository
  owns occurrence selection and creation; the state machine owns terminal classification.
- **Canonical source:** workflow rows and events in PostgreSQL remain canonical. API idempotency
  rows remain transport state.
- **Logical entity and revision model:** `workflow_id` identifies one immutable execution
  occurrence. Workflows are not revisions of one another; `request_hash` only relates equivalent
  business input.
- **Pointers and resolution:** artifact, prompt, Content Pack, Intake, Item, and final-manifest
  pointers are unchanged. A new occurrence resolves and pins them through the normal request path.
- **Access patterns:** exact submission lookup by unique `idempotency_key`; active-equivalent and
  audit lookup by indexed `request_hash`; newest same-actor COMPLETED lookup by fingerprint.
- **Structures and indexes:** immutable SHA-256 fingerprints plus B-tree indexes. No large payload
  or derived binary is added to PostgreSQL.
- **Scale and complexity:** lookups and uniqueness checks are O(log n); indexes use O(n) space;
  result selection is deterministic by creation timestamp and workflow ID.
- **Transaction and concurrency:** one workflow creation transaction plus a partial unique index;
  two database sessions cannot commit two active equivalent occurrences.
- **Dependency direction:** API router -> command adapter -> workflow repository/state machine.
  Domain code does not import API, filesystem, NAS, or infrastructure configuration.
- **Failure, replay, and idempotency:** same API key/body replays the same resource; same key with a
  different body remains an API conflict; a new key after FAILED/CANCELLED creates a clean
  occurrence; pre-claim readiness is unchanged.
- **Simpler alternatives:** a global unique business fingerprint causes permanent failed-record
  poisoning. A SELECT-before-INSERT check races. A new active-submission table or lease duplicates
  existing workflow lifecycle state and is unnecessary for V0.

Migration `20260818_0007` only adds indexes. It updates or deletes no workflow, event, command,
attempt, or artifact row. Downgrade removes only the new indexes. The API request/response contract
and exported OpenAPI bytes remain unchanged.
