from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml
from eom_catalog_contracts import (
    CATALOG_APPLICATION_SCHEMA_ROUTES,
    catalog_application_schema_route,
)
from eom_workflow import (
    WORKFLOW_ADMISSION_BY_IDENTITY,
    AgentStep,
    compile_definition,
    compile_definition_data,
    workflow_definition_is_admitted,
)
from eom_workflow.schemas import result_schema_protocol
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.models import WorkflowDefinitionRecord
from eom_workflow_runner.repository import (
    import_workflow_definition,
    reconcile_workflow_definition_admission,
)

ROOT = Path(__file__).resolve().parents[2]
ROLES = {"authoring", "image", "review", "item_management", "support"}

ADMITTED_DEFINITIONS = {
    ("generic-item-development", "1.7.0"): "generic-item-development.v1.7.yaml",
    ("knowledge-analysis", "1.0.0"): "knowledge-analysis.v1.yaml",
    ("knowledge-analysis", "4.0.0"): "knowledge-analysis.v4.yaml",
    ("knowledge-analysis", "8.0.0"): "knowledge-analysis.v8.yaml",
    ("legacy-item-extraction", "1.0.0"): "legacy-item-extraction.v1.yaml",
    (
        "legacy-item-editorial-compatibility",
        "1.0.0",
    ): "legacy-item-editorial-compatibility.v1.yaml",
}


def test_admission_matrix_matches_exact_checked_in_definition_protocols() -> None:
    assert set(WORKFLOW_ADMISSION_BY_IDENTITY) == set(ADMITTED_DEFINITIONS)
    for identity, file_name in ADMITTED_DEFINITIONS.items():
        compiled = compile_definition(ROOT / "config" / "workflows" / file_name, ROLES)
        protocols = {
            result_schema_protocol(step.result_schema)
            for step in compiled.definition.steps
            if isinstance(step, AgentStep)
        }
        admission = WORKFLOW_ADMISSION_BY_IDENTITY[identity]
        assert identity == (
            compiled.definition.definition_key,
            compiled.definition.definition_version,
        )
        assert protocols == {admission.role_protocol_version}


@pytest.mark.parametrize(
    ("definition_key", "definition_version"),
    [
        ("generic-item-development", "1.6.0"),
        ("knowledge-analysis", "2.0.0"),
        ("knowledge-analysis", "7.0.0"),
        ("unknown-workflow", "1.0.0"),
    ],
)
def test_historical_or_unknown_definition_is_not_admitted(
    definition_key: str,
    definition_version: str,
) -> None:
    assert not workflow_definition_is_admitted(definition_key, definition_version)


def test_definition_import_sets_active_from_admission_policy() -> None:
    admitted = compile_definition(
        ROOT / "config/workflows/generic-item-development.v1.7.yaml",
        ROLES,
    )
    historical = compile_definition(
        ROOT / "config/workflows/generic-item-development.v1.6.yaml",
        ROLES,
    )
    session = Mock()
    session.scalar.return_value = None

    admitted_record, admitted_created = import_workflow_definition(session, admitted)
    historical_record, historical_created = import_workflow_definition(session, historical)

    assert admitted_created and admitted_record.active is True
    assert historical_created and historical_record.active is False


def test_admitted_definition_rejects_a_different_role_protocol() -> None:
    raw = yaml.safe_load(
        (ROOT / "config/workflows/generic-item-development.v1.7.yaml").read_text(encoding="utf-8")
    )
    assert isinstance(raw, dict)
    for step in raw["steps"]:
        if step.get("type") == "agent":
            role = step["worker_role"]
            result_role = "registration" if role == "item_management" else role
            step["result_schema"] = f"{result_role}-result@6.0"
    compiled = compile_definition_data(raw, "mismatched-admission.yaml", ROLES)
    session = Mock()

    with pytest.raises(WorkflowError, match="unexpected role protocol"):
        import_workflow_definition(session, compiled)


