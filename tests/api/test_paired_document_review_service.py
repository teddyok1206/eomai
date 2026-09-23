from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from eom_api.errors import ApiError
from eom_api.pdf_document_review_models import (
    DocumentReviewSetMemberRecord,
    DocumentReviewSetRecord,
)
from eom_api.services.paired_document_review_service import (
    PairedDocumentReviewApplicationService,
)
from eom_api.services.pdf_upload_stager import StagedPdfUpload
from eom_api_contracts import CreateDocumentReviewSetRequest, DocumentReviewSetSourceRequest
from eom_catalog_contracts import (
    OfficeDocumentReviewConversionIdentity,
    OfficeDocumentReviewMemberPointer,
    OfficeDocumentReviewSourcePointer,
    PdfReviewArtifactMemberPointer,
    PdfReviewDocumentPointer,
    PdfReviewPagePointer,
)
from eom_identity_service.models import OperatorRecord
from eom_operator_identity import ActorContext, ActorSource, ActorType, PermissionKey
from eom_orchestrator.database import build_engine, build_session_factory
from eom_workflow import PairedReviewAnchor, PairedReviewCrossDocumentCheck
from eom_workflow_runner import models as workflow_models  # noqa: F401
from sqlalchemy import Table, create_engine, func, select

NOW = datetime(2026, 9, 22, 9, 0, tzinfo=UTC)
OPERATOR_ID = "operator_" + "1" * 32


def _sha(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _source(role: str, source: Path, **values: Any) -> OfficeDocumentReviewSourcePointer:
    digit = "2" if role == "QUESTION" else "3"
    artifact_id = "artifact_" + digit * 32
    artifact_revision_id = "rev_" + digit * 32
    source_pointer = PdfReviewArtifactMemberPointer(
        artifact_id=artifact_id,
        artifact_revision_id=artifact_revision_id,
        member_path="source/original.pdf",
        sha256=_sha(source.read_bytes()),
        content_length=source.stat().st_size,
        media_type="application/pdf",
        schema_ref="eom://schemas/document-review/pdf-source/1.0",
    )
    page_image = PdfReviewArtifactMemberPointer(
        artifact_id=artifact_id,
        artifact_revision_id=artifact_revision_id,
        member_path="pages/page-0001.png",
        sha256="sha256:" + digit * 64,
        content_length=1024,
        media_type="image/png",
        schema_ref="eom://schemas/document-review/pdf-page-render/1.0",
    )
    document = PdfReviewDocumentPointer(
        document_id="document_" + digit * 32,
        document_revision_id="documentrev_" + digit * 32,
        original_filename=f"{role.lower()}.pdf",
        source_pdf=source_pointer,
        page_count=1,
        pages=(
            PdfReviewPagePointer(
                page_number=1,
                width_px=1200,
                height_px=1600,
                rotation_degrees=0,
                page_image=page_image,
                text_layer=None,
            ),
        ),
    )
    manifest = OfficeDocumentReviewMemberPointer(
        artifact_id=artifact_id,
        artifact_revision_id=artifact_revision_id,
        member_path="manifest.json",
        sha256="sha256:" + ("4" if role == "QUESTION" else "5") * 64,
        content_length=512,
        media_type="application/json",
        schema_ref="eom://schemas/document-review/document-review-intake-manifest/2.0",
    )
    return OfficeDocumentReviewSourcePointer(
        document_id=document.document_id,
        document_revision_id=document.document_revision_id,
        original_filename=values["original_filename"],
        source_format="PDF",
        original_source=OfficeDocumentReviewMemberPointer.model_validate(
            source_pointer.model_dump(mode="json")
        ),
        review_document=document,
        editable_hwpx=None,
        intake_manifest=manifest,
        conversion=OfficeDocumentReviewConversionIdentity(
            conversion_kind="IDENTITY_PDF",
            review_pdf_sha256=source_pointer.sha256,
            libreoffice_version=None,
            libreoffice_sha256=None,
            h2orestart_sha256=None,
        ),
    )


class FakeCatalog:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def ingest_office_document_review_source(self, source: Path, **values: Any) -> Any:
        role = "QUESTION" if "QUESTION" in values["idempotency_key"] else "SOLUTION"
        self.calls.append({"role": role, "source": source, **values})
        return _source(role, source, **values)


class FakeCommands:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def start_paired_document_review(self, request: object, actor: object, **values: Any) -> Any:
        self.calls.append({"request": request, "actor": actor, **values})
        return "wfcmd_" + "8" * 32, "workflow_" + "9" * 32, 1


def _actor() -> ActorContext:
    return ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id=OPERATOR_ID,
        session_id="apisession_" + "a" * 32,
        request_id="req_" + "b" * 32,
        authentication_time=NOW,
        permissions=frozenset({PermissionKey.WORKFLOW_START}),
        source=ActorSource.APPLICATION_API,
    )


