# M04 operational observability status — 2026-09-15

Status time: 2026-09-15 14:16 UTC

## Outcome

`M04` automated implementation, deployment, and read-only runtime verification are complete. The
Observability console now distinguishes executable work from quiescent historical non-terminal
rows and exposes bounded administrator-only correlation details. It does not authorize repair,
retry, lease release, or state mutation.

The remaining M04 acceptance item is the administrator visual drill-down. It is recorded in
`docs/status/MANUAL_ACCEPTANCE_CHECKLIST_2026-09-15.md` so the user can perform it together with the
other final visual checks.

## Released boundary

- Installed source: `14f2e191e2ebf3a1f5f7030f5789ed58a7537b37`
- Package: `eom-observe==0.1.1`, non-editable wheel installation
- Contract: `observe-operational-overview/1.0`
- Authenticated route: `GET /observe/api/v1/operational-overview`
- Deployment record:
  `/var/lib/eom-observe/deployments/20260915T141505Z_14f2e191e2ebf3a1f5f7030f5789ed58a7537b37.json`
- Service after deployment: active, `NRestarts=0`, `ExecMainStatus=0`

The endpoint and console report the following distinct categories:

- active Workflow commands, Jobs, held worker leases, and API idempotency claims;
- executable Workflows backed by a command, Job, or held lease;
- pending human approvals;
- quiescent non-terminal Workflows with none of those execution edges;
- recent failures separately from historical terminal failures; and
- a maximum of 100 newest-first attention entries containing only bounded correlation pointers.

The topology view remains role-oriented. Slots 05 and 06 are both `support` slots, so snapshot
derivation groups them into one unique `support` role node. When work is active, the node carries
the selected concrete slot and Linux-user identity. This avoids duplicate graph node IDs without
pretending that an idle multi-slot role is using a particular slot.

## Live read-only observation

At 2026-09-15 14:16:05 UTC the installed projection reported:

| Classification | Count |
|---|---:|
| Active Workflow commands | 2 |
| Active Jobs | 1 |
| Held worker leases | 1 |
| Processing API requests | 0 |
| Executable Workflows | 2 |
| Pending human approvals | 45 |
| Quiescent non-terminal Workflows | 24 |
| Recent failed Workflows | 0 |
| Recent failed Jobs | 0 |
| Historical failed Workflows | 304 |
| Historical failed Jobs | 280 |

The two executable Workflows and active support Job belong to the M01 solution-report backfill.
The 24 quiescent rows are observations, not evidence of a current state-machine defect or authority
to edit them. Pending approvals are waiting human work, not executable worker activity.

## Least-privilege and data boundary

The Observability database role retains full `SELECT` only on the nine pre-existing read-model
tables. Three newly observed tables use exact column grants:

- `workflow_commands`: command, Workflow, state, lease expiry, and stable error code;
- `worker_leases`: lease, Workflow, Job, state, and expiry; and
- `api_idempotency_records`: record, state, lease expiry, and stable error code.

Request payloads, idempotency keys, response bodies, lease release reasons, Item content, prompts,
worker results, filesystem paths, secrets, and logs are not part of this contract. Live tests
confirmed that writes and the excluded columns remain denied.

## Verification evidence

- Source Observe suite: 57 passed.
- Focused API and derivation suite during the role-slot correction: 43 passed.
- Strict mypy for the changed source: passed.
- Ruff check and format check: passed.
- JSON Schema 2020-12 and Pydantic projection validation: passed.
- Production-shaped read-only projection benchmark: 0.296 seconds against 11,332 Jobs and 8,836
  Workflow-command rows. This is release evidence at the observed scale, not a future SLO.
- Installed-wheel live integration: 5 passed.
- Installed read-only role: base selects passed; insert, update, delete, create, and excluded-column
  reads were all denied as required.
- Deployment wheel/resource/RECORD and authenticated endpoint verification: passed.

The first post-deployment integration run exposed a real projection defect rather than a service
failure: two enabled slots shared the `support` role and produced duplicate role-node IDs. The fix
uses a role-keyed slot map and a Job-keyed active-slot map, with a regression test for slots 05 and
06. The installed successor passed the same live integration suite. No Workflow, Job, command,
lease, corpus, Item, or Artifact state was changed by this read-only verification.

## Rollback and remaining gate

The deployment record above pins the wheel hash, prior distribution state, unit backup, and prior
service state. Rollback concerns only the Observability component; it does not rewrite operational
history.

Automated M04 status is `PASS`. Final human acceptance remains:

1. open the administrator operational details panel;
2. confirm current executable work, approvals, and historical/quiescent rows are visually distinct;
3. confirm technical IDs remain inside the closed administrator detail rather than the default user
   view; and
4. use one known correlation ID to verify the intended drill-down without exposing content or
   secrets.

