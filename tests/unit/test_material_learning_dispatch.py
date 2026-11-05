"""Private framing rejects truncated/excess/hash mismatched streams before commit."""

import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.material_learning_intake import MaterialSourceUploadReceipt
from eom_catalog_service.material_learning_dispatch import dispatch_material_learning
from eom_catalog_service.material_learning_source import MaterialLearningSourceError

from tests.unit.test_material_learning_intake import source_receipt
from tests.unit.test_material_learning_source import PDF, command


@pytest.mark.parametrize("case", ["success", "truncated", "exceeded", "hash", "denied"])
def test_raw_stream_is_bounded_and_authorized(tmp_path, case):
    source = SimpleNamespace(
        settings=SimpleNamespace(staging_root=tmp_path),
        authorize_upload=Mock(),
        ingest=Mock(return_value=MaterialSourceUploadReceipt.model_validate(source_receipt())),
    )
    request = command().model_dump(mode="json")
    body = PDF
    if case == "truncated":
        body = PDF[:-1]
    elif case == "exceeded":
        body = PDF + b"X"
    elif case == "hash":
        request["sha256"] = "sha256:" + "0" * 64
    elif case == "denied":
        source.authorize_upload.side_effect = MaterialLearningSourceError(
            "MATERIAL_LEARNING_PERMISSION_DENIED"
        )
    output = BytesIO()
    dispatch_material_learning(
        request, BytesIO(body), output, sources=source, intake=None, reads=None
    )
    reply = json.loads(output.getvalue())
    if case == "success":
        assert reply["schema_version"] == "material-learning-source-receipt/1.0"
        source.ingest.assert_called_once()
    else:
        assert reply["status"] == "ERROR"
        assert reply["error_code"].startswith("MATERIAL_LEARNING_")
        source.ingest.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_unknown_or_disabled_operation_is_not_a_permission_grant():
    for value in [
        {"operation": "RUN_SHELL"},
        {"operation": "LIST_MATERIAL_LEARNING_RUNS", "actor_id": "operator_" + "1" * 32},
    ]:
        output = BytesIO()
        dispatch_material_learning(value, BytesIO(), output, sources=None, intake=None, reads=None)
        assert json.loads(output.getvalue())["status"] == "ERROR"
