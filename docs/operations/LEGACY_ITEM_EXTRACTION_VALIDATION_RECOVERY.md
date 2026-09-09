# Legacy item extraction validation recovery

Status: source-only runbook; no live deployment, bootstrap, continuation, or worker call has been
executed from this change.

## Closed scope and frozen inputs

This runbook deploys one additive protocol successor, publishes one non-live-evaluated extraction
preset successor, and creates one fresh three-work-unit continuation for the 15 missing scoped item
occurrences. It does not change the extraction result schema, canonicalize worker output, retry a
failed historical work unit, modify EOMIS, write directly to NAS, or use an external LLM API.

The implementation is based on commit
`76a1b697acb03f2148288b62b86cd54936f81010`. Before use, replace `FROZEN_COMMIT` below with the
independently reviewed final successor commit and require `/home/eom/EOM` to be clean at exactly
that commit. The final review record must also retain these source identities:

| Source | SHA-256 |
| --- | --- |
| control bootstrap V2 JSON Schema | `66d3874bbb4a58fe67520be60ca5c564b9444fd4eada0846254ba5c5bac2a635` |
| recovery authorization JSON Schema | `9cdbbc056f0919bc84e73040986d913c5ecbf664760c7ecc2f7a7398138a77f0` |
| V2 `bootstrap.yaml` | `ca41967a8cef9bce33b4cce49280a12832900c9ed0a29bfdd8aa6bcfd7f6e93d` |
| unchanged platform instruction | `82bb9a60c210a7e918f5ebcf9c609e9bd4774af75688b0a628ce421ec9d3f61b` |
| successor role instruction | `a87dd5868fffd746f410f0cddeb34b16672f2159f5c10e84e141478360df96b0` |

The exact reviewed predecessor is:

- batch `legacybatch_5455e7556c34ac3f3a577435263d06bd`, expected state
  `COMPLETED_WITH_GAPS`, 105 accepted and three failed;
- preset `execpreset_fbd4c93912ae421689ab340c60eac00d`, released revision
  `execpresetrev_4249f0c07653430aab1b9eff3626d694`, revision number 2, content SHA
  `sha256:ab85a0df6ba31be10a370ac969d007537f6cfa9819c7192c827588fcc2ea482b`,
  policy SHA
  `sha256:3f692e048f134c290645893eaf0297eb2b0f2bbeb4e547b68d611ec4f39e11a4`;
- instruction bundle `instrbundle_25335ef258798df97289805812c68432`, revision
  `instrrev_8b104f84bf1288a7cab59c2bd0de2ba9`, revision number 1, manifest SHA
  `sha256:59e787825fca530944e2b36202c82734e4a8013a3337afc55649a9925a3ab4b3`,
  content SHA
  `sha256:c2f0ea68700fdc66d24e3ef49ee8c51ee42775d2ccb19e4be487f2c7416d6633`;
- the manifest Artifact pointer SHA, the canonical preset manifest SHA, the persisted bundle
  revision manifest SHA, and the recovery authorization manifest SHA must be byte-identical;
- capacity revision `capacityrev_d8ce74ff203d225081fe8e9686457dd9`, SHA
  `sha256:0d57aca8671aebd1f487bb1d39ef1bbfb75b07f618bd26a38e863d69920f1660`;
- workflow definition `wfdef_67802c80675649d9945201cf440a2a71`, version `1.0.0`, SHA
  `sha256:03b240e6f880f7699a6a2f9184a422caac781c3d24c7b175795dc73e91cc059b`;
- role schema `workflow-role/1.14.0`, SHA
  `sha256:204a5070a9c465dde25677688980463c1df8feba64673001e2477a11d9f69e54`.

The successor instruction bundle revision ID is deterministically
`instrrev_efaa85f9c4448976b46914b3b1c13040`. The preset revision ID and the target content hashes are
created by the immutable bootstrap and must be copied only from its validated result; they must
never be found by querying a latest revision.

## Source gate

Run this gate as the unprivileged repository owner from the clean final commit. Use the explicit
Conda environment; do not rely on an ambient Python.

