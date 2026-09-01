from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_catalog_contracts import AssessmentArtifactMemberPointer
from eom_catalog_service.item_origin_service import ItemOriginService
from eom_catalog_service.legacy_assessment_registry import (
    LegacyAssessmentRegistry,
    LegacyAssessmentRegistryError,
)
from eom_identifiers import content_sha256


class _ArtifactReader:
    def __init__(self, raw: bytes) -> None:
        self.raw = raw
        self.calls = 0

    def read_member(self, **_kwargs: object) -> bytes:
        self.calls += 1
        return self.raw


def _pointer(*, schema_ref: str = "eom://schemas/legacy-assessment/test/1.0") -> Any:
    return AssessmentArtifactMemberPointer.model_validate(
        {
            "artifact_id": "artifact_" + "1" * 32,
            "artifact_revision_id": "rev_" + "1" * 32,
            "member_path": "evidence.json",
            "schema_ref": schema_ref,
            "media_type": "application/json",
            "sha256": "sha256:" + "1" * 64,
        }
    )


def _registry_with(raw: bytes) -> tuple[LegacyAssessmentRegistry, _ArtifactReader]:
    reader = _ArtifactReader(raw)
    registry = object.__new__(LegacyAssessmentRegistry)
    registry.artifacts = cast(Any, reader)
    return registry, reader


def test_json_evidence_is_read_once_and_rejects_duplicate_keys() -> None:
    registry, reader = _registry_with(b'{"schema_version":"x","schema_version":"y"}')
    with pytest.raises(LegacyAssessmentRegistryError) as error:
        registry._load_member_json(_pointer())
    assert error.value.code == "LEGACY_ASSESSMENT_ARTIFACT_INVALID"
    assert reader.calls == 1


def test_control_artifact_requires_exact_schema_and_json_media_type() -> None:
    with pytest.raises(LegacyAssessmentRegistryError) as error:
        LegacyAssessmentRegistry._require_control_artifact_contract(
            _pointer(),
            schema_ref="eom://schemas/legacy-assessment/expected/1.0",
        )
    assert error.value.code == "LEGACY_ASSESSMENT_ARTIFACT_INVALID"


def test_item_provenance_evidence_hash_is_canonical_and_path_free() -> None:
    record = SimpleNamespace(
        item_provenance_id="provenance_" + "1" * 32,
        item_revision_id="itemrev_" + "1" * 32,
        provenance_type="MANUAL_EXTERNAL_SOURCE",
        source_key="legacy.sample",
        source_reference="reviewed-source",
        source_intake_batch_id="intake_" + "1" * 32,
        source_file_id="intakefile_" + "1" * 32,
        source_artifact_id="artifact_" + "1" * 32,
        source_artifact_revision_id="rev_" + "1" * 32,
        source_sha256="sha256:" + "1" * 64,
        notes=None,
    )
    expected = content_sha256(
        {
            "item_provenance_id": record.item_provenance_id,
            "item_revision_id": record.item_revision_id,
            "provenance_type": record.provenance_type,
            "source_key": record.source_key,
            "source_reference": record.source_reference,
            "source_intake_batch_id": record.source_intake_batch_id,
            "source_file_id": record.source_file_id,
            "source_artifact_id": record.source_artifact_id,
            "source_artifact_revision_id": record.source_artifact_revision_id,
            "source_sha256": record.source_sha256,
            "notes": None,
        }
    )
    assert ItemOriginService._item_provenance_sha256(cast(Any, record)) == expected


def test_registry_models_do_not_accept_storage_paths_as_identity() -> None:
    pointer = _pointer()
    assert set(pointer.model_dump()) == {
        "artifact_id",
        "artifact_revision_id",
        "member_path",
        "schema_ref",
        "media_type",
        "sha256",
    }
    assert "nas_path" not in pointer.model_dump()
