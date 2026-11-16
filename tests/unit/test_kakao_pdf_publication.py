"""Real anonymous PDF → existing publication adapter; no live DB/NAS or Kakao."""

import json
from dataclasses import replace
from unittest.mock import Mock

import pymupdf
import pytest
from eom_catalog_service.kakao_pdf_publication import (
    LAYOUT_REF,
    PDF_REF,
    PREVIEW_REF,
    publish_kakao_pdf,
)
from eom_kakao_archive_contracts import canonical_bytes, sha256
from eom_orchestrator.kakao_pdf_execution import AcceptedKakaoPdf

from tests.unit.test_kakao_archive_intake import _publisher
from tests.unit.test_kakao_pdf_execution import LocalProcess, executor
from tests.unit.test_kakao_question_render import identity, picture
from tests.unit.test_kakao_question_render import prepared as prepared


@pytest.fixture
def rendered(prepared, tmp_path):
    source, _, prepare = prepared
    photo = picture(source)

    def with_photo(manifest):
        manifest["questions"][0]["images"].append(photo)

    command = prepare(with_photo)
    manifest_bytes = (source / "manifest.json").read_bytes()
    launcher = LocalProcess()
    execution = executor(tmp_path, launcher)
    accepted = execution.execute(command, source_root=source)
    assert accepted.result.status == "COMPLETED"
    return dict(command=command, manifest_bytes=manifest_bytes, accepted=accepted), launcher


def test_actual_pdf_previews_publication_exact_replay_no_render_and_private_metadata(
    rendered, tmp_path
):
    args, launcher = rendered
    publisher, commits = _publisher(tmp_path)
    authorize = Mock()
    first = publish_kakao_pdf(publisher, **args, authorize=authorize)
    second = publish_kakao_pdf(publisher, **args, authorize=authorize)
    assert first == second and launcher.calls == 1 and authorize.call_count == 6
    assert first.export_id == args["command"].export_id
    assert first.pdf.schema_ref == PDF_REF
    assert first.layout.schema_ref == LAYOUT_REF
    assert [p.schema_ref for p in first.previews] == [PREVIEW_REF]
    pointers = (first.pdf, first.layout, *first.previews)
    assert len({p.artifact_id for p in pointers}) == 1
    assert len({p.artifact_revision_id for p in pointers}) == 1
    assert [p.member_path for p in pointers] == ["report.pdf", "layout.json", "page-0001.png"]
    assert {p.member_path: p.sha256 for p in pointers} == commits[0][0]["expected_file_sha256"]
    assert str(args["accepted"].staging_root) not in repr(first)
    for fields, payloads in commits:
        assert fields["primary_file"] == "layout.json"
        assert {path.parent for path in fields["files"].values()} == {args["accepted"].staging_root}
        public_metadata = json.dumps(
            [fields["request"], fields["result"], fields["file_metadata"]], ensure_ascii=False
        )
        assert "익명 학생" not in public_metadata and "질문입니다" not in public_metadata
        assert "source.csv" not in payloads and "manifest.json" not in payloads
        with pymupdf.open(stream=payloads["report.pdf"], filetype="pdf") as document:
            assert len(document) == 1
            assert "질문입니다" in document[0].get_text()
            assert len(document[0].get_image_info()) == 1


@pytest.mark.parametrize(
    "which", ["export", "command", "manifest", "attempt", "files", "pages", "layout"]
)
def test_rejects_stale_foreign_or_forged_acceptance_before_publication(rendered, tmp_path, which):
    args, _ = rendered
    publisher, calls = _publisher(tmp_path)
    accepted = args["accepted"]
    result, layout, files = accepted.result, accepted.layout, accepted.files
    if which == "export":
        result = result.model_copy(update={"export_id": identity("export", 9)})
    elif which in {"command", "manifest"}:
        result = result.model_copy(update={which + "_sha256": "sha256:" + "f" * 64})
    elif which == "attempt":
        result = result.model_copy(
            update={"execution": result.execution.model_copy(update={"fence": 2})}
        )
    elif which == "files":
        files = files[:-1]
    elif which == "pages":
        result = result.model_copy(update={"page_count": 2})
    else:
        layout = layout.model_copy(update={"command_sha256": "sha256:" + "f" * 64})
    args["accepted"] = replace(accepted, result=result, layout=layout, files=files)
    with pytest.raises(ValueError):
        publish_kakao_pdf(publisher, **args, authorize=lambda: None)
    assert calls == []