```bash
cd /home/eom/EOM
: "${FROZEN_COMMIT:?set FROZEN_COMMIT to the independently reviewed successor commit}"
BASE_COMMIT='76a1b697acb03f2148288b62b86cd54936f81010'
PYTHON=/srv/eom/conda/envs/eom-core/bin/python
PYTHONPATH='packages/protocol:packages/identifiers:packages/workflow:packages/catalog_contracts:packages/api_contracts:packages/content_pack:packages/item_registry:services/orchestrator:services/catalog_service:services/workflow_runner:apps/application_api:apps/eomctl:packages/operator_identity:services/identity_service:packages/hwpx_contracts:services/hwpx_manager:packages/image_contracts:packages/content_intake'

test "$(git rev-parse HEAD)" = "${FROZEN_COMMIT}"
test -z "$(git status --porcelain)"
git merge-base --is-ancestor "${BASE_COMMIT}" "${FROZEN_COMMIT}"
git diff --check "${BASE_COMMIT}..${FROZEN_COMMIT}"
sha256sum --check <<'SHA256'
66d3874bbb4a58fe67520be60ca5c564b9444fd4eada0846254ba5c5bac2a635  schemas/workflow/control-plane/legacy-item-extraction-control-bootstrap-v2.schema.json
9cdbbc056f0919bc84e73040986d913c5ecbf664760c7ecc2f7a7398138a77f0  schemas/legacy-assessment/legacy-item-extraction-validation-recovery-v1.schema.json
ca41967a8cef9bce33b4cce49280a12832900c9ed0a29bfdd8aa6bcfd7f6e93d  config/control-plane/legacy-item-extraction-v2/bootstrap.yaml
82bb9a60c210a7e918f5ebcf9c609e9bd4774af75688b0a628ce421ec9d3f61b  config/control-plane/legacy-item-extraction-v2/instructions/platform.md
a87dd5868fffd746f410f0cddeb34b16672f2159f5c10e84e141478360df96b0  config/control-plane/legacy-item-extraction-v2/instructions/legacy-item-extraction.md
SHA256
cmp \
  schemas/workflow/control-plane/legacy-item-extraction-control-bootstrap-v2.schema.json \
  packages/workflow/eom_workflow/resources/control-plane/legacy-item-extraction-control-bootstrap-v2.schema.json
cmp \
  schemas/legacy-assessment/legacy-item-extraction-validation-recovery-v1.schema.json \
  packages/catalog_contracts/eom_catalog_contracts/resources/legacy-assessment/legacy-item-extraction-validation-recovery-v1.schema.json

PYTHON_FILES=(
  packages/catalog_contracts/eom_catalog_contracts/__init__.py
  packages/catalog_contracts/eom_catalog_contracts/legacy_extraction_recovery.py
  packages/catalog_contracts/eom_catalog_contracts/validation.py
  packages/workflow/eom_workflow/control_schemas.py
  services/orchestrator/eom_orchestrator/control_bootstrap.py
  services/orchestrator/eom_orchestrator/control_service.py
  services/orchestrator/eom_orchestrator/legacy_item_extraction_bootstrap.py
  services/catalog_service/eom_catalog_service/legacy_extraction_preset_resolution.py
  services/catalog_service/eom_catalog_service/legacy_item_extraction_batch_service.py
  services/catalog_service/eom_catalog_service/legacy_item_extraction_recovery_service.py
  apps/eomctl/eomctl/legacy_assessment.py
  tests/unit/test_catalog_contract_resources.py
  tests/unit/test_control_bundle_successor_cas.py
  tests/unit/test_execution_control_contracts.py
  tests/unit/test_legacy_extraction_batch_service.py
  tests/unit/test_legacy_extraction_preset_resolution.py
  tests/unit/test_legacy_extraction_recovery_contracts.py
  tests/unit/test_legacy_item_extraction_bootstrap.py
  tests/unit/test_legacy_item_extraction_recovery_service.py
)
PYTHONPATH="${PYTHONPATH}" "${PYTHON}" -m ruff format --check "${PYTHON_FILES[@]}"
PYTHONPATH="${PYTHONPATH}" "${PYTHON}" -m ruff check "${PYTHON_FILES[@]}"
PYTHONPATH="${PYTHONPATH}" "${PYTHON}" -m mypy --strict \
  packages/catalog_contracts/eom_catalog_contracts/legacy_extraction_recovery.py \
  packages/catalog_contracts/eom_catalog_contracts/validation.py \
  packages/workflow/eom_workflow/control_schemas.py \
  services/orchestrator/eom_orchestrator/control_bootstrap.py \
  services/orchestrator/eom_orchestrator/control_service.py \
  services/orchestrator/eom_orchestrator/legacy_item_extraction_bootstrap.py \
  services/catalog_service/eom_catalog_service/legacy_extraction_preset_resolution.py \
  services/catalog_service/eom_catalog_service/legacy_item_extraction_recovery_service.py \
  services/catalog_service/eom_catalog_service/legacy_item_extraction_batch_service.py \
  apps/eomctl/eomctl/legacy_assessment.py
PYTHONPATH="${PYTHONPATH}" "${PYTHON}" -m pytest -q \
  tests/unit/test_catalog_contract_resources.py \
  tests/unit/test_control_bundle_successor_cas.py \
  tests/unit/test_execution_control_contracts.py \
  tests/unit/test_legacy_item_extraction_bootstrap.py \
  tests/unit/test_legacy_extraction_preset_resolution.py \
  tests/unit/test_legacy_extraction_recovery_contracts.py \
  tests/unit/test_legacy_item_extraction_recovery_service.py \
  tests/unit/test_legacy_extraction_batch_contracts.py \
  tests/unit/test_legacy_extraction_batch_service.py \
  tests/unit/test_legacy_item_automation_service.py \
  tests/unit/test_workflow_package_resources.py
```

Stop before deployment unless all focused gates pass, both copies of each new schema are
byte-identical, the repository contains no secrets or generated recovery JSON, and the final commit
has been independently reviewed. No migration or dependency installation is part of this change.

## Quiescence and deployment gate

Before a service restart, obtain a fresh content-free, read-only runtime observation proving:

