# ADR 0170: Scientific Studio task workbench and navigation

- Status: Accepted
- Date: 2026-10-02

## Context

Scientific Studio exposes the supported application use cases, but its landing page is service-health
oriented and several flows still begin with a technical identifier.  The latest single-item lifecycle
also differs from the preserved legacy workflow approval lifecycle:

```text
latest: authoring -> review -> registration -> HWPX -> Item Revision approval
legacy: authoring -> review -> workflow approval -> registration
```

The browser must not infer these lifecycle rules, join unbounded API collections, or silently resolve
an immutable revision to a newer one.  Navigation must also survive refresh/back/forward without
putting credentials or content in the URL.

## Decision

The Web BFF owns a new read-only `studio-workbench-overview/1.0` presentation contract.  It composes
two bounded, permission-checked Application API queries (recent workflows and active Items) and
returns only typed immutable pointers and the next supported action.  It does not persist a derived
dashboard aggregate.

The dominant access patterns are bounded newest-first iteration and immutable Item Revision lookup.
Workbench composition is O(W + I) time and O(W + I) output space for at most 50 records from each
upstream collection.  A `source_truncated` bit prevents a bounded projection from being mistaken for
a complete corpus inventory.

Every work item declares one approval mode:

- `POST_REGISTRATION_HWPX` for the current Item Revision approval path;
- Legacy Workflow approval was initially exposed only for preserved historical work. ADR 0172
  retires that Studio surface after draining the bounded backlog while retaining core history.
- `NONE` otherwise.

When a user opens a pending current Item, the BFF performs one exact indexed lookup for the newest
validated HWPX build of that pinned Item Revision.  It opens that build when present and otherwise
offers a new build for the same revision.  This avoids both a browser-side list scan and an N+1 query
while constructing the workbench.

The Studio URL stores only an allow-listed view and validated logical/revision/build identifiers.
History navigation restores the same pinned resource.  Customer-support submissions capture this
sanitized origin route.  Permission-aware controls use the exact effective permission keys returned
by the session; the backend remains authoritative.

The large browser entry point is split with native ES modules.  Routing/history, effective permission
checks, and workbench rendering are independent modules with no persistence or business rules.

## Boundaries and invariants

- Canonical state remains in Workflow, Item Registry, and HWPX application resources.
- Logical Item ID, Item Revision ID, Workflow ID, and HWPX build ID remain distinct.
- The workbench never substitutes a current/latest revision for a pinned revision.
- The BFF validates upstream response shape before constructing its own Pydantic model.
- Browser history contains no token, prompt, result content, filesystem path, or secret.
- Routing has one history writer; resource-selection helpers do not mutate the URL independently.
- Selection sequence tokens prevent late Workflow or HWPX reads from overwriting a newer view.
- Mutations still use the existing CSRF, idempotency, expected-version, and permission boundaries.
- A read-only user may open an existing validated HWPX but cannot be routed into creating a missing
  build; creation and approval remain separate exact permissions.
- No database schema, migration, queue, worker protocol, or NAS write is introduced.

## Failure and retry

An unavailable or malformed upstream projection fails with a stable BFF error.  The browser may retry
the read.  It does not create substitute rows or replay a mutation.  Existing deep links with an
invalid identifier fail closed to the dashboard without dereferencing the value.

## Simpler alternative considered

Joining raw lists in the browser would require duplicating lifecycle and approval rules in an
untrusted presentation layer and would make bounded/incomplete results ambiguous.  Requiring users to
paste IDs avoids that join but does not satisfy the task-oriented product workflow.  A persisted
dashboard table would add invalidation and migration work without being canonical, so the bounded BFF
projection is the simpler sufficient design.
