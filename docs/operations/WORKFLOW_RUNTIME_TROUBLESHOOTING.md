# Workflow Runtime Troubleshooting

Run `eom-workflow-runner doctor` as the same `eom` process that will run commands. Output contains
only sanitized check names, codes, and metadata summaries.

| Code | Meaning | Action |
| --- | --- | --- |
| `CATALOG_ADAPTER_MISSING` | production graph is incomplete | redeploy the complete release |
| `CATALOG_STAGING_INVALID` | owner, group, mode, or access differs | run reviewed runtime path bootstrap |
| `CATALOG_STAGING_UNWRITABLE` | bounded probe failed | inspect parent mount and permissions |
| `WORKER_ACCOUNT_UNAVAILABLE` | configured Linux identity is absent | repair worker bootstrap |
| `WORKER_PRIVATE_GROUP_INVALID` | primary private group is inconsistent | repair the exact worker account |
| `WORKER_GROUP_MEMBERSHIP_MISSING` | `eom` is not configured in the group | repair account membership, then relogin |
| `WORKER_GROUP_MEMBERSHIP_STALE` | account is correct but this process is stale | start a new login/tmux process |
| `WORKER_WORKSPACE_INVALID` | owner/group/mode/setgid boundary differs | run reviewed runtime path bootstrap |
| `WORKER_WORKSPACE_UNWRITABLE` | job-local handoff probe failed | inspect filesystem and mount policy |
| `WORKER_HOME_INVALID` | worker HOME metadata is inconsistent | repair only that worker HOME |
| `CODEX_BINARY_UNAVAILABLE` | configured binary is missing/non-executable | repair the installed Codex runtime |
| `SYSTEMD_RUN_UNAVAILABLE` | launcher is unavailable | repair host systemd installation |
| `WORKFLOW_SCHEMAS_INVALID` | installed runtime resources are incomplete | rebuild/redeploy the self-contained wheel |
| `WORKFLOW_DEFINITION_INVALID` | configured definition cannot compile | repair the pinned definition/config |

Readiness failure before claim is operational, not terminal. It does not create a workflow failure
event. A failure after claim remains an authoritative workflow audit record and is not resurrected.
Create a new acceptance workflow after fixing the environment; do not update failed rows or leases.

Never use `chmod 777`, recursive ownership changes, root runner execution, per-job `sudo`, or Linux
capabilities as a workaround.
