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
modify them. The polkit rule grants `eom-workflow-runner` only fully anchored worker/probe starts,
grants `eom-hwpx-manager` only fully anchored HWPX builder starts, and lets the interactive `eom`
operator start only the harmless worker probe. It explicitly denies cross-manager starts, restarts,
and arbitrary units. If the
installed systemd/polkit mechanism does not expose both `unit` and `verb` for `StartUnit()`, do not
install that rule and do not substitute a broad allow rule. Use the separately reviewed narrow
broker fallback.

## Operator-Managed Worker Configuration

The installed Orchestrator reads worker slots from `/etc/eom/worker-slots.yaml`. The file is a
non-secret operator setting and must be a real `root:eom:0640` regular file. The checked-in
`config/worker-slots.example.yaml` is only a reviewed source/template for installation; runtime
code does not infer it from the repository or Python prefix.

`EOM_WORKER_CONFIG` may override the default only with an absolute reviewed path. Relative paths,
symlinks, malformed YAML, unknown roles or fields, duplicate slot/user identities, and unsupported
schema versions fail closed before job submission. Use the same explicit value for doctor, runner,
and an authorized dedicated live verification.

## Operator-Managed Workflow Configuration

Review and run `scripts/workflow/install_runner_configuration.sh` as root when deploying the
workflow runner. It materializes the reviewed workflow definition, human actor allowlist, runner
timing, and legacy prompt fallback into these non-secret paths:

```text
/etc/eom/workflows/generic-item-development.yaml
/etc/eom/human-actors.yaml
/etc/eom/workflow-runner.yaml
/etc/eom/workflow-prompts/{authoring,image,review,registration}.txt
```

The two created directories are `root:eom:0750`, and files are `root:eom:0640`. The installer does
not alter `/etc/eom` itself, install dependencies, read secrets, or restart services. Runtime
overrides are accepted only as absolute paths. Released Content Pack prompts remain canonical;
the fixed prompt directory supports only the legacy fallback path.

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
EOM_WORKER_CONFIG=/etc/eom/worker-slots.yaml \
  /srv/eom/conda/envs/eom-api/bin/eom-workflow-runner doctor
```

Both commands must pass before creating an acceptance workflow or running `run-once`. Doctor uses
separate unique create/delete probes in the Catalog parent, every fixed Catalog root, and worker
roots, then starts one fixed `/usr/bin/true` authorization probe for each worker slot. It validates
exact root-owned unit/helper hashes, never invokes Codex, never reads worker auth, and creates no
workflow state. The privileged filesystem and negative authorization integrations are separate and
opt-in; their exact commands are kept in the generated acceptance runbook.

## Execution

Production API submissions enqueue typed commands and return without executing workers. The
reviewed long-running service is therefore part of the production execution boundary; without it,
commands remain `PENDING` with zero attempts. Deploy it from a clean, committed tree:

```bash
HEAD="$(git rev-parse HEAD)"
sudo -n scripts/infra/harden_artifact_mount.sh "${HEAD}"
sudo -n scripts/infra/deploy_service_identities.sh "${HEAD}"
sudo -n scripts/workflow/deploy_runner_service.sh install "${HEAD}"
sudo -n scripts/workflow/deploy_runner_service.sh verify "${HEAD}"
systemctl is-active eom-workflow-runner.service
systemctl is-enabled eom-workflow-runner.service
```

The mount hardener edits only the pinned `/mnt/nas` CIFS entry, keeps the protected credential-file
pointer opaque, validates a temporary fstab before atomic replacement, and records a root-only
rollback copy. It stops only the three Artifact-committing managers for the remount and restores the
prior fstab and services on failure. Never replace this with a recursive `chmod` or `chgrp`: the
reviewed CIFS `nounix,forceuid,forcegid` contract ignores per-entry Unix metadata changes.

The service runs as the locked `eom-workflow-runner` identity with the five worker handoff groups
and primary group `eom` for the hardened CIFS Artifact mount. It does not inherit the operator
account's sudo, LXD, desktop, or device groups. The mount presents directories as `0750` and files
as `0640`, with `nosuid,nodev,noexec`; workers never receive the `eom` group and all fixed worker
units additionally make `/mnt/nas` inaccessible. The unit combines `NoNewPrivileges`, an empty
capability set, a strict read-only system image, and inaccessible container-control paths. The service can
write only the bounded staging, worker-workspace, NAS artifact, and private state roots. Git,
EOMIS, other service secrets, container control sockets, and every worker's Codex home are
inaccessible. `RestrictSUIDSGID` is intentionally disabled only on this producer boundary because
the runner must create the reviewed `02770` per-job directories; the fixed worker units retain
`RestrictSUIDSGID=true`.

The deployer refuses to replace a different active unit, so an update cannot silently interrupt an
in-flight worker. It records the source commit and installed unit hash in the separate root-only
`/var/lib/eom-workflow-runner-deployments` directory.

`run-once` remains a diagnostic/operator tool. It returns 2 when no command exists and 3 when work
exists but runtime readiness fails. A status 3 leaves the command unclaimed and the workflow
unchanged. Only a successful preflight is followed by a database claim.

```bash
/srv/eom/conda/envs/eom-api/bin/eom-workflow-runner run-once
```

Do not manually edit commands, leases, attempts, or workflow states. Correct the failed readiness
check and run again.
