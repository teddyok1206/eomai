from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from eom_catalog_contracts import AssessmentItemContent
from eom_catalog_service.artifacts import CatalogArtifact
from eom_catalog_service.item_content_import import StructuredItemContentImportService
from eom_catalog_service.models import (
    ItemComponentRecord,
    ItemMetadataSnapshotRecord,
    ItemProvenanceRecord,
    ItemRecord,
    ItemRevisionRecord,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_workflow_runner.models import WorkflowInstanceRecord

from tests.unit.test_assessment_item_content import item_content
from tests.unit.test_catalog_staging import _settings


class FakeSession:
    def __init__(self, values: dict[type[object], object]) -> None:
        self.values = values
        self.scalar_results: list[object | None] = [None, values[ItemMetadataSnapshotRecord]]
        self.scalars_results: list[tuple[object, ...]] = [
            values[ItemComponentRecord],  # type: ignore[list-item]
            values[ItemProvenanceRecord],  # type: ignore[list-item]
        ]

    def __enter__(self) -> FakeSession:
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def get(self, model: type[object], _identifier: str) -> object | None:
        return self.values.get(model)

    def scalar(self, _statement: object) -> object | None:
        return self.scalar_results.pop(0)

    def scalars(self, _statement: object) -> tuple[object, ...]:
        return self.scalars_results.pop(0)


class FakeArtifacts:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def commit_file_set(self, **values: Any) -> CatalogArtifact:
        path = values["files"]["assessment-item-content.json"]
        assert isinstance(path, Path)
        assert path.read_bytes() == canonical_json_bytes(item_content())
        self.calls.append(values)
        return CatalogArtifact(
            job_id="job_" + "1" * 32,
            artifact_id="artifact_" + "2" * 32,
            revision_id="rev_" + "3" * 32,
            content_hash=content_sha256(item_content()),
            manifest_hash="sha256:" + "4" * 64,
            content_bytes=path.stat().st_size,
            nas_path="/TEST_ONLY/artifact",
            manifest={
                "primary_file": "assessment-item-content.json",
                "files": [
                    {
                        "file_name": "assessment-item-content.json",
                        "sha256": content_sha256(item_content()),
                    }
                ],
            },
        )


class FakeRegistry:
    def __init__(self) -> None:
        self.request: object | None = None

    def register(self, request: object) -> SimpleNamespace:
        self.request = request
        return SimpleNamespace(
            item_id="item_" + "5" * 32,
            item_revision_id="itemrev_" + "6" * 32,
            lock_version=1,
        )


def test_reviewed_import_preserves_base_pointers_and_replaces_only_item_content(
    tmp_path: Path,
) -> None:
    base_revision_id = "itemrev_" + "7" * 32
    values: dict[type[object], object] = {
        ItemRevisionRecord: SimpleNamespace(
            item_revision_id=base_revision_id,
            item_id="item_" + "5" * 32,
            lock_version=1,
            revision_state="APPROVED",
            content_pack_release_id="packrel_" + "8" * 32,
            workflow_id="workflow_" + "9" * 32,
            workflow_definition_version="1.1.0",
            source_workflow_step_run_id="steprun_" + "a" * 32,
            item_type_key="multiple-choice",
            primary_taxonomy_ref="taxonomy:science",
            difficulty_band="medium",
            metadata_json={"subject": "science"},
        ),
        ItemRecord: SimpleNamespace(current_revision_id=base_revision_id),
        WorkflowInstanceRecord: SimpleNamespace(definition_key="generic-item-development"),
        ItemMetadataSnapshotRecord: SimpleNamespace(
            tag_keys=["reviewed"],
            estimated_time_seconds=120,
            schema_ref="eom://schemas/item-metadata/1.0",
        ),
        ItemComponentRecord: (
            SimpleNamespace(
                component_type="SOURCE_REFERENCE",
                ordinal=0,
                schema_ref="eom.source/1.0",
                media_type="application/json",
                artifact_id="artifact_" + "b" * 32,
                artifact_revision_id="rev_" + "c" * 32,
                sha256="sha256:" + "d" * 64,
                logical_name="source.json",
                required=True,
                metadata_json={"preserved": True},
            ),
            SimpleNamespace(
                component_type="ITEM_CONTENT",
                ordinal=0,
                schema_ref="eom.assessment.item-content/1.0",
                media_type="application/json",
                artifact_id="artifact_" + "e" * 32,
                artifact_revision_id="rev_" + "f" * 32,
                sha256="sha256:" + "0" * 64,
                logical_name="old-content.json",
                required=True,
                metadata_json={},
            ),
        ),
        ItemProvenanceRecord: (SimpleNamespace(source_intake_batch_id="intake_" + "1" * 32),),
    }
    session = FakeSession(values)
    service = object.__new__(StructuredItemContentImportService)
    service.settings = _settings(tmp_path)
    service.sessions = lambda: session
    artifacts = FakeArtifacts()
    registry = FakeRegistry()
    service.artifacts = artifacts
    service.registry = registry

    result = service.import_reviewed(
        base_revision_id,
        AssessmentItemContent.model_validate(item_content()),
        reviewed_by="operator_" + "2" * 32,
        review_reason="구조화 문항의 모든 의미 요소와 source pointer를 검토했습니다.",
        expected_version=1,
    )

    assert result.item_revision_id == "itemrev_" + "6" * 32
    assert len(artifacts.calls) == 1
    request = registry.request
    assert request is not None
    assert request.base_revision_id == base_revision_id  # type: ignore[attr-defined]
    assert request.source_intake_batch_ids == ("intake_" + "1" * 32,)  # type: ignore[attr-defined]
    positions = {
        (component.component_type, component.ordinal): component
        for component in request.components  # type: ignore[attr-defined]
    }
    assert positions[("SOURCE_REFERENCE", 0)].metadata == {"preserved": True}
    content_pointer = positions[("ITEM_CONTENT", 0)]
    assert content_pointer.artifact_revision_id == "rev_" + "3" * 32
    assert content_pointer.metadata["base_revision_id"] == base_revision_id
    assert len(request.registration_key) <= 200  # type: ignore[attr-defined]
