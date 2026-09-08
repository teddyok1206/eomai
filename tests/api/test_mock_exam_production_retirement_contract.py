from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_api_contracts.mock_exam_retirement import (
    MockExamProductionRetirementCommandV1,
    MockExamProductionRetirementOutcomeV1,
    MockExamProductionRetirementReceiptV1,
)
from eom_identifiers import content_sha256
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 8, 2, 3, 4, tzinfo=UTC)


def _command() -> MockExamProductionRetirementCommandV1:
    body = {
        "schema_version": "mock-exam-production-retirement-command/1.0",
        "retirement_id": "productionretire_" + "1" * 32,
        "execution_id": "productionexec_" + "2" * 32,
        "execution_revision_id": "productionexecrev_" + "3" * 32,
        "checkpoint_sha256": "sha256:" + "4" * 64,
        "production_request_id": "productionreq_" + "5" * 32,
        "production_plan_id": "productionplan_" + "6" * 32,
        "production_plan_sha256": "sha256:" + "7" * 64,
        "operator_id": "operator_" + "8" * 32,
        "reason_code": "SUPERSEDED_BY_CORRECTED_PROTOCOL",
        "authorized_at": NOW.isoformat().replace("+00:00", "Z"),
        "bindings": [
            {
                "position": position,
                "workflow_call_id": "workflowcall_" + f"{position:032x}",
                "workflow_id": "workflow_" + f"{position:032x}",
                "start_command_id": "wfcmd_" + f"{position:032x}",
                "expected_workflow_resource_version": position,
                "observed_workflow_state": "FAILED" if position == 25 else "REQUESTED",
            }
            for position in range(1, 26)
        ],
    }
    return MockExamProductionRetirementCommandV1.model_validate(
        {**body, "command_sha256": content_sha256(body)}
    )


def _receipt(
    command: MockExamProductionRetirementCommandV1,
) -> MockExamProductionRetirementReceiptV1:
    outcomes = tuple(
        MockExamProductionRetirementOutcomeV1(
            position=binding.position,
            workflow_call_id=binding.workflow_call_id,
            workflow_id=binding.workflow_id,
            expected_workflow_resource_version=binding.expected_workflow_resource_version,
            retirement_workflow_resource_version=(binding.expected_workflow_resource_version + 1),
            retirement_event_sequence=binding.expected_workflow_resource_version + 1,
            prior_workflow_state=binding.observed_workflow_state,
            disposition=(
                "UNSUCCESSFUL_TERMINAL_PRESERVED"
                if binding.observed_workflow_state == "FAILED"
                else "CANCEL_QUEUED"
            ),
            cancel_command_id=(
                None
                if binding.observed_workflow_state == "FAILED"
                else "wfcmd_cancel_" + f"{binding.position:032x}"
            ),
        )
        for binding in command.bindings
    )
    body = {
        "schema_version": "mock-exam-production-retirement-receipt/1.0",
        "retirement_id": command.retirement_id,
        "command_sha256": command.command_sha256,
        "execution_id": command.execution_id,
        "execution_revision_id": command.execution_revision_id,
        "checkpoint_sha256": command.checkpoint_sha256,
        "production_request_id": command.production_request_id,
        "production_plan_id": command.production_plan_id,
        "production_plan_sha256": command.production_plan_sha256,
        "operator_id": command.operator_id,
        "reason_code": command.reason_code,
        "retired_at": command.authorized_at.isoformat().replace("+00:00", "Z"),
        "outcomes": [outcome.model_dump(mode="json") for outcome in outcomes],
    }
    return MockExamProductionRetirementReceiptV1.model_validate(
        {**body, "receipt_sha256": content_sha256(body)}
    )


def test_retirement_command_and_receipt_match_json_schema_2020_12() -> None:
    packaged_path = (
        ROOT / "packages/api_contracts/eom_api_contracts/schemas/"
        "mock-exam-production-retirement-v1.schema.json"
    )
    canonical_path = ROOT / "schemas/api/v1/mock-exam-production-retirement-v1.schema.json"
    assert packaged_path.read_bytes() == canonical_path.read_bytes()
    schema = json.loads(packaged_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    command = _command()
    receipt = _receipt(command)

    validator.validate(command.model_dump(mode="json"))
    validator.validate(receipt.model_dump(mode="json"))


def test_retirement_contract_rejects_duplicate_cohort_and_tampered_hash() -> None:
    command = _command()
    duplicate = command.model_dump(mode="json")
    duplicate["bindings"][1]["workflow_id"] = duplicate["bindings"][0]["workflow_id"]
    duplicate["command_sha256"] = content_sha256(
        {key: value for key, value in duplicate.items() if key != "command_sha256"}
    )
    with pytest.raises(ValidationError, match="must be unique"):
        MockExamProductionRetirementCommandV1.model_validate(duplicate)

    tampered = command.model_dump(mode="json")
    tampered["bindings"][0]["expected_workflow_resource_version"] += 1
    with pytest.raises(ValidationError, match="SHA-256"):
        MockExamProductionRetirementCommandV1.model_validate(tampered)


def test_held_release_mode_uses_persistent_drop_in_and_never_restarts_workflow_runner() -> None:
    source = (ROOT / "scripts/api/deploy_release.sh").read_text(encoding="utf-8")

    assert "--install-preserve-workflow-runner-inactive" in source
    assert "zzzz-eom-workflow-runner-deployment-hold.conf" in source
    assert 'systemctl mask --runtime "${WORKFLOW_RUNNER_SERVICE}"' not in source
    assert "activate_workflow_runner_deployment_hold\n" in source
    assert "verify_workflow_runner_deployment_hold\n" in source
    assert '"${consumer}" == "${WORKFLOW_RUNNER_SERVICE}"' in source
    assert source.index("activate_workflow_runner_deployment_hold\n") < source.index(
        "install_wheels\n"
    )
    assert "workflow_runner_deployment_hold=ACTIVE" in source
    assert "--release-workflow-runner-hold" in source
    assert "workflow_runner_deployment_hold=RELEASED_INACTIVE" in source
    assert "systemctl unmask" not in source
    assert '"eom_workflow_runner/retirement_quiescence.py"' in source
    assert '"eom_workflow_runner/systemd_retirement_quiescence.py"' in source
