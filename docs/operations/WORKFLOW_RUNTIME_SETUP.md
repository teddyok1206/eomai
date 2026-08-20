# Workflow Runtime Setup

## Runtime Accounts

The runner executes as `eom`. It must have the configured `eom-cdx-01` through `eom-cdx-05`
supplementary groups in both account configuration and the current process. Start a fresh login or
tmux server after group membership changes.

```bash
id -un
id -nG | tr ' ' '\n' | grep '^eom-cdx-'
```

Do not add worker users to `eom`, `sudo`, or `docker`. Do not grant capabilities to Python, Codex,
the runner, or `systemctl`. Do not grant `eom` broad systemd `manage-units` permission.

## Root-Owned worker launcher

An operator installs these reviewed sources as root-owned files; normal job execution uses no
`sudo`:

```text
infra/systemd/eom-worker-01@.service ... eom-worker-05@.service
infra/systemd/eom-worker-probe-01@.service ... eom-worker-probe-05@.service
infra/polkit/50-eom-worker-units.rules
services/orchestrator/eom_orchestrator/worker_exec.py
  -> /usr/local/libexec/eom-worker-exec
```

The unit and helper hashes are part of the installed Python release contract. Unit files and the
helper must be regular root:root files with modes `0644` and `0755`; `eom` must not be able to
modify them. The polkit rule applies only to user `eom`, fully anchored EOM worker/probe instances,
and the `start` verb. It explicitly denies all other `manage-units` requests by `eom`. If the
installed systemd/polkit mechanism does not expose both `unit` and `verb` for `StartUnit()`, do not
install that rule and do not substitute a broad allow rule. Use the separately reviewed narrow
broker fallback.

## Privileged Path Reconciliation

Review `scripts/workflow/bootstrap_runtime_paths.sh` before use. It requires UID 0, calls no
`sudo`, rejects symlinks and non-directories, and reconciles only the Catalog parent, three typed
fixed Catalog staging roots, and five worker workspace roots. Codex does not execute this phase.
The operator runs the reviewed command in an interactive privileged shell as described by the
generated acceptance runbook.

Expected state:

```text
/srv/eom/staging/catalog             eom:eom                 0750
/srv/eom/staging/catalog/content-packs  eom:eom              0750
/srv/eom/staging/catalog/registry    eom:eom                 0750
/srv/eom/staging/catalog/workflow-prompts  eom:eom             0750
/srv/eom/workspaces/eom-cdx-01       eom-cdx-01:eom-cdx-01   2770
/srv/eom/workspaces/eom-cdx-02       eom-cdx-02:eom-cdx-02   2770
/srv/eom/workspaces/eom-cdx-03       eom-cdx-03:eom-cdx-03   2770
/srv/eom/workspaces/eom-cdx-04       eom-cdx-04:eom-cdx-04   2770
/srv/eom/workspaces/eom-cdx-05       eom-cdx-05:eom-cdx-05   2770
```

The script does not recurse through `/srv/eom`, touch worker auth, NAS, or Git, and is idempotent.
`content-packs`, `registry`, and `workflow-prompts` are exact managed paths, not runtime-created
convenience directories. Runtime code creates only operation-keyed children beneath them.

## Unprivileged Verification

After the operator phase, return to a fresh `eom` shell:

```bash
cd /home/eom/EOM
scripts/workflow/verify_runtime_paths.sh
/srv/eom/conda/envs/eom-core/bin/eom-workflow-runner doctor
```

Both commands must pass before creating an acceptance workflow or running `run-once`. Doctor uses
separate unique create/delete probes in the Catalog parent, every fixed Catalog root, and worker
roots, then starts one fixed `/usr/bin/true` authorization probe for each worker slot. It validates
exact root-owned unit/helper hashes, never invokes Codex, never reads worker auth, and creates no
workflow state. The privileged filesystem and negative authorization integrations are separate and
opt-in; their exact commands are kept in the generated acceptance runbook.

## Execution

`run-once` returns 2 when no command exists and 3 when work exists but runtime readiness fails. A
status 3 leaves the command unclaimed and the workflow unchanged. Only a successful preflight is
followed by a database claim.

```bash
/srv/eom/conda/envs/eom-core/bin/eom-workflow-runner run-once
```

Do not manually edit commands, leases, attempts, or workflow states. Correct the failed readiness
check and run again.