- no active Job, workflow, command, worker lease, HWPX build, or nonterminal extraction batch;
- slot 06 has no active or reconciling lease and its exact auth/capability is ready for
  `gpt-5.6-terra/xhigh`;
- no mock-exam retirement/deployment hold or other exclusive recovery window is active;
- the predecessor batch is still 105 accepted plus exactly the three reviewed failed rows; and
- API, Catalog, workflow runner, HWPX runner, PostgreSQL, and the reserved `127.0.0.1:8765` API are
  healthy.

The database state may change after the source gate. Re-run the observation immediately before
installation and immediately before continuation creation. Any mismatch is a stop condition, not
permission to edit a pin. The database claim and lease constraints remain the final concurrent
slot guard.

After the frozen commit has been integrated into the clean `/home/eom/EOM` main worktree, use only
the repository installer. It builds and installs the reviewed platform/API wheel set and restarts
its owning consumers. It does not require an Alembic migration for this successor.

```bash
cd /home/eom/EOM
test "$(git rev-parse HEAD)" = "${FROZEN_COMMIT}"
test -z "$(git status --porcelain)"
scripts/api/deploy_release.sh --build-only
scripts/api/deploy_release.sh --install
scripts/api/deploy_release.sh --verify
```

Record the protected deployment receipt and exact wheel hashes. Re-run the quiescence observation
after installation. Stop if any installed import resolves to the checkout, any service is unhealthy,
or any workload was admitted during the restart window.

Verify that the installed resources have the reviewed identities without printing configuration or
credentials:

```bash
/srv/eom/conda/envs/eom-api/bin/python - <<'PY'
from eom_catalog_contracts import catalog_schema_inventory
from eom_workflow import control_schema_inventory

catalog = dict(catalog_schema_inventory())
control = dict(control_schema_inventory())
assert catalog["legacy-item-extraction-validation-recovery"].sha256 == (
    "sha256:9cdbbc056f0919bc84e73040986d913c5ecbf664760c7ecc2f7a7398138a77f0"
)
assert control["legacy-item-extraction-control-bootstrap-v2"].sha256 == (
    "sha256:66d3874bbb4a58fe67520be60ca5c564b9444fd4eada0846254ba5c5bac2a635"
)
PY
```

## Non-live V2 bootstrap

Create a fresh protected local evidence directory outside Git. `OPERATOR_ID` must be one existing
active operator ID; do not invent or silently substitute it.

```bash
umask 077
RECOVERY_ROOT="$(mktemp -d /tmp/eom-legacy-extraction-validation-recovery.XXXXXX)"
EOMCTL=/srv/eom/conda/envs/eom-api/bin/eomctl
OPERATOR_ID='operator_<reviewed 32 lowercase hex>'
BOOTSTRAP_RESULT="${RECOVERY_ROOT}/bootstrap-v2.json"
BATCH_INSPECT="${RECOVERY_ROOT}/predecessor-batch.json"

"${EOMCTL}" legacy-assessment extraction-batch inspect \
  legacybatch_5455e7556c34ac3f3a577435263d06bd >"${BATCH_INSPECT}"
jq -e '
  .status == "SUCCEEDED" and
  .extraction_batch_id == "legacybatch_5455e7556c34ac3f3a577435263d06bd" and
  .state == "COMPLETED_WITH_GAPS" and
  .total_work_unit_count == 108 and
  .accepted_count == 105 and .failed_count == 3 and
  .pending_count == 0 and .claimed_count == 0 and .submitted_count == 0 and
  (.manifest_sha256 | test("^sha256:[0-9a-f]{64}$"))
' "${BATCH_INSPECT}" >/dev/null

"${EOMCTL}" control-plane bootstrap-legacy-item-extraction \
  --source-commit "${FROZEN_COMMIT}" \
  --actor-id "${OPERATOR_ID}" \
  --evaluation-cases-total 3 \
  --config-directory /home/eom/EOM/config/control-plane/legacy-item-extraction-v2 \
  >"${BOOTSTRAP_RESULT}"

jq -e --arg commit "${FROZEN_COMMIT}" '
  .status == "SUCCEEDED" and .source_commit == $commit and
  .preset_id == "execpreset_fbd4c93912ae421689ab340c60eac00d" and
  .preset_revision_number == 4 and
  (.preset_revision_id | test("^execpresetrev_[0-9a-f]{32}$")) and
  .preset_revision_id != "execpresetrev_4249f0c07653430aab1b9eff3626d694" and
  (.preset_content_sha256 | test("^sha256:[0-9a-f]{64}$")) and
  .preset_content_sha256 != "sha256:ab85a0df6ba31be10a370ac969d007537f6cfa9819c7192c827588fcc2ea482b" and
  (.preset_policy_sha256 | test("^sha256:[0-9a-f]{64}$")) and
  .preset_policy_sha256 != "sha256:3f692e048f134c290645893eaf0297eb2b0f2bbeb4e547b68d611ec4f39e11a4" and
  .capacity_policy_revision_id == "capacityrev_d8ce74ff203d225081fe8e9686457dd9" and
  .capacity_policy_sha256 == "sha256:0d57aca8671aebd1f487bb1d39ef1bbfb75b07f618bd26a38e863d69920f1660" and
  .instruction_bundle_id == "instrbundle_25335ef258798df97289805812c68432" and
  .instruction_bundle_revision_id == "instrrev_efaa85f9c4448976b46914b3b1c13040" and
  .instruction_revision_number == 2 and
  (.instruction_manifest_sha256 | test("^sha256:[0-9a-f]{64}$")) and
  .instruction_manifest_sha256 != "sha256:59e787825fca530944e2b36202c82734e4a8013a3337afc55649a9925a3ab4b3" and
  (.instruction_content_sha256 | test("^sha256:[0-9a-f]{64}$")) and
  .instruction_content_sha256 != "sha256:c2f0ea68700fdc66d24e3ef49ee8c51ee42775d2ccb19e4be487f2c7416d6633"
' "${BOOTSTRAP_RESULT}" >/dev/null
```

