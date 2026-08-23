# Workflow Runtime Troubleshooting

Run `eom-workflow-runner doctor` through the installed service identity when diagnosing production.
Output contains
only sanitized check names, codes, and metadata summaries.

| Code | Meaning | Action |
| --- | --- | --- |
| `CATALOG_ADAPTER_MISSING` | production graph is incomplete | redeploy the complete release |
| `CATALOG_STAGING_INVALID` | owner, group, mode, or access differs | run reviewed runtime path bootstrap |
| `CATALOG_STAGING_UNWRITABLE` | bounded probe failed | inspect parent mount and permissions |
| `CATALOG_CONTENT_PACK_STAGING_INVALID` | `content-packs` is missing, linked, incorrectly owned/mode, or unwritable | reconcile only the reviewed fixed Catalog paths |
| `CATALOG_REGISTRY_STAGING_INVALID` | `registry` is missing, linked, incorrectly owned/mode, or its create/remove probe failed | run the exact runtime path bootstrap; do not retry a failed workflow |
| `CATALOG_PROMPT_STAGING_INVALID` | `workflow-prompts` is missing, linked, incorrectly owned/mode, or unwritable | run the exact runtime path bootstrap; do not recursively normalize Catalog staging |
| `WORKER_ACCOUNT_UNAVAILABLE` | configured Linux identity is absent | repair worker bootstrap |
| `WORKER_CONFIGURATION_INVALID` | explicit worker config is missing, linked, relative, unreadable, malformed, or incompatible | reconcile `/etc/eom/worker-slots.yaml`; do not point runtime at a repository example |
| `ORCHESTRATOR_SOURCE_IMPORT_DETECTED` | dedicated verification imported Orchestrator outside installed package roots | redeploy the non-editable wheel and remove source path injection |
| `WORKER_PRIVATE_GROUP_INVALID` | primary private group is inconsistent | repair the exact worker account |
| `WORKER_GROUP_MEMBERSHIP_MISSING` | `eom` is not configured in the group | repair account membership, then relogin |
| `WORKER_GROUP_MEMBERSHIP_STALE` | account is correct but this process is stale | start a new login/tmux process |
| `WORKER_WORKSPACE_INVALID` | owner/group/mode/setgid boundary differs | run reviewed runtime path bootstrap |
| `WORKER_WORKSPACE_UNWRITABLE` | job-local handoff probe failed | inspect filesystem and mount policy |
| `WORKER_HOME_INVALID` | worker HOME metadata is inconsistent | repair only that worker HOME |
| `CODEX_BINARY_UNAVAILABLE` | configured binary is missing/non-executable | repair the installed Codex runtime |
| `SYSTEMCTL_UNAVAILABLE` | fixed-unit launcher client is unavailable | repair host systemd installation |
| `WORKER_SYSTEMD_TEMPLATE_INVALID` | root-owned helper/template is missing, stale, linked, writable, or hash-mismatched | reinstall the exact final-HEAD worker artifacts and run `daemon-reload` |
| `WORKER_SYSTEMD_AUTHORIZATION_DENIED` | `eom-workflow-runner` could not start and complete a fixed harmless slot probe | verify installed systemd/polkit unit+verb capability and the reviewed start-only rule; never add a broad allow |
| `WORKFLOW_SCHEMAS_INVALID` | installed runtime resources are incomplete | rebuild/redeploy the self-contained wheel |
| `WORKFLOW_DEFINITION_INVALID` | configured definition cannot compile | repair the pinned definition/config |

Readiness failure before claim is operational, not terminal. It does not create a workflow failure
event. A failure after claim remains an authoritative workflow audit record and is not resurrected.
Create a new acceptance workflow after fixing the environment; do not update failed rows or leases.

Never use `chmod 777`, recursive ownership changes, root runner execution, per-job `sudo`, Linux
capabilities, broad `manage-units`, or arbitrary transient-unit permission as a workaround. The
fixed templates are the only normal worker start path. If unit/verb filtering cannot be proven on
the installed server, stop and use a separately reviewed narrow broker design.
