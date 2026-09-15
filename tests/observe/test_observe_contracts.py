from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

pytest.importorskip("eom_observe")

from eom_observe.settings import load_settings
from eom_observe_contracts import NodeStatus, validate_contract

from tests.observe.helpers import operational_overview, snapshot


def test_snapshot_json_schema_validation() -> None:
    value = snapshot().model_dump(mode="json")
    validate_contract("snapshot", value)


def test_snapshot_schema_rejects_additional_property() -> None:
    value = snapshot().model_dump(mode="json")
    value["secret"] = "must fail"
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("snapshot", value)


def test_operational_overview_schema_and_package_mirror() -> None:
    value = operational_overview().model_dump(mode="json")
    validate_contract("operational-overview", value)
    assert (
        Path("schemas/observe/observe-operational-overview.schema.json").read_bytes()
        == Path(
            "packages/observe_contracts/eom_observe_contracts/schemas/"
            "observe-operational-overview.schema.json"
        ).read_bytes()
    )


def test_operational_overview_rejects_incomplete_inconsistent_or_unsorted_attention() -> None:
    value = operational_overview().model_dump(mode="json")
    value["attention"][0]["job_id"] = None
    with pytest.raises(ValidationError):
        type(operational_overview()).model_validate(value)
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("operational-overview", value)

    value = operational_overview().model_dump(mode="json")
    value["attention"][1]["command_id"] = "wfcmd_12345678"
    with pytest.raises(ValidationError):
        type(operational_overview()).model_validate(value)
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("operational-overview", value)

    value = operational_overview().model_dump(mode="json")
    value["attention"][0]["state"] = "PROCESSING"
    with pytest.raises(ValidationError):
        type(operational_overview()).model_validate(value)
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("operational-overview", value)

    value = operational_overview().model_dump(mode="json")
    value["attention"].reverse()
    with pytest.raises(ValidationError):
        type(operational_overview()).model_validate(value)


@pytest.mark.parametrize(
    ("classification", "identities"),
    [
        ("QUIESCENT_NONTERMINAL_WORKFLOW", {"workflow_id": "workflow_12345678"}),
        (
            "EXPIRED_WORKFLOW_COMMAND_CLAIM",
            {"workflow_id": "workflow_12345678", "command_id": "wfcmd_12345678"},
        ),
        (
            "EXPIRED_WORKER_LEASE",
            {
                "workflow_id": "workflow_12345678",
                "job_id": "job_12345678",
                "lease_id": "workerlease_12345678",
            },
        ),
        ("EXPIRED_API_IDEMPOTENCY_CLAIM", {"api_idempotency_record_id": "apiidem_12345678"}),
        ("RECENT_FAILED_WORKFLOW", {"workflow_id": "workflow_12345678"}),
        ("RECENT_FAILED_JOB", {"job_id": "job_12345678"}),
    ],
)
def test_operational_overview_accepts_each_exact_attention_identity(
    classification: str, identities: dict[str, str]
) -> None:
    value = operational_overview().model_dump(mode="json")
    item = {
        "classification": classification,
        "workflow_id": None,
        "job_id": None,
        "command_id": None,
        "lease_id": None,
        "api_idempotency_record_id": None,
        "state": {
            "QUIESCENT_NONTERMINAL_WORKFLOW": "RUNNING",
            "EXPIRED_WORKFLOW_COMMAND_CLAIM": "PROCESSING",
            "EXPIRED_WORKER_LEASE": "ACTIVE",
            "EXPIRED_API_IDEMPOTENCY_CLAIM": "PROCESSING",
            "RECENT_FAILED_WORKFLOW": "FAILED",
            "RECENT_FAILED_JOB": "FAILED",
        }[classification],
        "error_code": None,
        "observed_at": value["generated_at"],
    }
    item.update(identities)
    value["attention"] = [item]
    type(operational_overview()).model_validate(value)
    validate_contract("operational-overview", value)


def test_node_status_enum() -> None:
    assert {status.value for status in NodeStatus} >= {"IDLE", "RUNNING", "UNAVAILABLE"}


def test_config_validation_accepts_example() -> None:
    settings = load_settings(Path("config/observe.example.yaml"))
    assert settings.server.host == "127.0.0.1"
    assert settings.server.port == 8780


def test_config_rejects_non_loopback(tmp_path: Path) -> None:
    value = yaml.safe_load(Path("config/observe.example.yaml").read_text(encoding="utf-8"))
    value["server"]["host"] = "0.0.0.0"
    target = tmp_path / "observe.yaml"
    target.write_text(yaml.safe_dump(value), encoding="utf-8")
    with pytest.raises(RuntimeError):
        load_settings(target)


def test_pydantic_contract_rejects_unknown_status() -> None:
    value = snapshot().nodes[0].model_dump()
    value["status"] = "MUTATING"
    with pytest.raises(ValidationError):
        type(snapshot().nodes[0]).model_validate(value)