This command publishes only reviewed control Artifacts and metadata; it does not submit a worker
Job. An exact replay of the same command must return the same released target. A changed source
commit, predecessor, instruction byte, hash, current pointer, evaluation, capacity pointer,
workflow definition, or schema must fail closed.

## Build the exact recovery authorization

The recovery document is created only after V2 bootstrap so it can pin the target revision and
hashes. The following content-free builder accepts only the two validated command outputs above,
uses deterministic fresh successor IDs, validates JSON Schema first and Pydantic second, and emits
the canonical self-hashed authorization. It does not access the database, NAS, PDFs, prompts, or
worker output.

```bash
RECOVERY_FILE="${RECOVERY_ROOT}/validation-recovery-v1.json"
test ! -e "${RECOVERY_FILE}"
/srv/eom/conda/envs/eom-api/bin/python - \
  "${BATCH_INSPECT}" "${BOOTSTRAP_RESULT}" >"${RECOVERY_FILE}" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

from eom_catalog_contracts import (
    LegacyItemExtractionValidationRecovery,
    validate_contract,
)
from eom_catalog_service.intake_files import load_strict_json
from eom_identifiers import content_sha256

batch = load_strict_json(Path(sys.argv[1]))
target = load_strict_json(Path(sys.argv[2]))
if (
    batch.get("status") != "SUCCEEDED"
    or batch.get("extraction_batch_id")
    != "legacybatch_5455e7556c34ac3f3a577435263d06bd"
    or batch.get("state") != "COMPLETED_WITH_GAPS"
    or batch.get("accepted_count") != 105
    or batch.get("failed_count") != 3
    or target.get("status") != "SUCCEEDED"
):
    raise SystemExit("reviewed predecessor/bootstrap envelope differs")

predecessor = {
    "preset_id": "execpreset_fbd4c93912ae421689ab340c60eac00d",
    "preset_revision_id": "execpresetrev_4249f0c07653430aab1b9eff3626d694",
    "preset_revision_number": 2,
    "preset_sha256": "sha256:ab85a0df6ba31be10a370ac969d007537f6cfa9819c7192c827588fcc2ea482b",
    "preset_policy_sha256": "sha256:3f692e048f134c290645893eaf0297eb2b0f2bbeb4e547b68d611ec4f39e11a4",
    "capacity_policy_revision_id": "capacityrev_d8ce74ff203d225081fe8e9686457dd9",
    "capacity_policy_sha256": "sha256:0d57aca8671aebd1f487bb1d39ef1bbfb75b07f618bd26a38e863d69920f1660",
    "instruction_bundle_id": "instrbundle_25335ef258798df97289805812c68432",
    "instruction_bundle_revision_id": "instrrev_8b104f84bf1288a7cab59c2bd0de2ba9",
    "instruction_revision_number": 1,
    "instruction_manifest_sha256": "sha256:59e787825fca530944e2b36202c82734e4a8013a3337afc55649a9925a3ab4b3",
    "instruction_content_sha256": "sha256:c2f0ea68700fdc66d24e3ef49ee8c51ee42775d2ccb19e4be487f2c7416d6633",
    "workflow_definition_id": "wfdef_67802c80675649d9945201cf440a2a71",
    "workflow_definition_version": "1.0.0",
    "workflow_definition_sha256": "sha256:03b240e6f880f7699a6a2f9184a422caac781c3d24c7b175795dc73e91cc059b",
    "role_schema_version": "workflow-role/1.14.0",
    "role_schema_sha256": "sha256:204a5070a9c465dde25677688980463c1df8feba64673001e2477a11d9f69e54",
}
successor = {
    **predecessor,
    "preset_revision_id": target["preset_revision_id"],
    "preset_revision_number": target["preset_revision_number"],
    "preset_sha256": target["preset_content_sha256"],
    "preset_policy_sha256": target["preset_policy_sha256"],
    "instruction_bundle_revision_id": target["instruction_bundle_revision_id"],
    "instruction_revision_number": target["instruction_revision_number"],
    "instruction_manifest_sha256": target["instruction_manifest_sha256"],
    "instruction_content_sha256": target["instruction_content_sha256"],
}
if (
    target.get("preset_id") != predecessor["preset_id"]
    or target.get("capacity_policy_revision_id")
    != predecessor["capacity_policy_revision_id"]
    or target.get("capacity_policy_sha256") != predecessor["capacity_policy_sha256"]
    or target.get("instruction_bundle_id") != predecessor["instruction_bundle_id"]
    or target.get("instruction_bundle_revision_id")
    != "instrrev_efaa85f9c4448976b46914b3b1c13040"
):
    raise SystemExit("successor dependency graph differs")

document = {
    "schema_version": "legacy-item-extraction-validation-recovery/1.0",
    "predecessor_batch_id": "legacybatch_5455e7556c34ac3f3a577435263d06bd",
    "predecessor_manifest_sha256": batch["manifest_sha256"],
    "predecessor_preset": predecessor,
    "successor_batch_id": "legacybatch_023ed9f07afa3bfb0b085fbdfc246dcb",
    "successor_idempotency_key": "legacy-item-extraction-validation-recovery-v1",
    "successor_preset": successor,
    "replacements": [
        {
            "predecessor_work_unit_id": "legacyworkunit_effa66b21814add8cac3d8cde5c5881b",
            "predecessor_ordinal": 23,
            "predecessor_extraction_request_id": "itemextractreq_d6f9643db154da55bb99902ff34f0eb5",
            "predecessor_request_sha256": "sha256:ef13a450ee4865eb36cd00ce4c8cebb17e19604eabbc03bd3a42f84776c72696",
            "predecessor_bundle_revision_id": "assessbundlerev_b6be31d55220e4c095d11433d394e641",
            "predecessor_workflow_id": "workflow_4406154020ab4da0915e1e91516ed169",
            "predecessor_platform_job_id": "job_666dcc4429274ea0b83e9e33f41f696b",
            "failure_code": "LEGACY_ITEM_EXTRACTION_WORKFLOW_FAILED",
            "workflow_failure_code": "WORKER_RESULT_INVALID",
            "job_error_code": "WORKER_RESULT_INVALID",
            "failure_message_sha256": "sha256:2ada76a1141d18b17a5471a274251fc12cf373ea5b2af6336b799f5dd2397cd9",
            "diagnosis_code": "DUPLICATE_STATEMENT_EXPLANATION_ID",
            "expected_item_numbers": [16, 17, 18, 19, 20],
            "expected_item_numbers_sha256": "sha256:5a7a50f290d5bf9e4ae39a9dbfe413b17f98fb8d8764f3a498582d0a8727c315",
            "successor_work_unit_id": "legacyworkunit_66854d36c201aa658ff90e7d9efb7784",
            "successor_ordinal": 0,
            "successor_extraction_request_id": "itemextractreq_877aca4bf33f06e9716b698899d86081",
        },
        {
            "predecessor_work_unit_id": "legacyworkunit_076f5ffc97766f3831592af2d0f1fdda",
            "predecessor_ordinal": 65,
            "predecessor_extraction_request_id": "itemextractreq_da8a18c0cb1d9358b49f4d349240fbfb",
            "predecessor_request_sha256": "sha256:308fd724239af7908b7b4aa8f6b7830479535ac1df1cd740b993e6b1acfb801f",
            "predecessor_bundle_revision_id": "assessbundlerev_2690a6a1e07e4789c17f9dd2e9e4cf4e",
            "predecessor_workflow_id": "workflow_39f300ceebdf436ea6b712cedd072a81",
            "predecessor_platform_job_id": "job_f8c4c7b0ec3743c3a1c35728900322de",
            "failure_code": "LEGACY_ITEM_EXTRACTION_WORKFLOW_FAILED",
            "workflow_failure_code": "WORKER_RESULT_INVALID",
            "job_error_code": "WORKER_RESULT_INVALID",
            "failure_message_sha256": "sha256:9a095854756f6d82c6d5fdc1f3bd88faee9ac0a7b5825050c3e45ed3a4c1b55a",
            "diagnosis_code": "BODY_BLOCK_DISCRIMINATOR_MISMATCH",
            "expected_item_numbers": [6, 7, 8, 9, 10],
            "expected_item_numbers_sha256": "sha256:a5713f9004dd495aa2e83a6d6e4636d4855a99b8342e1fa75e96273d08eb090e",
            "successor_work_unit_id": "legacyworkunit_c6d4cd41b1c2ce41a8985592ffbf5d7a",
            "successor_ordinal": 1,
            "successor_extraction_request_id": "itemextractreq_f73e0aee520113690da44a27e1d6df2b",
        },
        {
            "predecessor_work_unit_id": "legacyworkunit_cd81cbb341454ec4f7d7ae5a92767729",
            "predecessor_ordinal": 85,
            "predecessor_extraction_request_id": "itemextractreq_a89b1df115b0bad8ce68fde75aca8bf7",
            "predecessor_request_sha256": "sha256:185573101192bcc2ba0a91e1e9bfc65f5535cfa652b337dfbb470c978eea0d4f",
            "predecessor_bundle_revision_id": "assessbundlerev_4b1423ea0ceef51eb05cba9555b846ed",
            "predecessor_workflow_id": "workflow_70a2a4e900514bbc8aadfc5010686c0b",
            "predecessor_platform_job_id": "job_0a41515d5773468eb59662ceb6374cf7",
            "failure_code": "LEGACY_ITEM_EXTRACTION_WORKFLOW_FAILED",
            "workflow_failure_code": "WORKER_RESULT_INVALID",
            "job_error_code": "WORKER_RESULT_INVALID",
            "failure_message_sha256": "sha256:f375a267d5f0c116232b8a4408855f8e789b255c8f9b2ebcef4cd6ec1e1b67b7",
            "diagnosis_code": "NONE_VISUAL_RENDERING_CONFLICT",
            "expected_item_numbers": [5, 6, 7, 8, 9],
            "expected_item_numbers_sha256": "sha256:cfe2ea86126a9b7762f05df985e74f0814a50bde5ffdf2cfc388b48e5a7b3db5",
            "successor_work_unit_id": "legacyworkunit_dc364c9db2075d5893b1101fa0bc10ad",
            "successor_ordinal": 2,
            "successor_extraction_request_id": "itemextractreq_95334eb47d3417e05c2615e359fbc5a7",
        },
    ],
    "created_at": "2026-09-09T06:00:00Z",
    "recovery_sha256": "sha256:" + "0" * 64,
}
document["recovery_sha256"] = content_sha256(
    {key: value for key, value in document.items() if key != "recovery_sha256"}
)
validate_contract("legacy-item-extraction-validation-recovery", document)
recovery = LegacyItemExtractionValidationRecovery.model_validate(document)
print(json.dumps(recovery.model_dump(mode="json"), ensure_ascii=True, sort_keys=True, indent=2))
PY

test "$(jq -r '.successor_batch_id' "${RECOVERY_FILE}")" = \
  'legacybatch_023ed9f07afa3bfb0b085fbdfc246dcb'
jq -e '.replacements | length == 3' "${RECOVERY_FILE}" >/dev/null
sha256sum "${RECOVERY_FILE}"
```

