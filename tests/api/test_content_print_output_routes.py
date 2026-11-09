"""The output selection reaches the existing Catalog owner under actual identity."""

import json
from unittest.mock import Mock

from eom_api.services.catalog_application_client import CatalogApplicationClient
from eom_catalog_contracts.content_print_commands import (
    ContentPrintMutationResult,
    RecordContentPrintWithOutput,
)
from eom_catalog_contracts.content_print_record import ContentPrintRecordV1
from eom_catalog_service.content_planning_dispatch import dispatch_content_planning
from eom_identifiers import content_sha256

from tests.api.test_content_planning_routes import planning_client as planning_client
from tests.api.test_hwpx_endpoints import OPERATOR_ID
from tests.unit.content_planning_fixtures import SHA, identifier
from tests.unit.test_content_planning_read_contracts import print_example
from tests.unit.test_curated_document_assembly_resolution import _actor


def example():
    previous, response = print_example()
    command = RecordContentPrintWithOutput.model_validate(
        {
            **previous.model_dump(mode="json"),
            "command_kind": "RECORD_PRINT_WITH_OUTPUT",
            "output_build_id": identifier("hwpxbuild"),
            "output_sha256": SHA,
        }
    )
    value = response.record.model_dump(mode="json", exclude={"record_sha256"})
    value["output"] = {
        "hwpx_build_id": command.output_build_id,
        "scope_sha256": response.record.scope.scope_sha256,
        "artifact_id": identifier("artifact"),
        "artifact_revision_id": identifier("rev"),
        "artifact_sha256": SHA,
        "output_sha256": SHA,
    }
    result = ContentPrintMutationResult(
        disposition="RECORDED",
        replayed=False,
        record=ContentPrintRecordV1.model_validate(
            {**value, "record_sha256": content_sha256(value)}
        ),
    )
    return command, result


def test_output_command_uses_existing_route_and_actual_operator(planning_client):
    client, catalog, _state = planning_client
    command, result = example()
    catalog.record_content_print.return_value = result
    response = client.post(
        "/api/v1/content-planning/prints",
        json=command.model_dump(mode="json"),
        headers={"Idempotency-Key": "explicit-print-output-1234"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"] == result.model_dump(mode="json")
    call = catalog.record_content_print.call_args
    assert call.args[0] == command
    assert call.kwargs["actor"].operator_id == OPERATOR_ID
    assert call.kwargs["idempotency_key"] == "explicit-print-output-1234"


def test_output_command_rpc_is_closed_and_preserves_exact_output(monkeypatch):
    command, result = example()
    service = Mock()
    service.prints.execute.return_value = result
    client = CatalogApplicationClient()
    monkeypatch.setattr(
        client,
        "_raw_request",
        lambda value, **_: json.loads(dispatch_content_planning(service, value)),
    )
    response = client.record_content_print(
        command, actor=_actor(), idempotency_key="explicit-print-output-1234"
    )
    assert response == result
    assert service.prints.execute.call_args.args[0] == command
    assert not service.prints.execute.call_args.kwargs["actor"].permissions
