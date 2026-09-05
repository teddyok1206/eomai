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

Create and revise new content through the Application API/GUI on the admitted
`generic-item-development/1.7.0` path. A revise command must name both the logical Item and its exact
current base revision. The former manual `1.1.0` placeholder command is historical and intentionally
cannot accept new work. Before operational use, confirm:

```bash
eomctl workflow definition admission
```

The output must report `consistent: true`; new item requests use the active
`generated-knowledge-item/1.12.0` Content Pack and preserve the supplied logical Item and pinned base
revision identities.

After approval, verify that the previous revision is `SUPERSEDED`, its immutable artifact pointers
remain resolvable, and the new revision is `APPROVED` and current. Re-running `workflow reconcile`
must not change the number of revisions.
