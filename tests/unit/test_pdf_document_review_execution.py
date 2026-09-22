from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator.control_models import (
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    ResolvedExecutionPlanRecord,
    ResolvedExecutionPlanStepRecord,
)
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.execution_resolver import resolve_pdf_document_review_plan
from eom_workflow import (
    ExecutionPresetRevision,
    PdfReviewDocumentPointer,
    ResolvedExecutionPlanV13,
    build_pdf_document_review_request,
)

NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)


def _document() -> PdfReviewDocumentPointer:
    artifact_id = "artifact_" + "1" * 32
    revision_id = "rev_" + "2" * 32
    return PdfReviewDocumentPointer.model_validate(
        {
            "document_id": "document_" + "3" * 32,
            "document_revision_id": "documentrev_" + "4" * 32,
            "original_filename": "review.pdf",
            "source_pdf": {
                "artifact_id": artifact_id,
                "artifact_revision_id": revision_id,
                "member_path": "source/original.pdf",
                "sha256": "sha256:" + "5" * 64,
                "schema_ref": "eom://schemas/document-review/pdf-source/1.0",
                "media_type": "application/pdf",
                "content_length": 4096,
            },
            "page_count": 1,
            "pages": [
                {
                    "page_number": 1,
                    "width_px": 1200,
                    "height_px": 1800,
                    "rotation_degrees": 0,
                    "page_image": {
                        "artifact_id": artifact_id,
                        "artifact_revision_id": revision_id,
                        "member_path": "pages/page-0001.png",
                        "sha256": "sha256:" + "6" * 64,
                        "schema_ref": "eom://schemas/document-review/pdf-page-render/1.0",
                        "media_type": "image/png",
                        "content_length": 2048,
                    },
                    "text_layer": None,
                }
            ],
        }
    )


def _instruction_pointer() -> dict[str, object]:
    return {
        "bundle_id": "instrbundle_" + "7" * 32,
        "bundle_revision_id": "instrrev_" + "8" * 32,
        "manifest_artifact": {
            "artifact_id": "artifact_" + "9" * 32,
            "artifact_revision_id": "rev_" + "a" * 32,
            "sha256": "sha256:" + "b" * 64,
            "schema_ref": "eom://schemas/workflow/bundle-manifest/1.0",
            "media_type": "application/json",
            "logical_name": "manifest.json",
        },
        "manifest_sha256": "sha256:" + "c" * 64,
    }


def _preset_document() -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": "execution-preset-revision/1.0",
        "preset_id": "execpreset_" + "d" * 32,
        "preset_revision_id": "execpresetrev_" + "e" * 32,
        "revision_number": 1,
        "state": "RELEASED",
        "display_name": "PDF 교육 문서 검토",
        "description": "불변 PDF를 page anchor 기반으로 검토한다.",
        "role_policies": [
            {
                "role": "support",
                "model_candidates": [{"model": "gpt-5.6-terra", "reasoning_effort": "xhigh"}],
                "instruction_bundle": _instruction_pointer(),
                "reference_bundle": None,
                "worker_pool_key": "customer-support",
                "timeout_seconds": 3600,
                "sandbox": "read-only",
                "network": "disabled",
            }
        ],
        "capacity_policy_revision_id": "capacityrev_" + "f" * 32,
        "general_knowledge_policy": "ALLOW_WITH_PROVENANCE",
        "compatible_workflow_protocols": ["workflow-role/1.25.0"],
        "content_sha256": "sha256:" + "0" * 64,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    document["content_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "content_sha256"}
    )
    return ExecutionPresetRevision.model_validate(document).model_dump(mode="json")


