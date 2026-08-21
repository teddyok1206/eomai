# Application API V0 Release Status

## Completion

```text
APPLICATION_API_V0_COMPLETE=YES
PLATFORM_BASELINE_STABLE=YES
READY_FOR_APPLICATION_LAYER=YES
```

- Release: `EOM Application API V0`
- Local release tag: `v0.6.0-application-api`
- Accepted deployed source: `c90615c83d76de3840a23a2a13de2dbeae50e6fc`
- OpenAPI SHA-256: `9032a4bf3b127fcea6a46ab7137d7212ba2eac8df6cd5ee894f2c2289072878f`
- Alembic head: `20260818_0007`

The Application API V0 functional, live, and privileged acceptance scope is closed. P2 and P3
follow-up work does not reopen this acceptance cycle.

## Acceptance Checkpoints

### Functional and live acceptance

- Checkpoint: `/home/eom/.eom/checkpoints/application-api-v0-live-v2-b325f250`
- Checkpoint JSON SHA-256:
  `e36e95c44aecf2257bcbef30155cec6f9957358a7b99b7f35593308c4ba42435`
- Local checkpoint tag: `checkpoint/application-api-v0-live-v2-pass-b325f250`
- Tag target: `b325f250ebc731b21e5791fbcb254d093cbf11d2`

### Privileged acceptance

- Checkpoint: `/home/eom/.eom/checkpoints/application-api-v0-privileged-pass-c90615c`
- Checkpoint JSON SHA-256:
  `9331b7936cbe81a63882277d7dc32a5391ca83f817b371212d0510df676edbc0`
- Local checkpoint tag: `checkpoint/application-api-v0-privileged-pass-c90615c`
- Tag target: `c90615c83d76de3840a23a2a13de2dbeae50e6fc`
- Privileged report: `/tmp/EOM_APPLICATION_API_V0_PRIVILEGED_GATES_c90615c.report`
- Privileged report SHA-256:
  `71ef52e963aa4ed18dd333b1f364470b23ffa0bd6e46657156b1f47f51f925a5`
- Result: `APPLICATION_API_V0_PRIVILEGED_GATES=PASS`
- Runtime-isolation pidfd backend: `LIBC_PIDFD`

## Canonical Domain Evidence

- Workflow: `workflow_dd417b016178419a96e148a6ad74f9d6`
- Workflow state: `COMPLETED`
- Item: `item_3702e13cd2fc434fae646ddba6f74eef`
- Item Revision: `itemrev_07d8eefd125f44848adf8e53851b7376`
- Revision state: `APPROVED`
- Content Pack provenance: `PASS`
- Prompt provenance: `PASS`
- Approval actor attribution: `PASS`
- Registry manifest: `PASS`
- Final pointer manifest: `PASS`
- Reconciliation: `PASS`
- Duplicate active artifact revisions: `ABSENT`

The workflow, Item, and pinned Item Revision above are the canonical Application API V0 acceptance
records. They remain immutable and are not rerun or reconciled during release finalization.

## Live Verification Accounting

### V1

- Test process attempts: `1`
- Result: `FAIL`
- Failure boundary: before platform job submission
- Platform job submissions: `0`
- Codex process/model invocations: `0`

### V2

- Test process attempts: `1`
- Result: `PASS`
- Rerun: `NOT_RERUN`
- Platform job: `job_59e82b230b0f4abf8f2f341d80b53743`
- Final job state: `SUCCEEDED`
- Actual Codex process/model invocations: `1`

## Verifier and Deployment History

The historical attempts remain separate audit records:

- `70fff050`: pidfd capability crash; no service-context access probes and no isolation verdict.
- `b141bdc`: restrictive-umask package-mode deployment failure; recovered with no verifier
  invocation.
- `76eb4bf`: runtime verifier semantic defect in the API environment-file expectation; no PASS
  verdict.
- `c90615c`: corrected service-context verifier executed once and returned `PASS`.

The accepted API environment boundary is systemd-manager read with direct access denied to the
running `eom-api` service identity.

## Final Gate Results

- Functional acceptance: `PASS`
- Live verification: `PASS`
- Deployment/runtime isolation: `PASS`
- Service-context allowed probes: `PASS`
- Service-context denied probes: `PASS`
- Worker permission boundary: `PASS`
- HWPX ownership boundary: `PASS`
- Observability privileged integration: `PASS`
- Journal secret scan: `PASS`
- Auth/RBAC regression: `PASS`
- Deliverable/Usage regression: `PASS`
- Repository ownership: `PASS`
- EOMIS integrity: `UNCHANGED`
- Ports 8000 and 8780: `UNCHANGED`

Historical failed workflows, commands, verifier attempts, deployment logs, and recovery records are
preserved as audit evidence. A successful later boundary never relabels an earlier failure.

## Deferred Non-Blocking Backlog

The following work is outside the Application API V0 release scope:

- production HWPX quality refinement, including a pinned Kordoc renderer adapter;
- long-term load and performance exercises;
- backup and restore rehearsal;
- optional resilience improvements;
- architecture cleanup;
- future TLS, LAN, and product-operations work;
- future SSO or MFA if required.

These are P2 or P3 follow-ups unless a later, independently demonstrated security or data-integrity
failure changes their priority.

## Development Handoff

The next product track is `WEB_GUI_V0`: natural-language item requests and Request Drafts,
workflow timeline/log views, reviewer approval UX, completed Item/Revision views, secure HWPX
build/download, and a read-only DB Explorer. Integrated Science Content Pack V0, production
taxonomy/rubric rules, and further HWPX refinement follow as application-layer work.
