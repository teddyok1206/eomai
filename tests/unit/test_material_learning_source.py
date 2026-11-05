"""Untrusted raw uploads use the current Catalog owner and never trust a suffix."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from eom_catalog_contracts.material_learning_intake import MaterialSourceUploadCommand
from eom_catalog_service.material_learning_source import (
    MaterialLearningSourceError,
    MaterialLearningSourceService,
    authorize_material_learning,
    validate_material_source_file,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import sha256_bytes
from eom_identity_service.models import OperatorRecord
from eom_operator_identity import PermissionKey

from tests.unit.test_material_learning_intake import ACTOR

PDF = b"%PDF-1.7\nsynthetic bounded bytes; parsing happens after intake\n"


def command(data=PDF, **changes):
    return MaterialSourceUploadCommand.model_validate(
        {
            "actor_id": ACTOR,
            "original_filename": "original.pdf",
            "source_format": "PDF",
            "media_type": "application/pdf",
            "content_length": len(data),
            "sha256": sha256_bytes(data),
            "rights_confirmed": True,
            "idempotency_key": "source-upload-123456789",
            **changes,
        }
    )


def staged(tmp_path: Path, data=PDF):
    path = tmp_path / "untrusted-input.hwp"
    path.write_bytes(data)
    path.chmod(0o600)
    return path


def test_native_suffix_is_not_source_format(tmp_path):
    validate_material_source_file(staged(tmp_path), command())


@pytest.mark.parametrize("mismatch", ["hash", "length", "mode", "signature", "symlink"])
def test_source_input_fails_closed(tmp_path, mismatch):
    path = staged(tmp_path)
    value = command()
    if mismatch == "hash":
        value = command(sha256="sha256:" + "0" * 64)
    elif mismatch == "length":
        value = command(content_length=len(PDF) + 1)
    elif mismatch == "mode":
        path.chmod(0o644)
    elif mismatch == "signature":
        path.write_bytes(b"not-a-pdf" + PDF[9:])
    else:
        link = tmp_path / "symlink.pdf"
        link.symlink_to(path)
        path = link
    with pytest.raises((MaterialLearningSourceError, OSError)):
        validate_material_source_file(path, value)


def authorized(monkeypatch):
    operator = SimpleNamespace(status="ACTIVE", deleted_at=None, must_change_password=False)
    now = datetime(2026, 11, 5, tzinfo=UTC)
    revision = SimpleNamespace(
        logical_artifact_id="artifact_" + "c" * 32,
        created_at=now,
    )
    session = MagicMock()
    session.get.side_effect = lambda model, *args, **kwargs: (
        operator if model is OperatorRecord else revision
    )
    permission_read = Mock(
        return_value=frozenset(
            {
                PermissionKey.CONTENT_INTAKE_READ,
                PermissionKey.WORKFLOW_START,
                PermissionKey.KNOWLEDGE_ANALYSIS_CREATE,
            }
        )
    )
    monkeypatch.setattr(
        "eom_catalog_service.material_learning_source.effective_permissions", permission_read
    )
    return session, operator, permission_read, now


@pytest.mark.parametrize("reason", ["disabled", "deleted", "password", "permissions"])
def test_real_owner_is_rechecked_not_worker_authority(monkeypatch, reason):
    session, operator, permission_read, _ = authorized(monkeypatch)
    if reason == "disabled":
        operator.status = "DISABLED"
    elif reason == "deleted":
        operator.deleted_at = datetime.now(UTC)
    elif reason == "password":
        operator.must_change_password = True
    else:
        permission_read.return_value = frozenset()
    with pytest.raises(MaterialLearningSourceError, match="PERMISSION_DENIED"):
        authorize_material_learning(session, ACTOR)


def test_publication_preserves_original_and_resolves_exact_receipt(tmp_path, monkeypatch):
    session, _, _, now = authorized(monkeypatch)
    service = MaterialLearningSourceService.__new__(MaterialLearningSourceService)
    service.settings = CatalogSettings(staging_root=tmp_path)
    context = MagicMock()
    context.__enter__.return_value = session
    service.sessions = Mock(return_value=context)
    artifacts = Mock()
    captured = {}

    def commit(**kwargs):
        captured.update(kwargs)
        captured["manifest_bytes"] = kwargs["files"][kwargs["primary_file"]].read_bytes()
        assert kwargs["files"]["source/original.pdf"] == source
        return SimpleNamespace(
            artifact_id="artifact_" + "c" * 32,
            revision_id="rev_" + "d" * 32,
        )

    artifacts.commit_file_set.side_effect = commit
    service.artifacts = artifacts
    source = staged(tmp_path)
    receipt = service.ingest(source, command())
    assert receipt.created_at == now
    assert receipt.original.sha256 == sha256_bytes(PDF)
    assert receipt.original.artifact_revision_id == receipt.manifest.artifact_revision_id
    artifacts.read_member.return_value = captured["manifest_bytes"]
    resolved = service.resolve(receipt, operator_id=ACTOR)
    assert resolved.original.sha256 == receipt.original.sha256
    artifacts.verify_member.assert_called_once()
    assert not list(tmp_path.glob("material-source.*"))
    with pytest.raises(MaterialLearningSourceError, match="OWNER_MISMATCH"):
        service.resolve(receipt, operator_id="operator_" + "2" * 32)