def _service() -> tuple[PairedDocumentReviewApplicationService, Any, FakeCatalog, FakeCommands]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    cast(Table, DocumentReviewSetRecord.__table__).create(engine)
    cast(Table, DocumentReviewSetMemberRecord.__table__).create(engine)
    catalog = FakeCatalog()
    commands = FakeCommands()
    service = PairedDocumentReviewApplicationService(
        engine,
        catalog=catalog,  # type: ignore[arg-type]
        commands=commands,  # type: ignore[arg-type]
        intent_ttl_seconds=86_400,
        processing_lease_seconds=300,
    )
    return service, engine, catalog, commands


def _create(service: PairedDocumentReviewApplicationService) -> str:
    value = service.create_set(
        CreateDocumentReviewSetRequest(
            documents=(
                DocumentReviewSetSourceRequest(
                    role="QUESTION",
                    original_filename="문제지.pdf",
                    source_format="PDF",
                    media_type="application/pdf",
                    content_length=8,
                ),
                DocumentReviewSetSourceRequest(
                    role="SOLUTION",
                    original_filename="해설지.pdf",
                    source_format="PDF",
                    media_type="application/pdf",
                    content_length=8,
                ),
            ),
            preset_key="PROBLEM_SET",
            additional_guidance="문제와 해설의 조건 및 정답을 서로 대조해 주세요.",
        ),
        actor_id=OPERATOR_ID,
        observed_at=NOW,
    )
    return value.review_set_id


def test_paired_review_starts_only_after_both_members_and_replays(tmp_path: Path) -> None:
    service, engine, catalog, commands = _service()
    review_set_id = _create(service)
    question = tmp_path / "question.pdf"
    solution = tmp_path / "solution.pdf"
    question.write_bytes(b"%PDF-Q01")
    solution.write_bytes(b"%PDF-S01")

    command_id, waiting = service.accept_member_upload(
        review_set_id,
        "QUESTION",
        StagedPdfUpload(question, 8, _sha(question.read_bytes())),
        actor=_actor(),
        observed_at=NOW + timedelta(seconds=1),
    )
    assert command_id is None
    assert waiting.state == "AWAITING_UPLOADS"
    assert tuple(value.state for value in waiting.documents) == ("COMMITTED", "AWAITING_UPLOAD")

    command_id, started = service.accept_member_upload(
        review_set_id,
        "SOLUTION",
        StagedPdfUpload(solution, 8, _sha(solution.read_bytes())),
        actor=_actor(),
        observed_at=NOW + timedelta(seconds=2),
    )
    replay_command, replay = service.accept_member_upload(
        review_set_id,
        "QUESTION",
        StagedPdfUpload(question, 8, _sha(question.read_bytes())),
        actor=_actor(),
        observed_at=NOW + timedelta(seconds=3),
    )

    assert command_id == replay_command == "wfcmd_" + "8" * 32
    assert started == replay
    assert started.state == "STARTED"
    assert started.workflow_id == "workflow_" + "9" * 32
    assert tuple(value.state for value in started.documents) == ("COMMITTED", "COMMITTED")
    assert len(catalog.calls) == 2
    assert len(commands.calls) == 1
    request = commands.calls[0]["request"]
    assert tuple(value.role for value in request.documents) == ("QUESTION", "SOLUTION")
    assert request.documents[0].document.document_revision_id != (
        request.documents[1].document.document_revision_id
    )
    engine.dispose()


