# HWPX POC Runbook

## Status Levels

- `CODE_COMPLETE`: code, synthetic tests, migration, wheels, and sandbox pass.
- `REFERENCE_IMPORTED`: a Hancom-saved reference has passed import and immutable registration.
- `LINUX_POC_VALIDATED`: a reference-based build passes structural, semantic, and artifact commit.
- `HWPX_POC_V0_COMPLETE`: manual Hancom open/edit/save/reopen and re-saved comparison pass.

Do not describe a synthetic fixture as a reference or compatibility result.

## Prepare

Bootstrap the locked system user and install a reviewed clean commit as non-editable wheels:

```bash
sudo /home/eom/EOM/scripts/hwpx/bootstrap_builder_user.sh
/home/eom/EOM/scripts/hwpx/deploy_builder.sh --install
/home/eom/EOM/scripts/hwpx/deploy_builder.sh --verify
```

Wheel builds occur from a temporary source copy under `/tmp`; build directories and editable
metadata are never left in the repository. Deployment records the previous versions and installed
commit under `/var/lib/eom-hwpx/deployments/`. Roll back by force-reinstalling the reviewed wheels
from the recorded prior release directory, then run `--verify` and `eomctl hwpx doctor`.

```bash
/srv/eom/conda/envs/eom-core/bin/eomctl hwpx doctor
```

Stage the existing Hancom-saved content-team template and reference PNG into a fresh local workspace,
then create `eom_hwpx_reference_v1.hwpx` with the profile-bound command documented in
`HWPX_REFERENCE_TEMPLATE_CREATION.md`. Do not edit the EOMIS source. The generated candidate keeps
the `1x1`, `3x3`, and `9x4` authoring-form surfaces, creates the POC `2x3` data table, and omits the
unrelated generic-choice `5x2` table. Place only the validated candidate in the fixed reference inbox.
The importer opens it read-only and canonical artifacts are committed through the existing artifact
boundary.

## Inspect And Import

```bash
/srv/eom/conda/envs/eom-core/bin/eomctl hwpx template inspect \
  /mnt/nas/eom/hwpx/poc-v0/reference/inbox/eom_hwpx_reference_v1.hwpx

/srv/eom/conda/envs/eom-core/bin/eomctl hwpx template import \
  /mnt/nas/eom/hwpx/poc-v0/reference/inbox/eom_hwpx_reference_v1.hwpx \
  --name placeholder-item-v1 \
  --hancom-version '<EXACT_RECORDED_VERSION>'
```

Review the bounded analysis summary, all marker counts, image binding, equation binding, active
content scan, package profile, and hashes before approving the template revision.

## Build

Use the kit input as a placeholder-only starting point and replace no field with real assessment
content in this POC.

```bash
/srv/eom/conda/envs/eom-core/bin/eomctl hwpx build \
  --template-revision <TEMPLATE_REVISION_ID> \
  --input /mnt/nas/eom/hwpx/poc-v0/reference-kit/v1/reference-input.example.json \
  --idempotency-key hwpx-poc-v0-placeholder-1

/srv/eom/conda/envs/eom-core/bin/eomctl hwpx build inspect <BUILD_ID>
/srv/eom/conda/envs/eom-core/bin/eomctl hwpx build locate <BUILD_ID>
```

A build is not successful when `result.json` is missing, invalid, reports failure, has a mismatched
hash, or either validation report fails. NAS commit occurs only after eom-core repeats validation.

## Manual Gate

Continue with `HWPX_MANUAL_HANCOM_VALIDATION.md`. Before this gate, the expected build state is
`PENDING_MANUAL_VALIDATION`, not complete.

The transient unit runs as `eom-hwpx` with `PrivateNetwork`, no privileges, a strict filesystem,
and explicit denial of NAS, the Git checkout, Docker, Codex, worker homes, and EOM secrets. Only the
assigned build workspace is writable.