class FakeSession:
    def __init__(self, *, preset_document: dict[str, object]) -> None:
        self.preset_logical = SimpleNamespace(
            preset_id=preset_document["preset_id"],
            preset_key="pdf-document-review",
            state="ACTIVE",
            current_revision_id=preset_document["preset_revision_id"],
        )
        self.preset_revision = SimpleNamespace(
            preset_id=preset_document["preset_id"],
            state="RELEASED",
            compatible_workflow_protocols=("workflow-role/1.25.0",),
            content_sha256=preset_document["content_sha256"],
            canonical_document=preset_document,
        )
        self.plan: ResolvedExecutionPlanRecord | None = None
        self.steps: list[ResolvedExecutionPlanStepRecord] = []

    def scalar(self, statement: Any) -> object | None:
        entity = statement.column_descriptions[0].get("entity")
        if entity is ResolvedExecutionPlanRecord:
            return self.plan
        if entity is ExecutionPresetRecord:
            return self.preset_logical
        raise AssertionError(f"unexpected scalar entity: {entity}")

    def get(self, model: type[object], identity: str) -> object | None:
        if model is ExecutionPresetRevisionRecord:
            assert identity == self.preset_logical.current_revision_id
            return self.preset_revision
        return None

    def add(self, value: object) -> None:
        if isinstance(value, ResolvedExecutionPlanRecord):
            self.plan = value
        elif isinstance(value, ResolvedExecutionPlanStepRecord):
            self.steps.append(value)
        else:
            raise AssertionError(f"unexpected added record: {type(value)}")

    def flush(self) -> None:
        return None


def test_pdf_review_plan_resolution_is_exact_and_idempotent() -> None:
    session = FakeSession(preset_document=_preset_document())
    request = build_pdf_document_review_request(
        document=_document(),
        preset_key="MOCK_EXAM",
        additional_guidance="과학적 오류와 편집 위치를 함께 확인해 주세요.",
    )

    first = resolve_pdf_document_review_plan(
        session,  # type: ignore[arg-type]
        workflow_id="workflow_" + "1" * 32,
        workflow_definition_version="1.0.0",
        workflow_definition_sha256="sha256:" + "2" * 64,
        workflow_role_schema_version="workflow-role/1.25.0",
        review_request=request,
        resolved_at=NOW,
    )
    replay = resolve_pdf_document_review_plan(
        session,  # type: ignore[arg-type]
        workflow_id=first.workflow_id,
        workflow_definition_version="1.0.0",
        workflow_definition_sha256="sha256:" + "2" * 64,
        workflow_role_schema_version="workflow-role/1.25.0",
        review_request=request,
        resolved_at=NOW,
    )

    assert isinstance(first, ResolvedExecutionPlanV13)
    assert replay == first
    assert first.document == request.document
    assert len(session.steps) == 1
    assert session.steps[0].worker_pool_key == "customer-support"


def test_pdf_review_plan_replay_rejects_changed_request_binding() -> None:
    session = FakeSession(preset_document=_preset_document())
    request = build_pdf_document_review_request(
        document=_document(),
        preset_key="PROBLEM_SET",
        additional_guidance=None,
    )
    resolve_pdf_document_review_plan(
        session,  # type: ignore[arg-type]
        workflow_id="workflow_" + "1" * 32,
        workflow_definition_version="1.0.0",
        workflow_definition_sha256="sha256:" + "2" * 64,
        workflow_role_schema_version="workflow-role/1.25.0",
        review_request=request,
        resolved_at=NOW,
    )
    changed = build_pdf_document_review_request(
        document=_document(),
        preset_key="PROBLEM_SET",
        additional_guidance="표현 오류를 추가로 확인해 주세요.",
    )

    with pytest.raises(ControlPlaneError) as captured:
        resolve_pdf_document_review_plan(
            session,  # type: ignore[arg-type]
            workflow_id="workflow_" + "1" * 32,
            workflow_definition_version="1.0.0",
            workflow_definition_sha256="sha256:" + "2" * 64,
            workflow_role_schema_version="workflow-role/1.25.0",
            review_request=changed,
            resolved_at=NOW,
        )

    assert captured.value.code == "CONTROL_PLAN_BINDING_MISMATCH"
