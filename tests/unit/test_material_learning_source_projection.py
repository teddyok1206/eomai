"""Projection staging carries the actual caller, never authority from a receipt."""

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.material_learning_intake import MaterialLearningSourceSelection
from eom_catalog_contracts.material_learning_preparation import MaterialPreparationInput
from eom_catalog_service.artifacts import VerifiedArtifactMemberStream
from eom_catalog_service.material_learning_source import MaterialLearningSourceError
from eom_catalog_service.material_learning_source_projection import MaterialSourceProjectionService
from eom_identifiers import content_sha256, sha256_bytes

from tests.unit.test_material_learning_contracts import member
from tests.unit.test_material_learning_intake import ACTOR, source_receipt
from tests.unit.test_material_learning_preparation import profile


def preparation_work():
    value = {
        "schema_version": "material-learning-preparation-input/1.0",
        "task_id": "materialtask_" + "1" * 32,
        "material_id": "material_" + "2" * 32,
        "material_revision_id": "materialrev_" + "3" * 32,
        "intake_manifest": member(
            "material/intake.json", "application/json", "material-learning/intake/1.0"
        ),
        "profile": profile(),
    }
    return MaterialPreparationInput.model_validate({**value, "input_sha256": content_sha256(value)})


def fixture(tmp_path):
    body = b"%PDF-1.7\nlocal projection fixture"
    receipt = source_receipt(actor=ACTOR)
    receipt["original"]["bytes"] = len(body)
    receipt["original"]["sha256"] = sha256_bytes(body)
    selection = MaterialLearningSourceSelection.model_validate(
        {"source_role": "MAIN", "source_upload": receipt}
    )
    service = MaterialSourceProjectionService.__new__(MaterialSourceProjectionService)
    service.settings = SimpleNamespace(staging_root=tmp_path)
    service._sources = Mock()
    service.artifacts = Mock()
    service.artifacts.open_verified_member.return_value = VerifiedArtifactMemberStream(
        BytesIO(body), len(body), sha256_bytes(body)
    )
    return service, selection, body


def test_pdf_projection_is_one_private_temporary_copy_of_same_canonical_pointer(tmp_path):
    service, selection, body = fixture(tmp_path)
    authorize = Mock()
    with service.stage(
        preparation_work(), selection, operator_id=ACTOR, authorize=authorize
    ) as staged:
        assert staged.pdf == selection.source_upload.original
        assert staged.pdf_path.read_bytes() == body
        assert staged.pdf_path.stat().st_mode & 0o777 == 0o600
        assert staged.office_catalog is None
        assert staged.conversion.conversion_kind == "IDENTITY_PDF"
    service._sources.resolve.assert_called_once_with(selection.source_upload, operator_id=ACTOR)
    assert not staged.pdf_path.exists()
    assert not list(tmp_path.iterdir())


def test_foreign_receipt_does_not_replace_actual_operator_id(tmp_path):
    service, selection, _ = fixture(tmp_path)
    actual = "operator_" + "2" * 32
    service._sources.resolve.side_effect = MaterialLearningSourceError(
        "MATERIAL_LEARNING_SOURCE_OWNER_MISMATCH"
    )
    with (
        pytest.raises(MaterialLearningSourceError, match="OWNER_MISMATCH"),
        service.stage(preparation_work(), selection, operator_id=actual, authorize=lambda: None),
    ):
        pytest.fail("foreign input materialized")
    service._sources.resolve.assert_called_once_with(selection.source_upload, operator_id=actual)
    service.artifacts.open_verified_member.assert_not_called()
