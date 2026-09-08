# Application API Privileged Deployment

Deployment has three ordered phases:

1. As `eom`, validate the clean release and run `scripts/api/deploy_release.sh --build-only`.
2. In a reviewed interactive operator shell, refresh sudo once and run the documented bootstrap and
   config installation commands with `sudo -n`. Then run `deploy_release.sh --install` as `eom`.
3. Drop the sudo timestamp and run unprivileged smoke, contract, authentication, and RBAC checks.

Codex and unattended automation do not acquire sudo credentials. `deploy_release.sh` performs a
noninteractive privilege preflight before any build or install side effect and every internal
privileged command uses `sudo -n`. Wheel build and pip installation always remain under `eom`.

The deployment installs reviewed metadata and runtime verifiers at
`/usr/local/libexec/eom-api/verify-deployment-metadata` and
`/usr/local/libexec/eom-api/verify-runtime-isolation` as `root:root:0755`, installs the unit,
verifies protected metadata, reloads systemd, enables and restarts the service, waits for health,
runs the service-context isolation verifier, and records wheel hashes. A failed preflight changes
nothing. A later failure stops the sequence; inspect systemd and the recorded prior release rather
than weakening file or sandbox permissions.

No phase changes UFW, `/etc/fstab`, ports 8000 or 8780, Observability, worker groups, Docker groups,
NAS, EOMIS, Git history, or a public network bind.

## Exceptional Workflow-runner hold

Use `--install-preserve-workflow-runner-inactive` only for the reviewed mock-exam retirement
sequence. It requires the local runner unit to be loaded, inactive/dead, without a PID or queued
systemd Job. Before any release mutation, it atomically installs the pinned root-owned persistent
drop-in and proves the exact loaded path, SHA-256, metadata, `RefuseManualStart=yes`,
`ConditionPathExists=!/`, and `NeedDaemonReload=no`. This blocks explicit start/restart requests and
skips dependency activation before `ExecStart`, including across reboot. Hold acquisition disables
the stopped unit with `--no-reload`, writes the barrier, re-enables with `--no-reload` only after the
barrier is durable on disk, then reloads once and proves the enabled barrier. Hold release disables
without reload before removing the barrier.

Commit `6691567` may have left `/run/systemd/system/eom-workflow-runner.service -> /dev/null`. That
lower-precedence mask does not hold a complete unit installed under `/etc`. The installer removes it
only after proving its exact root-owned symlink identity and proving the persistent drop-in is
already effective. Any different file, owner, target, or loaded drop-in set stops the deployment for
manual review.

Keep the hold in place until `retire-items` returns and the operator has independently reviewed the
immutable checkpoint pins and the self-hashed receipt for the exact 25-Workflow cohort. The access
token must already be the invoking `eom-api` identity's non-symlinked mode-0600 file. Check only its
metadata; never print its contents. The held installer creates the fixed receipt directory as
`eom-api:eom-api:0700` and refuses an existing path with any other identity:

Treat retirement through hold release as one exclusive recovery window. Do not run `initialize`,
`advance-*`, `status`, or another mock-exam production CLI command concurrently. The release
verifier takes the checkpoint store's nonblocking exclusive lock, re-reads `current.json`, and
retains the lock through the complete systemd hold mutation handshake. Any official concurrent
writer therefore fails or waits without advancing the checkpoint until release has completed. The
exclusive operator window additionally forbids unrelated production commands.

