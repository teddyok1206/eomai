from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_catalog_contracts import (
    ApplyDocumentReviewHwpxCorrections,
    DocumentReviewHwpxCorrectionMediaQuery,
    DocumentReviewHwpxCorrectionResult,
    OfficeDocumentReviewMemberPointer,
    PdfDocumentReviewResultMemberPointer,
)
from eom_catalog_service.artifacts import CatalogArtifact
from eom_catalog_service.document_review_hwpx_correction_service import (
    DocumentReviewCorrectionArtifacts,
    DocumentReviewHwpxCorrectionService,
    DocumentReviewHwpxCorrectionServiceError,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import content_sha256, sha256_bytes, sha256_file
from sqlalchemy import create_engine


class _Artifacts:
    committed: dict[str, Any] | None = None
    output: bytes | None = None

    def read_member(self, **values: Any) -> bytes:
        if values["artifact_id"] == "artifact_" + "1" * 32:
            return b"{}"
        if values["artifact_id"] == "artifact_" + "2" * 32:
            return b"source-hwpx"
        if values["artifact_id"] == "artifact_" + "9" * 32 and self.output is not None:
            return self.output
        raise ValueError("unknown pointer")

    def commit_file_set(self, **values: Any) -> CatalogArtifact:
        self.committed = values
        files = cast(dict[str, Path], values["files"])
        expected = cast(dict[str, str], values["expected_file_sha256"])
        assert {name: sha256_file(path) for name, path in files.items()} == expected
        self.output = files["corrected/document-review-redline.hwpx"].read_bytes()
        return CatalogArtifact(
            job_id="job_" + "8" * 32,
            artifact_id="artifact_" + "9" * 32,
            revision_id="rev_" + "a" * 32,
            content_hash=expected["result.json"],
            manifest_hash="sha256:" + "b" * 64,
            content_bytes=files["result.json"].stat().st_size,
            nas_path="/non-live/correction",
            manifest={"files": []},
        )


def _review_pointer() -> PdfDocumentReviewResultMemberPointer:
    return PdfDocumentReviewResultMemberPointer(
        artifact_id="artifact_" + "1" * 32,
        artifact_revision_id="rev_" + "3" * 32,
        sha256="sha256:" + "c" * 64,
        content_length=2,
    )


def _base_pointer() -> OfficeDocumentReviewMemberPointer:
    return OfficeDocumentReviewMemberPointer(
        artifact_id="artifact_" + "2" * 32,
        artifact_revision_id="rev_" + "4" * 32,
        member_path="source/original.hwpx",
        sha256=sha256_bytes(b"source-hwpx"),
        content_length=len(b"source-hwpx"),
        media_type="application/vnd.hancom.hwpx",
        schema_ref="eom://schemas/document-review/editable-hwpx/1.0",
    )


def _command(finding_id: str) -> ApplyDocumentReviewHwpxCorrections:
    return ApplyDocumentReviewHwpxCorrections(
        actor_id="operator_" + "d" * 32,
        idempotency_key="document-review-correction-test",
        workflow_id="workflow_" + "5" * 32,
        review_result=_review_pointer(),
        base_hwpx=_base_pointer(),
        finding_ids=(finding_id,),
    )


def test_correction_service_commits_one_new_hwpx_and_streams_exact_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finding_id = "reviewfinding_" + "6" * 32
    finding = SimpleNamespace(
        finding_id=finding_id,
        finding_code="TYPO_CONFIRMED",
        recommendation=SimpleNamespace(
            operation="REPLACE",
            before_text="수정 전",
            after_text="수정 후",
        ),
    )

    class FakeRoleResult:
        workflow_id = "workflow_" + "5" * 32
        output = SimpleNamespace(findings=(finding,))

    monkeypatch.setattr(
        "eom_catalog_service.document_review_hwpx_correction_service.PdfDocumentReviewRoleResult",
        FakeRoleResult,
    )
    monkeypatch.setattr(
        "eom_catalog_service.document_review_hwpx_correction_service.validate_role_result",
        lambda *_args: FakeRoleResult(),
    )

    expected_plan_sha256 = "sha256:" + "7" * 64

    class FakePlan:
        plan_sha256 = expected_plan_sha256

        def model_dump(self, *, mode: str) -> dict[str, object]:
            assert mode == "json"
            return {"plan_sha256": expected_plan_sha256}

    monkeypatch.setattr(
        "eom_catalog_service.document_review_hwpx_correction_service."
        "build_document_review_hwpx_correction_plan",
        lambda *_args, **_kwargs: FakePlan(),
    )

    def fake_apply(
        _source: Path, output: Path, _plan: object
    ) -> DocumentReviewHwpxCorrectionResult:
        output.parent.mkdir(mode=0o700)
        output.write_bytes(b"PK\x03\x04corrected-hwpx")
        output_hash = sha256_file(output)
        correction_digest = content_sha256(
            {
                "workflow_id": "workflow_" + "5" * 32,
                "review_result": _review_pointer().model_dump(mode="json"),
                "base_hwpx": _base_pointer().model_dump(mode="json"),
                "finding_ids": [finding_id],
            }
        ).removeprefix("sha256:")
        value: dict[str, object] = {
            "schema_version": "document-review-hwpx-correction-result/1.0",
            "correction_id": f"doccorrection_{correction_digest[:32]}",
            "workflow_id": "workflow_" + "5" * 32,
            "plan_sha256": expected_plan_sha256,
            "base_hwpx_sha256": _base_pointer().sha256,
            "output_member": {
                "member_path": "corrected/document-review-redline.hwpx",
                "sha256": output_hash,
                "content_length": output.stat().st_size,
                "media_type": "application/vnd.hancom.hwpx",
            },
            "applied_finding_ids": [finding_id],
            "text_color": "#FF0000",
        }
        value["result_sha256"] = content_sha256(value)
        return DocumentReviewHwpxCorrectionResult.model_validate(value)

    monkeypatch.setattr(
        "eom_catalog_service.document_review_hwpx_correction_service."
        "apply_document_review_hwpx_correction",
        fake_apply,
    )
    settings = CatalogSettings(
        staging_root=tmp_path / "staging",
        nas_artifact_root=tmp_path / "nas",
        intake_root=tmp_path / "intake",
    )
    settings.staging_root.mkdir(mode=0o700)
    service = DocumentReviewHwpxCorrectionService(
        create_engine("sqlite+pysqlite:///:memory:"), settings
    )
    artifacts = _Artifacts()
    service.artifacts = cast(DocumentReviewCorrectionArtifacts, artifacts)

    response = service.apply(_command(finding_id))

    assert response.status == "OK"
    assert response.output is not None
    assert response.result is not None
    assert response.result.text_color == "#FF0000"
    assert artifacts.committed is not None
    assert artifacts.committed["artifact_type"] == "document-review-hwpx-correction"
    assert set(artifacts.committed["files"]) == {
        "result.json",
        "plan.json",
        "corrected/document-review-redline.hwpx",
    }
    media = service.load_output(
        DocumentReviewHwpxCorrectionMediaQuery(
            workflow_id="workflow_" + "5" * 32,
            correction_id=response.result.correction_id,
            output=response.output,
        )
    )
    assert b"".join(media.iter_chunks()) == artifacts.output


def test_correction_service_rejects_non_replace_finding_before_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finding_id = "reviewfinding_" + "6" * 32
    finding = SimpleNamespace(
        finding_id=finding_id,
        finding_code="VISUAL_CONFIRMED",
        recommendation=SimpleNamespace(operation="REDRAW", before_text=None, after_text=None),
    )

    class FakeRoleResult:
        workflow_id = "workflow_" + "5" * 32
        output = SimpleNamespace(findings=(finding,))

    monkeypatch.setattr(
        "eom_catalog_service.document_review_hwpx_correction_service.PdfDocumentReviewRoleResult",
        FakeRoleResult,
    )
    monkeypatch.setattr(
        "eom_catalog_service.document_review_hwpx_correction_service.validate_role_result",
        lambda *_args: FakeRoleResult(),
    )
    settings = CatalogSettings(
        staging_root=tmp_path / "staging",
        nas_artifact_root=tmp_path / "nas",
        intake_root=tmp_path / "intake",
    )
    settings.staging_root.mkdir(mode=0o700)
    service = DocumentReviewHwpxCorrectionService(
        create_engine("sqlite+pysqlite:///:memory:"), settings
    )
    artifacts = _Artifacts()
    service.artifacts = cast(DocumentReviewCorrectionArtifacts, artifacts)

    with pytest.raises(DocumentReviewHwpxCorrectionServiceError) as error:
        service.apply(_command(finding_id))

    assert error.value.code == "DOCUMENT_REVIEW_CORRECTION_FINDING_UNSUPPORTED"
    assert artifacts.committed is None
