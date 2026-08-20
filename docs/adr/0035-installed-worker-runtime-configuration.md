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
| workflow definition | repository-derived workflow YAML | passed | inferred Python-prefix path | runner deployment config; `SOURCE_CHECKOUT_RUNTIME_DEPENDENCY` | existing production runner supplies `EOM_WORKFLOW_DEFINITION`; its broader deployment move is outside the dedicated live-job path |
| static human actors | repository-derived example YAML | passed | inferred Python-prefix path | legacy runner deployment config; `SOURCE_CHECKOUT_RUNTIME_DEPENDENCY` | existing production runner supplies `EOM_HUMAN_ACTOR_CONFIG` |
| runner timing | repository-derived example YAML | passed | inferred Python-prefix path | runner deployment config; `SOURCE_CHECKOUT_RUNTIME_DEPENDENCY` | existing production runner supplies `EOM_WORKFLOW_RUNNER_CONFIG` |
| placeholder prompt root | repository-derived content tree | passed | inferred Python-prefix path | development fallback; `SOURCE_CHECKOUT_RUNTIME_DEPENDENCY` | existing production runner supplies `EOM_WORKFLOW_PROMPT_ROOT`; Content Pack prompts remain canonical |
| placeholder Content Pack source | hard-coded repository path | passed | same source dependency | development generation input; `SOURCE_CHECKOUT_RUNTIME_DEPENDENCY` | explicit `EOM_PLACEHOLDER_PACK_SOURCE` in the runner/import workflow |
| staging/workspace/NAS roots | fixed `/srv` and `/mnt` paths | explicit | explicit | operator-managed runtime paths; `EXPLICIT_EXTERNAL_CONFIG` | retain validated absolute paths |
| protocol/workflow/Catalog schemas | package resources | passed | passed | immutable release resources; `SAFE_PACKAGE_RESOURCE` | retain `importlib.resources` and wheel drift checks |

Only worker slots participate in the dedicated `Orchestrator.submit()` live verification. The
other source dependencies are already explicitly supplied by the workflow runner acceptance
contract and are recorded here rather than being silently treated as package resources.

## Decision

The canonical worker registry at runtime is the reviewed operator-managed file
`/etc/eom/worker-slots.yaml`. It is non-secret, root-owned, group-readable by `eom`, and mode
`0640`. `EOM_WORKER_CONFIG` may select another reviewed file, but the value must be absolute. No
repository, current-working-directory, or Python-install-prefix fallback exists.

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

The dominant access is a one-time parse followed by role selection over five slots. Validation and
selection are O(n) time and O(n) space, with deterministic slot ordering. PostgreSQL, workflow
state, and artifact pointers are outside this configuration transaction; a failure is fail-closed
before any job row, workspace, unit, token use, or retry exists.

## Consequences

Deployments must install or reconcile the external worker file before running doctor or a live
verification. Build verification installs the real wheel into an isolated target, passes a copied
non-production fixture explicitly, and proves `/tmp` CWD independence without a repository import.

The simpler alternatives were rejected: packaging the example would turn an operator setting into
an immutable code resource, and keeping the `__file__` traversal would preserve source/install
behavior drift. Broadening this change to move every workflow example into `/etc` was also rejected
because those paths do not participate in the dedicated live job and have separate deployment
ownership.