```bash
EXECUTION_ID='productionexec_<32 lowercase hex>'
ACCESS_TOKEN_FILE='/run/eom-api-mock-exam/access.token'
RECEIPT_ROOT='/var/lib/eom-api/mock-exam-retirement-receipts'
RECEIPT_FILE="${RECEIPT_ROOT}/${EXECUTION_ID}.retirement-receipt.json"

sudo -n test ! -L "${ACCESS_TOKEN_FILE}"
test "$(sudo -n stat --format='%U:%G:%a' -- "${ACCESS_TOKEN_FILE}")" = \
  'eom-api:eom-api:600'

sudo -n systemd-run --quiet --wait --pipe --collect --service-type=exec \
  --expand-environment=no \
  --unit=eom-mock-exam-retire.service \
  --uid=eom-api --gid=eom-api --working-directory=/var/lib/eom-api \
  --property=EnvironmentFile=/etc/eom/secrets/api.env \
  --setenv=EOM_API_CONFIG=/etc/eom-api/api.yaml \
  --setenv=HOME=/var/lib/eom-api --setenv=PATH=/usr/bin:/bin \
  --setenv=PYTHONSAFEPATH=1 --property=UMask=0077 \
  --property=NoNewPrivileges=yes --property=ProtectSystem=strict \
  --property=ProtectHome=yes --property=PrivateTmp=yes \
  --property=ReadWritePaths=/var/lib/eom-api \
  /usr/bin/bash -c '
    set -euo pipefail
    umask 077
    execution_id="$1"
    access_token_file="$2"
    receipt_root="$3"
    [[ "${execution_id}" =~ ^productionexec_[0-9a-f]{32}$ ]]
    [[ "${access_token_file}" == /run/eom-api-mock-exam/access.token ]]
    [[ "${receipt_root}" == /var/lib/eom-api/mock-exam-retirement-receipts ]]
    receipt_file="${receipt_root}/${execution_id}.retirement-receipt.json"
    [[ ! -e "${receipt_file}" && ! -L "${receipt_file}" ]]
    staged="$(/usr/bin/mktemp \
      --tmpdir="${receipt_root}" ".${execution_id}.retirement-receipt.XXXXXX")"
    cleanup_staged_receipt() { /usr/bin/rm -f -- "${staged}"; }
    trap cleanup_staged_receipt EXIT
    /srv/eom/conda/envs/eom-api/bin/eom-api mock-exam-production retire-items \
      "${execution_id}" --access-token-file "${access_token_file}" \
      --checkpoint-root /var/lib/eom-api/mock-exam-production >"${staged}"
    /usr/bin/ln -T -- "${staged}" "${receipt_file}"
    /usr/bin/rm -- "${staged}"
    trap - EXIT
  ' eom-mock-exam-retire "${EXECUTION_ID}" "${ACCESS_TOKEN_FILE}" "${RECEIPT_ROOT}"
```

The transient command runs the installed CLI as `eom-api`. It writes to a fresh mode-0600 staging
inode, publishes the successful stdout envelope with a no-overwrite hard link, and removes the
staging link. A failed CLI never publishes the final filename. An interruption may leave a hidden
staging link or a final file with link count two; the release verifier rejects both until an operator
reviews and cleans only that exact materialization.

Set the following values from the independently reviewed immutable checkpoint and receipt. The
final `RECEIPT_SHA256` is the receipt's `data.receipt_sha256` self-hash, not a `sha256sum` of the JSON
envelope file. Do not populate all expected pins by blindly copying an unreviewed receipt:

```bash
EXECUTION_REVISION_ID='productionexecrev_<32 lowercase hex>'
CHECKPOINT_SHA256='sha256:<64 lowercase hex>'
PRODUCTION_REQUEST_ID='productionreq_<32 lowercase hex>'
PRODUCTION_PLAN_ID='productionplan_<32 lowercase hex>'
PRODUCTION_PLAN_SHA256='sha256:<64 lowercase hex>'
OPERATOR_ID='operator_<32 lowercase hex>'
RECEIPT_SHA256='sha256:<64 lowercase hex>'

scripts/api/deploy_release.sh --release-workflow-runner-hold \
  "${RECEIPT_FILE}" "${EXECUTION_ID}" "${EXECUTION_REVISION_ID}" \
  "${CHECKPOINT_SHA256}" "${PRODUCTION_REQUEST_ID}" "${PRODUCTION_PLAN_ID}" \
  "${PRODUCTION_PLAN_SHA256}" "${OPERATOR_ID}" "${RECEIPT_SHA256}"
```

Release first runs the installed root-owned verifier as unprivileged `eom-api`. It safely reads the
fixed receipt and current plus immutable checkpoint, validates installed JSON Schema and Pydantic
contracts, all explicit pins, hashes, and the exact 24-cancel/one-failed-preserved cohort. Only then
does it derive a retry-stable journal cursor from the immutable receipt retirement time, disable the
runner without reload under the still-loaded hold, atomically move the verified drop-in to a
non-`.conf` recovery name, reload systemd, and prove the base unit matches its canonical pinned hash.
The stopped unit's invocation identity must either remain exact or become systemd's empty baseline
after garbage collection; the latter is accepted only when the exact runner unit has no journal
entry after the receipt cursor. Missing journal access, malformed output, or a rotated cursor fails
closed. Release then proves the runner remains disabled and inactive with no drop-ins or Job,
repeats the state and journal fence, removes the exact backup, and completes the verifier handshake
while its checkpoint lock is still held. It does not start the runner. A retry with the backup uses
the same receipt-time cursor; a retry after completed backup removal is an exact disabled-state
no-op.
Enable and start it in a separate explicit step with
`sudo -n systemctl enable --now eom-workflow-runner.service`. If release is interrupted, rerun the
same fully pinned command; do not delete or edit files under the unit drop-in directory manually.