@pytest.mark.parametrize("field", ["source_binding_id", "packet_revision_id", "student_id", "mode"])
def test_manifest_cannot_be_moved_to_different_binding_student_packet_or_mode(
    rendered, tmp_path, field
):
    args, _ = rendered
    publisher, calls = _publisher(tmp_path)
    changed = (
        "DRAFT"
        if field == "mode"
        else identity(
            {
                "source_binding_id": "binding",
                "packet_revision_id": "packetrev",
                "student_id": "student",
            }[field],
            9,
        )
    )
    manifest = json.loads(args["manifest_bytes"])
    manifest[field] = changed
    raw = canonical_bytes(manifest)
    # Even if local content and its hash are internally consistent, cross-identity
    # input is not the originally selected student's export.
    command = args["command"].model_copy(
        update={
            "manifest": args["command"].manifest.model_copy(
                update={"sha256": sha256(raw), "size_bytes": len(raw)}
            )
        }
    )
    args.update(command=command, manifest_bytes=raw)
    with pytest.raises(ValueError, match="MANIFEST_IDENTITY_MISMATCH"):
        publish_kakao_pdf(publisher, **args, authorize=lambda: None)
    assert calls == []


@pytest.mark.parametrize("boundary,committed", [(1, 0), (2, 0), (3, 1)])
def test_revoke_current_source_or_fence_before_or_after_commit(
    rendered, tmp_path, boundary, committed
):
    args, launcher = rendered
    publisher, calls = _publisher(tmp_path)
    count = 0

    def authorize():
        nonlocal count
        count += 1
        if count == boundary:
            raise PermissionError("revoked")

    with pytest.raises(PermissionError):
        publish_kakao_pdf(publisher, **args, authorize=authorize)
    assert len(calls) == committed
    assert launcher.calls == 1
    assert (args["accepted"].staging_root / "report.pdf").is_file()
    # When authority is valid again, exact publication is adopted without rerender.
    recovered = publish_kakao_pdf(publisher, **args, authorize=lambda: None)
    assert recovered.pdf.sha256 == next(
        m.sha256 for m in args["accepted"].files if m.relative_path == "report.pdf"
    )
    assert launcher.calls == 1


@pytest.mark.parametrize("status", ["NEEDS_LAYOUT_REVIEW", "INVALID_INPUT"])
def test_failed_or_needs_review_results_do_not_publish(rendered, tmp_path, status):
    args, _ = rendered
    publisher, calls = _publisher(tmp_path)
    result = args["accepted"].result.model_copy(
        update={
            "status": status,
            "page_count": 0,
            "outputs": (),
            "error_code": "KAKAO_LAYOUT_FAILED",
        }
    )
    args["accepted"] = AcceptedKakaoPdf(result, None, (), None)
    with pytest.raises(ValueError, match="PDF_NOT_COMPLETED"):
        publish_kakao_pdf(publisher, **args, authorize=lambda: None)
    assert calls == []


def test_completed_publication_response_loss_reuses_exact_artifact(rendered, tmp_path):
    args, launcher = rendered
    publisher, calls = _publisher(tmp_path)
    commit = publisher.commit_file_set.side_effect
    once = True

    def lose_response(**kwargs):
        nonlocal once
        result = commit(**kwargs)
        if once:
            once = False
            raise TimeoutError("response lost after commit")
        return result

    publisher.commit_file_set.side_effect = lose_response
    with pytest.raises(TimeoutError):
        publish_kakao_pdf(publisher, **args, authorize=lambda: None)
    recovered = publish_kakao_pdf(publisher, **args, authorize=lambda: None)
    again = publish_kakao_pdf(publisher, **args, authorize=lambda: None)
    assert recovered == again and len(calls) == 3 and launcher.calls == 1
    assert len({call[0]["idempotency_key"] for call in calls}) == 1
