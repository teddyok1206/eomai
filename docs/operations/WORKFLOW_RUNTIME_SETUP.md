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
the runner, or `systemd-run`.

## Privileged Path Reconciliation

Review `scripts/workflow/bootstrap_runtime_paths.sh` before use. It requires UID 0, calls no
`sudo`, rejects symlinks and non-directories, and reconciles only the two fixed Catalog staging
directories and five worker workspace roots. Codex does not execute this phase. The operator runs
the reviewed command in an interactive privileged shell as described by the generated acceptance
runbook.

Expected state:

```text
/srv/eom/staging/catalog             eom:eom                 0750
/srv/eom/staging/catalog/workflow-prompts  eom:eom             0750
/srv/eom/workspaces/eom-cdx-01       eom-cdx-01:eom-cdx-01   2770
/srv/eom/workspaces/eom-cdx-02       eom-cdx-02:eom-cdx-02   2770
/srv/eom/workspaces/eom-cdx-03       eom-cdx-03:eom-cdx-03   2770
/srv/eom/workspaces/eom-cdx-04       eom-cdx-04:eom-cdx-04   2770
/srv/eom/workspaces/eom-cdx-05       eom-cdx-05:eom-cdx-05   2770
```

The script does not recurse through `/srv/eom`, touch worker auth, NAS, or Git, and is idempotent.
`workflow-prompts` is an exact managed path, not a runtime-created convenience directory. The
runtime creates only `<workflow_id>/<step_key>-<attempt>` beneath it.

## Unprivileged Verification

After the operator phase, return to a fresh `eom` shell:

```bash
cd /home/eom/EOM
scripts/workflow/verify_runtime_paths.sh
/srv/eom/conda/envs/eom-core/bin/eom-workflow-runner doctor
```

Both commands must pass before creating an acceptance workflow or running `run-once`. Doctor uses
separate unique create/delete probes in the Catalog parent, prompt staging root, and worker roots,
but never invokes Codex. The privileged filesystem integration is separate and opt-in; its exact
command is kept in the generated acceptance runbook.

## Execution

`run-once` returns 2 when no command exists and 3 when work exists but runtime readiness fails. A
status 3 leaves the command unclaimed and the workflow unchanged. Only a successful preflight is
followed by a database claim.

```bash
/srv/eom/conda/envs/eom-core/bin/eom-workflow-runner run-once
```

Do not manually edit commands, leases, attempts, or workflow states. Correct the failed readiness
check and run again.
