# ADR 0034: Catalog Fixed Staging Inventory

## Status

Accepted

## Context

Catalog runtime code used fixed `workflow-prompts`, `content-packs`, and `registry` namespaces below
one staging parent, but only `workflow-prompts` was provisioned and checked. A prior privileged
Catalog run could therefore create another fixed namespace as `root`, making later unprivileged
workflow registration deterministically fail after its worker had succeeded.

## Decision

The Catalog settings package owns one immutable typed inventory containing the three fixed roots.
The root-only exact-path bootstrap and unprivileged verifier mirror that inventory, with a static
parity test preventing drift. Workflow doctor and preclaim probe every fixed root before claiming a
command. Each root must be a real, non-symlink `eom:eom:0750` directory and pass a bounded
create/read/remove probe.

Runtime services create only operation-specific children beneath a validated fixed root. Registry
children use the canonical registration key, require parent containment, and create the manifest
exclusively. A pre-existing child or manifest is an explicit staging error rather than an overwrite.
Intake and artifact job IDs remain dynamic children directly beneath the Catalog parent and are not
fixed namespaces.

The dominant access is constant-size keyed lookup in the three-entry tuple and one bounded probe per
entry. Time and space are both constant at V0 scale. Readiness happens before the database command
claim; final use is revalidated to cover filesystem changes between check and registration.

## Consequences

Missing or drifted Registry staging makes doctor and preclaim NOT_READY, so the command remains
unclaimed and its attempt count is unchanged. Runtime code never repairs ownership or permissions,
the API and workers receive no new filesystem access, and only the orchestrator continues to commit
validated artifacts to NAS.

The simpler alternative—allowing `mkdir(parents=True)` to create fixed roots—was rejected because
ownership would depend on whichever identity executed first and readiness could not prove the
deployment contract before consuming a workflow occurrence.