The file SHA from `sha256sum` and the JSON `recovery_sha256` are deliberately separate identities.
Record both. Do not commit this generated authorization to Git.

## Create without executing, then stage extraction-only automation

Stop the Catalog application runner before creating the new batch. Its ordinary loop can claim any
eligible pending extraction batch, so this stop is the materialization boundary that keeps creation
separate from worker execution. Confirm the service is inactive and no Catalog systemd Job remains;
leave the workflow runner alone.

```bash
sudo -n systemctl stop eom-catalog-application-runner.service
test "$(systemctl is-active eom-catalog-application-runner.service)" = inactive
test "$(systemctl show -p Job --value eom-catalog-application-runner.service)" = ''

CONTINUATION_CREATE="${RECOVERY_ROOT}/continuation-create.json"
"${EOMCTL}" legacy-assessment extraction-batch recover-validation-failures \
  --recovery-file "${RECOVERY_FILE}" \
  --actor-id "${OPERATOR_ID}" >"${CONTINUATION_CREATE}"
jq -e --arg recovery "$(jq -r '.recovery_sha256' "${RECOVERY_FILE}")" '
  .status == "SUCCEEDED" and .recovery_sha256 == $recovery and
  .batch.extraction_batch_id == "legacybatch_023ed9f07afa3bfb0b085fbdfc246dcb" and
  .batch.total_work_unit_count == 3 and .batch.pending_count == 3 and
  .batch.failed_count == 0 and .batch.state == "QUEUED" and
  .successor_manifest_sha256 == .batch.manifest_sha256
' "${CONTINUATION_CREATE}" >/dev/null
```

