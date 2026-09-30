# ADR 0161: Ungrounded review escalation plan

## Context

`generic-item-development@1.15.0` emits `review-result@12.0` for both Graph-grounded and
general-knowledge requests. The @12 review contract deterministically declares whether a stronger
review pass is required. Graph-grounded requests already pin both the primary and stronger review
candidates in `resolved-execution-plan/17.0`, but general-knowledge requests still resolved to
`resolved-execution-plan/1.0`, which pins only the primary candidate. A successful primary review
therefore could not be classified after commit without consulting mutable preset state.

## Decision

Add immutable `resolved-execution-plan/18.0` for ungrounded Workflow 1.15 executions. It preserves
the V1 pointer model and explicitly requires null Graph/Evidence revisions, while every step carries
`evidence_access=NONE` and only the review step carries one distinct escalation candidate.

The standard execution resolver selects V18 only for the exact Workflow 1.15 / role protocol 1.24
pair. It validates the current released preset once, stores both review candidates in the canonical
plan, and replays the stored plan byte-for-byte. Older Workflow families continue to produce V1.

The runner and materializer accept V18 as an escalation-authorizing plan. They never resolve a
later preset revision. The canonical plan remains the source of truth; the normalized step table is
an indexed execution projection.

## Data structures and boundaries

- Primary access is one indexed plan lookup by Workflow ID, then one bounded step lookup (at most
  64 entries); resolution and validation are O(S) time and O(S) plan space.
- Step identities remain unique in the canonical immutable tuple and the existing database key.
- Plan creation and its step projection remain one database transaction with the existing unique
  Workflow-plan constraint.
- Retries reuse the same plan hash. Missing, stale, mismatched, or unsupported plan families fail
  closed.
- No binary content, worker output, or new queue is introduced.

## Rejected alternative

Consulting the current preset only after review would be smaller, but would make replay and audit
depend on mutable state. Silently skipping stronger-review classification for ungrounded requests
would weaken the released @12 review contract. Both alternatives are rejected.