def test_paired_review_rejects_different_bytes_after_member_commit(tmp_path: Path) -> None:
    service, engine, _catalog, _commands = _service()
    review_set_id = _create(service)
    question = tmp_path / "question.pdf"
    question.write_bytes(b"%PDF-Q01")
    service.accept_member_upload(
        review_set_id,
        "QUESTION",
        StagedPdfUpload(question, 8, _sha(question.read_bytes())),
        actor=_actor(),
        observed_at=NOW + timedelta(seconds=1),
    )

    with pytest.raises(ApiError) as mismatch:
        service.accept_member_upload(
            review_set_id,
            "QUESTION",
            StagedPdfUpload(question, 8, "sha256:" + "f" * 64),
            actor=_actor(),
            observed_at=NOW + timedelta(seconds=2),
        )
    assert mismatch.value.error_code == "PAIRED_DOCUMENT_REVIEW_UPLOAD_HASH_MISMATCH"
    engine.dispose()


@pytest.mark.integration
@pytest.mark.api_integration
def test_paired_review_set_persists_parent_before_members_on_postgresql() -> None:
    if os.environ.get("EOM_RUN_API_INTEGRATION") != "1":
        pytest.skip("run through the guarded disposable PostgreSQL database")
    explicit_url = os.environ.get("EOM_DATABASE_URL")
    if not explicit_url:
        pytest.fail("paired review persistence requires the guarded database URL")
    engine = build_engine(explicit_url)
    suffix = uuid4().hex[:12]
    actor_id = "operator_" + uuid4().hex
    sessions = build_session_factory(engine)
    with sessions.begin() as session:
        session.add(
            OperatorRecord(
                operator_id=actor_id,
                username=f"paired-review-{suffix}",
                normalized_username=f"paired-review-{suffix}",
                display_name="Paired Review Persistence",
                status="ACTIVE",
                must_change_password=False,
                role_version=1,
                created_at=NOW,
                created_by="paired-review-integration",
                updated_at=NOW,
                lock_version=1,
            )
        )
    catalog = FakeCatalog()
    commands = FakeCommands()
    service = PairedDocumentReviewApplicationService(
        engine,
        catalog=catalog,  # type: ignore[arg-type]
        commands=commands,  # type: ignore[arg-type]
        intent_ttl_seconds=86_400,
        processing_lease_seconds=300,
    )
    try:
        value = service.create_set(
            CreateDocumentReviewSetRequest(
                documents=(
                    DocumentReviewSetSourceRequest(
                        role="QUESTION",
                        original_filename="question.pdf",
                        source_format="PDF",
                        media_type="application/pdf",
                        content_length=8,
                    ),
                    DocumentReviewSetSourceRequest(
                        role="SOLUTION",
                        original_filename="solution.pdf",
                        source_format="PDF",
                        media_type="application/pdf",
                        content_length=8,
                    ),
                ),
                preset_key="MOCK_EXAM",
                additional_guidance=None,
            ),
            actor_id=actor_id,
            observed_at=NOW,
        )
        with sessions() as session:
            assert session.get(DocumentReviewSetRecord, value.review_set_id) is not None
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(DocumentReviewSetMemberRecord)
                    .where(DocumentReviewSetMemberRecord.review_set_id == value.review_set_id)
                )
                == 2
            )
    finally:
        engine.dispose()


def test_cross_document_missing_status_cannot_invent_solution_location() -> None:
    question_anchor = PairedReviewAnchor(
        anchor_id="reviewanchor_" + "1" * 32,
        document_role="QUESTION",
        page_number=1,
        page_image_sha256="sha256:" + "1" * 64,
        region={"x_ppm": 1, "y_ppm": 1, "width_ppm": 10, "height_ppm": 10},
        quote=None,
        quote_sha256=None,
    )
    value = PairedReviewCrossDocumentCheck(
        check_id="reviewcross_" + "2" * 32,
        question_anchors=(question_anchor,),
        solution_anchors=(),
        status="MISSING",
        conclusion="해설지에서 대응하는 풀이를 찾지 못했습니다.",
    )
    assert value.solution_anchors == ()
    with pytest.raises(ValueError, match="must not invent"):
        PairedReviewCrossDocumentCheck(
            check_id="reviewcross_" + "3" * 32,
            question_anchors=(question_anchor,),
            solution_anchors=(
                question_anchor.model_copy(
                    update={
                        "anchor_id": "reviewanchor_" + "4" * 32,
                        "document_role": "SOLUTION",
                    }
                ),
            ),
            status="MISSING",
            conclusion="존재하지 않는 해설 위치를 만들면 안 됩니다.",
        )