Replay the exact command while the runner remains stopped. It must return the same batch and
manifest hashes and must not create another Artifact, batch, or work unit.

```bash
CONTINUATION_REPLAY="${RECOVERY_ROOT}/continuation-replay.json"
"${EOMCTL}" legacy-assessment extraction-batch recover-validation-failures \
  --recovery-file "${RECOVERY_FILE}" \
  --actor-id "${OPERATOR_ID}" >"${CONTINUATION_REPLAY}"
jq -e --arg recovery "$(jq -r '.recovery_sha256' "${RECOVERY_FILE}")" '
  .status == "SUCCEEDED" and .recovery_sha256 == $recovery and
  .batch.extraction_batch_id == "legacybatch_023ed9f07afa3bfb0b085fbdfc246dcb" and
  .batch.total_work_unit_count == 3 and .batch.pending_count == 3 and
  .batch.failed_count == 0 and .batch.state == "QUEUED" and
  .successor_manifest_sha256 == .batch.manifest_sha256
' "${CONTINUATION_REPLAY}" >/dev/null
test "$(jq -r '.successor_manifest_sha256' "${CONTINUATION_REPLAY}")" = \
  "$(jq -r '.successor_manifest_sha256' "${CONTINUATION_CREATE}")"
test "$(jq -r '.batch.manifest_artifact_revision_id' "${CONTINUATION_REPLAY}")" = \
  "$(jq -r '.batch.manifest_artifact_revision_id' "${CONTINUATION_CREATE}")"
```

Retain a content-free row/event-count observation proving replay left one successor batch, three
successor work units, and one original `BATCH_CREATED` event. A mismatch is a stop condition.