def test_admission_reconciliation_is_complete_and_idempotent() -> None:
    records: list[WorkflowDefinitionRecord] = []
    for index, file_name in enumerate(ADMITTED_DEFINITIONS.values()):
        compiled = compile_definition(ROOT / "config" / "workflows" / file_name, ROLES)
        records.append(
            WorkflowDefinitionRecord(
                definition_id=f"wfdef_{index:032x}",
                definition_key=compiled.definition.definition_key,
                definition_version=compiled.definition.definition_version,
                schema_version=compiled.definition.schema_version,
                canonical_definition=compiled.as_dict(),
                definition_hash=compiled.sha256,
                active=False,
                source_path=compiled.source_path,
            )
        )
    historical = compile_definition(
        ROOT / "config/workflows/generic-item-development.v1.6.yaml",
        ROLES,
    )
    records.append(
        WorkflowDefinitionRecord(
            definition_id="wfdef_ffffffffffffffffffffffffffffffff",
            definition_key=historical.definition.definition_key,
            definition_version=historical.definition.definition_version,
            schema_version=historical.definition.schema_version,
            canonical_definition=historical.as_dict(),
            definition_hash=historical.sha256,
            active=True,
            source_path=historical.source_path,
        )
    )
    session = Mock()
    session.scalars.return_value = tuple(records)

    first = reconcile_workflow_definition_admission(session)
    second = reconcile_workflow_definition_admission(session)

    assert all(status.active == status.admitted for status in first)
    assert second == first
    assert records[-1].active is False
    assert session.flush.call_count == 2


def test_admission_reconciliation_fails_before_mutation_when_current_definition_missing() -> None:
    compiled = compile_definition(
        ROOT / "config/workflows/generic-item-development.v1.6.yaml",
        ROLES,
    )
    historical = WorkflowDefinitionRecord(
        definition_id="wfdef_ffffffffffffffffffffffffffffffff",
        definition_key=compiled.definition.definition_key,
        definition_version=compiled.definition.definition_version,
        schema_version=compiled.definition.schema_version,
        canonical_definition=compiled.as_dict(),
        definition_hash=compiled.sha256,
        active=True,
        source_path=compiled.source_path,
    )
    session = Mock()
    session.scalars.return_value = (historical,)

    with pytest.raises(WorkflowError, match="not imported"):
        reconcile_workflow_definition_admission(session)

    assert historical.active is True
    session.flush.assert_not_called()


def test_catalog_socket_operation_schema_routes_are_total_and_immutable() -> None:
    expected = {
        "IMPORT_REVIEWED_ITEM_CONTENT": (10, 10),
        "GET_ITEM_CONTENT": (10, 10),
        "CREATE_KNOWLEDGE_ANALYSIS": (5, 3),
        "RECONCILE_KNOWLEDGE_ANALYSIS": (3, 3),
        "REVIEW_KNOWLEDGE_ANALYSIS": (3, 3),
        "CREATE_KNOWLEDGE_ANALYSIS_BATCH": (9, 7),
        "CREATE_EVIDENCE_BUNDLE": (3, 9),
        "CREATE_ITEM_PRODUCTION_EVIDENCE": (4, 8),
    }
    assert set(CATALOG_APPLICATION_SCHEMA_ROUTES) == set(expected)
    for operation, (request_version, response_version) in expected.items():
        route = catalog_application_schema_route(operation)
        assert route.request_schema == f"catalog-application-request-v{request_version}"
        assert route.response_schema == f"catalog-application-response-v{response_version}"
    with pytest.raises(ValueError, match="unsupported"):
        catalog_application_schema_route("UNKNOWN")
    with pytest.raises(TypeError):
        CATALOG_APPLICATION_SCHEMA_ROUTES["UNKNOWN"] = catalog_application_schema_route(
            "GET_ITEM_CONTENT"
        )
