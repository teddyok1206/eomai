# ADR 0096: Orchestrated customer support

## Status

Accepted for implementation on 2026-09-17.

## Responsibility and boundary

Scientific Studio exposes an authenticated customer-support surface. The Application API owns the
create/list/read use cases and authorization. The Workflow service owns ticket execution state,
the Orchestrator owns the one-shot Codex execution and validated Artifact commit, and the Web BFF
only adapts the typed API for the browser. The support worker diagnoses and explains; it cannot
approve, retry, deploy, edit data, call another worker, write PostgreSQL, or write NAS.

The support worker is not a resident process. Slot 06 remains ready and an isolated systemd worker
is started only for a claimed support job. This preserves the existing bounded execution model
while giving customer support an always-available capacity route.

## Canonical source and revision model

The existing Workflow instance is the canonical support-case record. A new parallel ticket table
would duplicate lifecycle and idempotency state, so it is intentionally not introduced.
The explicit Workflow stage is `CUSTOMER_SUPPORT`; support work is not projected as knowledge
analysis merely because both use the support worker role.

```text
customer-support Workflow
  -> immutable initial CustomerSupportRequest
  -> append-only Workflow/Job events
  -> immutable result Artifact Revision
  -> SHA-256 content hash
```

The browser presents a friendly subject and state. Workflow, Job, Artifact, revision, and hash
identities remain available in an administrator detail view but are not the primary user label.
The worker result is a bounded JSON value committed once as the canonical Artifact; PostgreSQL
stores the existing small validated result projection and pointers, never a binary attachment or
log bundle.

## Protocol

`customer-support@1.0.0` uses `workflow-role/1.22.0` with exactly one `support` step and
`customer-support-result@1.0`. The input keeps user-authored text separate from server-authored
diagnostics. Both role messages are defined first as JSON Schema 2020-12 and then mirrored by
Pydantic models. User text and diagnostic strings are untrusted data and never instructions to
change the execution policy.

The two owner-facing Application API permissions are additive built-in RBAC values. They are
seeded by a successor migration for every authenticated built-in role; readiness compares the
persisted permission inventory with the typed `PermissionKey` contract and fails closed when they
drift. This keeps authorization data aligned with the public route contract without mutating the
already-applied Workflow-stage migration.

The first version accepts no file attachment and no arbitrary filesystem, Artifact, database, or
URL pointer. It may carry a bounded Studio route, a `webreq_` inquiry identifier, and a stable error
code. Rich authorized resource pointers can be added by a successor contract after each resource
family has an explicit permission resolver.

## Access patterns and data structures

- Create/replay: unique indexed Workflow idempotency key, O(log n) database lookup.
- “My inquiries”: indexed `(definition_key, created_actor_id, created_at)` Workflow query with
  cursor pagination. If the existing index is insufficient, add a measured partial/B-tree index;
  do not maintain a copied ticket list.
- Case read: Workflow primary-key lookup followed by at most one terminal Job/Artifact Revision
  lookup. Result projection is bounded.
- Execution: one indexed command claim and one atomic capacity lease for the plan step.
- History: existing append-only monotonic Workflow and Job event sequences.

Expected scale is small relative to item production: hundreds to low tens of thousands of cases.
No full scan, list-based deduplication, or N+1 result lookup is required.

## Capacity and concurrency

A released `customer-support` execution preset pins the model, instructions, timeout, read-only
sandbox, disabled network, and the existing isolated slot-06 pool. The resolved execution plan is
persisted in the same transaction as Workflow creation and pins its exact preset/capacity and
definition identities. The normal capacity controller performs the lease claim. Per-slot capacity
is one; global Codex capacity remains unchanged. A support ticket therefore cannot race a legacy
slot-06 workload or start a second process on the same slot.

Slot 06 has two root-owned fixed systemd templates with distinct reviewed execution ceilings. The
legacy analysis template remains fixed at 7,200 seconds. Customer support uses the dedicated
`eom-worker-support-06@.service` template fixed at 900 seconds. Selection is an O(1) lookup keyed by
the validated `(slot identity, worker role, timeout)` tuple; an unknown tuple fails closed. Both
templates use the same Linux account, workspace identity, and atomic slot-06 capacity lease, so
the additional template does not add capacity or permit concurrent processes. Recovery inspects
both exact instance names and rejects an ambiguous dual observation instead of guessing.

Customer-support work has no right to preempt an already-held lease. “Always available” means the
slot and preset stay READY, not that a long-lived model process or an unbounded priority bypass is
kept running.

V3 remains an immutable historical revision. Re-running a V3 bootstrap after V4 publication may
verify and reuse V3, but it must preserve the newer current pointer. The automatic legacy-learning
guard understands an exactly pinned, hash-valid V3 or V4 current revision; accepting V4 does not
rewrite the older capacity revision pinned by an existing execution plan.

## Transaction, failure, retry, and idempotency

Workflow creation, resolved-plan persistence, and START command creation share one database
transaction. The authenticated operator and endpoint-scoped idempotency key bind the exact
user-authored business values. Server-authored observation time, inquiry correlation, and installed
release diagnostics are excluded from the API idempotency hash so that the same user request can
replay after a timeout; the immutable first snapshot remains on the Workflow. Reusing a key with
different category, subject, question, locale, route, or stable error code fails closed. Timeouts do
not imply that the operation was not accepted; the client reads the prior receipt before replaying
the same key.

Worker failure is recorded as the existing terminal Job/Workflow failure and never rewritten as a
successful answer. Automatic mutation or automatic retry after an uncertain worker outcome is not
allowed. A future retry use case must reuse the supported command/state-machine boundary and
preserve the failed attempt.

## Dependency direction

```text
Web GUI/BFF -> Application API support use case -> Workflow application boundary
Workflow runner -> Orchestrator interface -> systemd/Codex/NAS adapters
domain/contracts <- all higher layers
```

The Web BFF does not query Workflow tables, the worker does not call APIs or NAS, and the
Orchestrator does not own browser presentation rules.

## Diagnostics and privacy

Only a bounded diagnostic snapshot is sent: route, inquiry ID, stable error code, UTC observation
time, and installed API/Web release commits when available. Secrets, cookies, bearer tokens, full
logs, prompts, item content, database rows, and arbitrary paths are forbidden. Output is plain text
rendered without HTML interpretation. The worker must explicitly state uncertainty and escalate
when the snapshot cannot support a safe answer.

## Simpler alternatives rejected

- A permanent interactive Codex process wastes capacity and creates unaudited mutable session
  state.
- Direct Web-to-Codex calls bypass RBAC, Workflow history, leases, validation, and Artifact commit.
- Reusing knowledge-analysis request/result schemas conflates unrelated domain meaning and would
  make future evolution unsafe.
- A new ticket table duplicates Workflow state and creates reconciliation problems without serving
  a present requirement.
- Routing directly to slot 06 without a resolved plan bypasses the capacity lease and can start two
  processes for one Linux worker account.
- Lowering the existing slot-06 template from 7,200 to 900 seconds would silently change the
  immutable execution contract used by long-running analysis work.
- Allowing arbitrary plan timeouts through the generic slot-06 template would weaken the
  root-owned execution ceiling and make the installed systemd contract unverifiable.

## Availability limit

In-product support depends on the Web and Application API. It is not the emergency channel for a
total login, Web, API, or host outage. The existing external operator channel remains necessary for
those failures.