First activate extraction without automatic acceptance/learning. Preserve every unrelated line in
`/etc/eom/legacy-item-automation.env`; change only the ordered batch allowlist to predecessor then
successor and change `EOM_LEGACY_ITEM_AUTOMATION_MODE` to `DISABLED`. Install the reviewed staged
file atomically with its existing owner/group/mode, then start Catalog. Do not alter the separate
analysis retry allowlist prepared by the analysis-recovery runbook.

```text
EOM_LEGACY_ITEM_AUTOMATION_MODE=DISABLED
EOM_LEGACY_ITEM_AUTOMATION_BATCH_ID=legacybatch_5455e7556c34ac3f3a577435263d06bd
EOM_LEGACY_ITEM_AUTOMATION_BATCH_IDS=legacybatch_5455e7556c34ac3f3a577435263d06bd,legacybatch_023ed9f07afa3bfb0b085fbdfc246dcb
```

Use this bounded replacement rather than reconstructing the rest of the environment file:

```bash
AUTOMATION_ENV=/etc/eom/legacy-item-automation.env
AUTOMATION_STAGE_A="${RECOVERY_ROOT}/legacy-item-automation-stage-a.env"
AUTOMATION_INCOMING=/etc/eom/.legacy-item-automation.recovery-v1.incoming
BATCH_ALLOWLIST='legacybatch_5455e7556c34ac3f3a577435263d06bd,legacybatch_023ed9f07afa3bfb0b085fbdfc246dcb'

test "$(stat --format='%U:%G:%a' "${AUTOMATION_ENV}")" = 'root:root:644'
test ! -L "${AUTOMATION_ENV}"
AUTOMATION_BEFORE_SHA256="$(sha256sum "${AUTOMATION_ENV}" | awk '{print $1}')"
awk -v batches="${BATCH_ALLOWLIST}" '
  BEGIN { mode = 0; batch_ids = 0 }
  /^EOM_LEGACY_ITEM_AUTOMATION_MODE=/ {
    print "EOM_LEGACY_ITEM_AUTOMATION_MODE=DISABLED"; mode += 1; next
  }
  /^EOM_LEGACY_ITEM_AUTOMATION_BATCH_IDS=/ {
    print "EOM_LEGACY_ITEM_AUTOMATION_BATCH_IDS=" batches; batch_ids += 1; next
  }
  { print }
  END { if (mode != 1 || batch_ids != 1) exit 42 }
' "${AUTOMATION_ENV}" >"${AUTOMATION_STAGE_A}"
test "$(grep -c '^EOM_LEGACY_ITEM_AUTOMATION_MODE=DISABLED$' "${AUTOMATION_STAGE_A}")" = 1
test "$(grep -c "^EOM_LEGACY_ITEM_AUTOMATION_BATCH_IDS=${BATCH_ALLOWLIST}$" \
  "${AUTOMATION_STAGE_A}")" = 1
test "$(grep -c '^EOM_LEGACY_ITEM_AUTOMATION_BATCH_ID=legacybatch_5455e7556c34ac3f3a577435263d06bd$' \
  "${AUTOMATION_STAGE_A}")" = 1
sudo -n test ! -e "${AUTOMATION_INCOMING}"
sudo -n test ! -L "${AUTOMATION_INCOMING}"
sudo -n install -o root -g root -m 0644 \
  "${AUTOMATION_STAGE_A}" "${AUTOMATION_INCOMING}"
test "$(sudo -n stat --format='%U:%G:%a' "${AUTOMATION_INCOMING}")" = 'root:root:644'
test "$(sha256sum "${AUTOMATION_ENV}" | awk '{print $1}')" = "${AUTOMATION_BEFORE_SHA256}"
test ! -L "${AUTOMATION_ENV}"
sudo -n mv -T "${AUTOMATION_INCOMING}" "${AUTOMATION_ENV}"
test "$(stat --format='%U:%G:%a' "${AUTOMATION_ENV}")" = 'root:root:644'
```

Before starting, re-run the no-active-work/slot-06/retirement-hold observation. Then:

```bash
sudo -n systemctl start eom-catalog-application-runner.service
test "$(systemctl is-active eom-catalog-application-runner.service)" = active
```

The existing global extraction claim lock, single in-flight work-unit rule, capacity policy, and
slot lease ensure these three units execute serially and do not overlap another slot-06 extraction.
The continuation has only `EXECUTE` units and no reuse or acceptance pointer. Poll only the
content-free views:

```bash
"${EOMCTL}" legacy-assessment extraction-batch inspect \
  legacybatch_023ed9f07afa3bfb0b085fbdfc246dcb
"${EOMCTL}" legacy-assessment extraction-batch work-units \
  legacybatch_023ed9f07afa3bfb0b085fbdfc246dcb
```

The extraction-only gate passes only when the batch is `AWAITING_REVIEW`, all three units are
`AWAITING_REVIEW`, each has `submission_attempts=1`, and each has non-null, unique workflow, Job,
extraction-result, result-hash, and receipt pointers with no error code. JSON Schema and Pydantic
validation of each accepted worker result proves exact coverage of its pinned five-item range, so
the three distinct source-bundle-scoped ranges prove 15/15 occurrences even though local item
numbers overlap across assessments.

