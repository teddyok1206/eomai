from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_historical_protocol_schemas_remain_byte_pinned() -> None:
    expected = dict(
        (
            (
                "schemas/catalog-application/catalog-application-request-v10.schema.json",
                "fc89d31db0aa51d97c991187b5553f82954b497d5cbebc8edc54b908b1484366",
            ),
            (
                "schemas/catalog-application/catalog-application-response-v10.schema.json",
                "d24f2d2ca3fb3fd593f087c3658d17be45d00863df94ff8b6ada867ba0d92308",
            ),
            (
                "schemas/api/v1/production-item-candidate-v1.schema.json",
                "6b5f27e7d275fc77e976d7445f40080ed3fb4145bfa280ca8356856eb12664f4",
            ),
            (
                "schemas/api/v1/mock-exam-production-execution-v1.schema.json",
                "aafa7465142ae1fec36082b2a167a21a099dcd7c3379ad4224be03bab235ab80",
            ),
            (
                "schemas/api/v1/mock-exam-review-eligibility-v1.schema.json",
                "1bf1e2299d838c526983880ce85a3fd38add3fc494edbdd2cffabaf194c366e0",
            ),
            (
                "schemas/api/v1/workflow-start-v1.schema.json",
                "0123a95c69b02fdb6f3ad877bf824782d25db07dc500ced8935823209a06ba6f",
            ),
            (
                "schemas/assessment-assembly/mock-exam-item-review-decision-v1.schema.json",
                "5f0934dfb60d8daf03f32aee080ea0f75b5930553e7bc697a592954552e9fd80",
            ),
            (
                "schemas/assessment-assembly/mock-exam-item-review-publication-result-v1.schema.json",
                "7c5925cea23b97b882ed12776c993db611fabac35b5056c41833f727eb989061",
            ),
            (
                "schemas/assessment-assembly/mock-exam-review-eligibility-result-v1.schema.json",
                "5d8ce21540dbda8f38cda3f008e3379646e06505c6435e95b16095f1a6e8f7c2",
            ),
            (
                "schemas/api/v1/hwpx.schema.json",
                "f6e9379e39fede724a6c19c450eec036e9a5a09ae5a90f9e6ae06aefea3dbabd",
            ),
        )
    )
    assert {name: _sha256(ROOT / name) for name in expected} == expected

    api_names = (
        "production-item-candidate-v1.schema.json",
        "mock-exam-production-execution-v1.schema.json",
        "mock-exam-review-eligibility-v1.schema.json",
        "workflow-start-v1.schema.json",
    )
    for name in api_names:
        assert (ROOT / "schemas/api/v1" / name).read_bytes() == (
            ROOT / "packages/api_contracts/eom_api_contracts/schemas" / name
        ).read_bytes()

    catalog_names = (
        "assessment-assembly/mock-exam-item-review-decision-v1.schema.json",
        "assessment-assembly/mock-exam-item-review-publication-result-v1.schema.json",
        "assessment-assembly/mock-exam-review-eligibility-result-v1.schema.json",
        "catalog-application/catalog-application-request-v10.schema.json",
        "catalog-application/catalog-application-response-v10.schema.json",
    )
    for name in catalog_names:
        assert (ROOT / "schemas" / name).read_bytes() == (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources" / name
        ).read_bytes()


def test_additive_successor_schema_mirrors_are_byte_exact() -> None:
    api_names = (
        "production-item-candidate-v2.schema.json",
        "mock-exam-production-execution-v2.schema.json",
        "mock-exam-review-eligibility-v2.schema.json",
        "hwpx-v2.schema.json",
    )
    for name in api_names:
        assert (ROOT / "schemas/api/v1" / name).read_bytes() == (
            ROOT / "packages/api_contracts/eom_api_contracts/schemas" / name
        ).read_bytes()

    catalog_names = (
        "assessment-assembly/mock-exam-item-review-decision-v2.schema.json",
        "assessment-assembly/mock-exam-item-review-publication-result-v2.schema.json",
        "assessment-assembly/mock-exam-review-eligibility-result-v2.schema.json",
        "catalog-application/catalog-application-request-v12.schema.json",
        "catalog-application/catalog-application-response-v12.schema.json",
        "catalog-application/catalog-application-request-v13.schema.json",
        "catalog-application/catalog-application-response-v13.schema.json",
    )
    for name in catalog_names:
        assert (ROOT / "schemas" / name).read_bytes() == (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources" / name
        ).read_bytes()


def test_successor_ids_are_distinct_and_workflow_start_keeps_plan_v1_slot() -> None:
    candidate = json.loads(
        (ROOT / "schemas/api/v1/production-item-candidate-v2.schema.json").read_text()
    )
    execution = json.loads(
        (ROOT / "schemas/api/v1/mock-exam-production-execution-v2.schema.json").read_text()
    )
    hwpx = json.loads((ROOT / "schemas/api/v1/hwpx-v2.schema.json").read_text())
    workflow_start = json.loads((ROOT / "schemas/api/v1/workflow-start-v1.schema.json").read_text())
    assert candidate["properties"]["schema_version"]["const"].endswith("/2.0")
    assert execution["properties"]["schema_version"]["const"].endswith("/2.0")
    assert hwpx["$id"] == "urn:eom:schema:api:v2:hwpx"
    slot_ref = workflow_start["$defs"]["content_team_item_brief_request_v3"]["properties"][
        "mock_exam_slot"
    ]["oneOf"][1]["$ref"]
    assert slot_ref == (
        "eom://schemas/assessment-assembly/mock-exam-production-plan/1.0#/$defs/mock_exam_slot"
    )
