# Item Registry Runbook

Run the registry checks:

```bash
/srv/eom/conda/envs/eom-core/bin/eomctl registry doctor
/srv/eom/conda/envs/eom-core/bin/eomctl item list
```

Inspect one logical Item and its pinned revision:

```bash
eomctl item inspect <ITEM_ID>
eomctl item revision inspect <ITEM_REVISION_ID>
eomctl item components <ITEM_REVISION_ID>
```

Registration normally runs from the item-management workflow step. Never edit Item Revision,
component, metadata, provenance, or manifest rows. A correction is a new workflow and revision.
`ITEM_REVISION_CONFLICT` means the requested base is stale; inspect the current pointer and submit
a deliberate new command. Do not silently retarget it.

Retirement changes the logical Item lifecycle but preserves revisions and usage history:

```bash
eomctl item retire <ITEM_ID> --actor-id admin_01 --reason PLACEHOLDER_REASON
```
