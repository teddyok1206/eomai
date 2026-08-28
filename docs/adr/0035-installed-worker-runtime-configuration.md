# ADR 0035: Installed Worker Runtime Configuration

## Status

Accepted

## Context

The Orchestrator derived its default worker registry from
`Path(__file__).resolve().parents[3] / "config/worker-slots.example.yaml"`. That happened to reach
the repository in a source checkout. In the installed Application API environment it instead
reached `/srv/eom/conda/envs/eom-api/lib/config`, so a dedicated live verification failed before
job submission. The `.example.yaml` file is a development and deployment template, not an
installed wheel resource or an operator-approved runtime value.

The adjacent installed runtime path inventory is:

| Setting | Previous default | Source behavior | Installed behavior | Owner and classification | Resolution |
| --- | --- | --- | --- | --- | --- |
| worker slots | repository-derived `config/worker-slots.example.yaml` | accidentally passed | inferred Python-prefix path | operator-managed external config | `/etc/eom/worker-slots.yaml`, with an absolute `EOM_WORKER_CONFIG` override |
| workflow definition | repository-derived workflow YAML | passed | inferred Python-prefix path | operator-managed external config | `/etc/eom/workflows/generic-item-development.yaml`, with an absolute override |
| static human actors | repository-derived example YAML | passed | inferred Python-prefix path | operator-managed external config | `/etc/eom/human-actors.yaml`, with an absolute override |
| runner timing | repository-derived example YAML | passed | inferred Python-prefix path | operator-managed external config | `/etc/eom/workflow-runner.yaml`, with an absolute override |
| placeholder prompt root | repository-derived content tree | passed | inferred Python-prefix path | operator-managed fallback | `/etc/eom/workflow-prompts`; released Content Pack prompts remain canonical |
| placeholder Content Pack source | hard-coded repository path | passed | same source dependency | development generation input; `SOURCE_CHECKOUT_RUNTIME_DEPENDENCY` | explicit `EOM_PLACEHOLDER_PACK_SOURCE` in the runner/import workflow |
| staging/workspace/NAS roots | fixed `/srv` and `/mnt` paths | explicit | explicit | operator-managed runtime paths; `EXPLICIT_EXTERNAL_CONFIG` | retain validated absolute paths |
| protocol/workflow/Catalog schemas | package resources | passed | passed | immutable release resources; `SAFE_PACKAGE_RESOURCE` | retain `importlib.resources` and wheel drift checks |

Worker slots participate in the dedicated `Orchestrator.submit()` live verification. The workflow
runner settings participate in the installed end-to-end workflow and therefore follow the same
operator-owned external-configuration rule rather than relying on a source checkout.

## Decision

The canonical worker registry at runtime is the reviewed operator-managed file
`/etc/eom/worker-slots.yaml`. It is non-secret, root-owned, group-readable by `eom`, and mode
`0640`. `EOM_WORKER_CONFIG` may select another reviewed file, but the value must be absolute. No
repository, current-working-directory, or Python-install-prefix fallback exists.

The workflow definition, actor allowlist, runner timing, and legacy prompt fallback use the fixed
operator-owned paths listed above. Overrides must be absolute. Configuration files are bounded,
regular, non-symlink files opened without following the final symlink and then validated through
the existing frozen models or JSON Schema compiler. Deployment materializes reviewed repository
inputs at this explicit install boundary as `root:eom:0640`; containing directories are
`root:eom:0750`. Content Pack prompts remain the canonical prompts for release-backed workflows,
and the prompt directory is only the legacy fail-closed fallback.

The loader opens the file without following a final symlink, bounds its size, requires a regular
readable file with a real absolute path, and validates schema version 1 through the frozen Pydantic
model. Slot and Linux-user identities are unique; the slot suffix fixes the Linux identity; roles
come from the V0 allowlist; unknown executable/path fields are rejected; and GPU concurrency cannot
exceed global Codex concurrency.

One resolver supplies the same validated registry to Orchestrator construction, doctor, and the
dedicated live preflight. The preflight selects the deterministic lowest enabled authoring slot,
verifies installed-package origin, staging/workspace access, protocol schemas, fixed template, and
the harmless authorization probe before `submit()` is reachable. It never submits a job or invokes
Codex.

The dominant access is a one-time parse followed by role selection over the bounded installed
inventory (five slots in V1 and six in additive V2). Validation and selection are O(n) time and
O(n) space, with deterministic slot ordering. PostgreSQL, workflow
state, and artifact pointers are outside this configuration transaction; a failure is fail-closed
before any job row, workspace, unit, token use, or retry exists.

## Consequences

Deployments must install or reconcile the external worker file before running doctor or a live
verification. Build verification installs the real wheel into an isolated target, passes a copied
non-production fixture explicitly, and proves `/tmp` CWD independence without a repository import.
The reviewed worker-runtime installer owns this materialization boundary and atomically replaces
the file only after installed-code validation and an empty durable-lease check; its provenance
record pins the resulting inventory SHA-256.

The simpler alternatives were rejected: packaging examples would turn operator settings into
immutable code resources, and keeping `__file__` traversal or supplying repository paths per
command would preserve source/install behavior drift. Installing reviewed inputs explicitly keeps
the wheel independent from mutable configuration while making the production ownership and
materialization boundary auditable.
