# Independent QUERY: authentication accepted, staging prerequisite missing

As of 2026-10-15 17:39:41 UTC. This is a bounded runtime observation, not full
similarity acceptance or a reinterpretation of the earlier stopped query.

- Installed compatible owner: `517e45510ee230d547f5d3b784c355002e6f30f9`.
- Genuine operator capture: PASS at17:35:40 UTC; credentials were not persisted.
- Existing exact index revision: `embeddingindexrev_ec428fa3e4bd4ecd878b68cee5d932b1`;
  coverage remains2/520. No new seed/delta work was submitted.
- New independent Workflow: `workflow_5fc6d19409da4146ac9b3ef7bcb24dc9`.
- Original START: `wfcmd_589cf4bf8c364e7986e941425237f1cc`.
- Native allocation: `job_75571c2b502f423dbb75e76ba0ba9904`.
- Workflow request SHA:
  `sha256:69336effe0c8ccfdf906b91a851ae0e47f11dfb1f14fd9f224afdd3124b3032d`.

Submission finished at17:35:57 UTC. Staging stopped at17:36:48 UTC with
`INFERENCE_CPU_DIRECTORY_INVALID`/`FileNotFoundError`. Read-only layout inspection
confirmed that `/var/lib/eom-workflow-runner/incremental-embeddings/query` was
absent; its parent and the existing INDEX capacity root had the expected private
owner/group/mode. The runtime-only launcher preflight did not check this owner
staging prerequisite.

Exact-ID metadata inspection found the RUNNING step and original native
ALLOCATION in the same committed history, with no output pointer. Both exact
prepare/query unit InvocationIDs were empty. There is no successful model result
or current similarity context to report. The controller process exited; the DB
RUNNING state is not evidence that computation continues.

Preserve this Workflow/START/Job and the earlier
`workflow_38a7254f053449739ef31f5d535ff604`. Repair the deployment prerequisite
and test fail-closed readiness before using supported original-identity recovery.
Do not submit a replacement key, fabricate a launch/receipt or mark either history
successful. No shared API/runner activation, authority/TTL change or additional
model execution was performed by this diagnosis.

Evidence (local sanitized metadata, not credentials/item text):

- `/tmp/eom-identity-provider-install.nAaycoDM/genuine-reference-query-atomic-execution.log`
- `/tmp/eom-identity-provider-install.nAaycoDM/query-workspace-layout-diagnosis.log`
- `/tmp/eom-identity-provider-install.nAaycoDM/query-atomic-stopped-metadata.log`

## Scoped correction and source regression

The absent `query` directory was created exclusively with mode0700 by the actual
`eom-workflow-runner` account. No existing directory, ACL, group membership,
installed prefix, CPU environment, DB row or service activation was changed.
Root layout inspection confirmed its expected owner/group/mode. The existing
installed owner/runtime/index preflight passed again at17:45:09 UTC without
authentication, database mutation or model execution.

The source QUERY launcher now checks its fixed owner staging root using the same
retained-ancestor-FD boundary used by actual staging. This is a read-only runtime
prerequisite, not a source permission or native launch grant. Missing, symlink,
file and unsafe-mode roots are rejected without creation/repair. It is checked by
executor readiness before the atomic RUNNING/allocation commit. Workflow request
admission remains separate; it does not gain filesystem side effects.

Affected QUERY/INDEX handoff, shared CPU lifecycle and native executor regression:
120 PASS in67.57s. This includes the missing-root reproduction, preserved layout,
redacted not-ready result and absence of native allocation/model execution. Strict
mypy: two production modules PASS; Ruff/format: five Python files PASS. No DB
schema, protocol, policy, template bytes, dependency or queue changed; the earlier
87-test PostgreSQL gate is referenced, not rerun as a new filesystem proof.

The source guard is not yet installed in the compatible517e4551 owner. Current
recovery preparation instead verifies the corrected folder explicitly using that
installed owner's supported FD boundary and keeps its exact package pins. A
read-only diagnostic initially invoked an execution-owner read that uses FOR SHARE;
PostgreSQL correctly rejected it. The harness now uses read-only metadata and pure
contract validation before authentication; the actual runner retains its official
locking and current-authority checks. That harness failure is not a runtime
state-machine defect or permission to relax the read-only diagnostic.