If any unit is `FAILED`, immediately stop Catalog, retain every terminal row and Artifact, record
only content-free failure fingerprints, and do not create another successor or retry. The closed
collect batch may already have submitted a later one of its three authorized units; it can never
submit a fourth unit or re-execute a predecessor.

## Acceptance, learning, and final proof

After an independent review of the three valid extraction pointers, stop Catalog and atomically
change only `EOM_LEGACY_ITEM_AUTOMATION_MODE` back to `AUTO_ACCEPT_AND_LEARN`. Keep the exact ordered
two-batch allowlist and all already-reviewed Content Pack, risk-policy, graph-access-policy, graph
batch-size, and analysis-retry pointers unchanged. Restart Catalog.

```bash
sudo -n systemctl stop eom-catalog-application-runner.service
AUTOMATION_STAGE_B="${RECOVERY_ROOT}/legacy-item-automation-stage-b.env"
test "$(systemctl is-active eom-catalog-application-runner.service)" = inactive
test "$(systemctl show -p Job --value eom-catalog-application-runner.service)" = ''
test "$(stat --format='%U:%G:%a' "${AUTOMATION_ENV}")" = 'root:root:644'
test ! -L "${AUTOMATION_ENV}"
AUTOMATION_BEFORE_SHA256="$(sha256sum "${AUTOMATION_ENV}" | awk '{print $1}')"
awk '
  BEGIN { mode = 0 }
  /^EOM_LEGACY_ITEM_AUTOMATION_MODE=/ {
    print "EOM_LEGACY_ITEM_AUTOMATION_MODE=AUTO_ACCEPT_AND_LEARN"; mode += 1; next
  }
  { print }
  END { if (mode != 1) exit 42 }
' "${AUTOMATION_ENV}" >"${AUTOMATION_STAGE_B}"
test "$(grep -c '^EOM_LEGACY_ITEM_AUTOMATION_MODE=AUTO_ACCEPT_AND_LEARN$' \
  "${AUTOMATION_STAGE_B}")" = 1
test "$(grep -c "^EOM_LEGACY_ITEM_AUTOMATION_BATCH_IDS=${BATCH_ALLOWLIST}$" \
  "${AUTOMATION_STAGE_B}")" = 1
test "$(grep -c '^EOM_LEGACY_ITEM_AUTOMATION_BATCH_ID=legacybatch_5455e7556c34ac3f3a577435263d06bd$' \
  "${AUTOMATION_STAGE_B}")" = 1
sudo -n test ! -e "${AUTOMATION_INCOMING}"
sudo -n test ! -L "${AUTOMATION_INCOMING}"
sudo -n install -o root -g root -m 0644 \
  "${AUTOMATION_STAGE_B}" "${AUTOMATION_INCOMING}"
test "$(sudo -n stat --format='%U:%G:%a' "${AUTOMATION_INCOMING}")" = 'root:root:644'
test "$(sha256sum "${AUTOMATION_ENV}" | awk '{print $1}')" = "${AUTOMATION_BEFORE_SHA256}"
test ! -L "${AUTOMATION_ENV}"
sudo -n mv -T "${AUTOMATION_INCOMING}" "${AUTOMATION_ENV}"
test "$(stat --format='%U:%G:%a' "${AUTOMATION_ENV}")" = 'root:root:644'
sudo -n systemctl start eom-catalog-application-runner.service
test "$(systemctl is-active eom-catalog-application-runner.service)" = active
```

Final extraction success requires:

- successor batch `SUCCEEDED`, exactly three accepted, and every other state count zero;
- the exact successor work-unit IDs
  `legacyworkunit_66854d36c201aa658ff90e7d9efb7784`,
  `legacyworkunit_c6d4cd41b1c2ce41a8985592ffbf5d7a`, and
  `legacyworkunit_dc364c9db2075d5893b1101fa0bc10ad` at ordinals 0, 1, and 2;
- one submission and one immutable result/acceptance chain per successor unit, with no retry;
- predecessor batch still `COMPLETED_WITH_GAPS`, 105 accepted and the same three historical
  failures; and
- no changed current capacity, workflow-definition, role-schema, platform-instruction, slot-06,
  EOMIS, HWPX, database-schema, port, or unrelated workload fingerprint.

Automatic learning and graph publication are separate downstream state machines. Their success is
not evidence that extraction succeeded; inspect their exact run/revision pointers independently and
coordinate their retry allowlist with the analysis-recovery runbook.

## Rollback and stop conditions

There is no destructive rollback. Before continuation creation, reinstall the protected prior
wheel set if code deployment fails. A published V2 instruction bundle or preset revision remains
immutable even if unused; never edit it or move a pointer with SQL. After continuation creation,
stop Catalog and remove only the successor batch from the staged automation allowlist if execution
must be halted. Preserve the new batch, failed/successful workflows, Jobs, receipts, and Artifacts.

Stop and escalate on any pointer/hash/state mismatch, non-adjacent instruction revision, unexpected
preset revision number, missing Artifact, changed current pointer, duplicate identity, extra failed
predecessor row, manifest drift, active retirement hold, slot collision, schema/resource mismatch,
service health failure, or new validation category. Do not weaken a check, substitute latest,
canonicalize a result, delete history, expand the owner set, or run live from this source-only
implementation task.
