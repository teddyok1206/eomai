# ADR 0008: Read-Only Observability Console

Status: Accepted

## Context

Operators need a temporary browser view of platform jobs, workflows, workers, approvals, artifacts,
and recent interactions. This view must not become a control plane or constrain the future main GUI.

## Decision

- Implement `eom_observe` as an independent FastAPI process and vanilla JavaScript application.
- Use existing PostgreSQL audit tables as the only source of truth.
- Give the process the dedicated `eom_observe_ro` role with SELECT on nine required tables only.
- Expose no mutation endpoint other than stateless session login and logout.
- Do not import observer packages from protocol, workflow, orchestrator, runner, or `eomctl` code.
- Use metadata-only content summaries and logical artifact URIs; never read NAS or worker files.
- Poll once per interval for all browser clients and fan out through bounded SSE queues.

## Consequences

The service can be stopped or removed without changing EOM execution. Polling is appropriate for the
current single-server scale. PostgreSQL triggers or NOTIFY are deferred until measured demand exists.
