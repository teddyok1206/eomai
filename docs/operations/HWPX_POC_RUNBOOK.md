# HWPX POC Runbook

## Status Levels

- `CODE_COMPLETE`: code, synthetic tests, migration, wheels, and sandbox pass.
- `REFERENCE_IMPORTED`: a Hancom-saved reference has passed import and immutable registration.
- `LINUX_POC_VALIDATED`: a reference-based build passes structural, semantic, and artifact commit.
- `HWPX_POC_V0_COMPLETE`: manual Hancom open/edit/save/reopen and re-saved comparison pass.

Do not describe a synthetic fixture as a reference or compatibility result.

## Prepare

```bash
/srv/eom/conda/envs/eom-core/bin/eomctl hwpx doctor
/srv/eom/conda/envs/eom-core/bin/eomctl hwpx reference-kit create
```

Create `eom_hwpx_reference_v1.hwpx` using
`HWPX_REFERENCE_TEMPLATE_CREATION.md`. Place it only in the fixed reference inbox. The importer
opens it read-only and canonical artifacts are committed through the existing artifact boundary.

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
