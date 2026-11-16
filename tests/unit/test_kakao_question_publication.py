"""Private Artifact boundary tests with anonymous inputs, no NAS or live account."""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service.artifacts import CatalogArtifact, CatalogArtifactService
from eom_catalog_service.kakao_question_publication import (
    publish_kakao_packet,
    publish_kakao_question,
)
from eom_identifiers import content_sha256, sha256_bytes

from tests.unit.test_kakao_question_editing import confirmed, packet, published, question, source


def publisher(tmp_path):
    service = Mock(spec=CatalogArtifactService)
    service.settings = SimpleNamespace(staging_root=tmp_path)
    seen = []
    receipts = {}

    def commit(**kwargs):
        files = {name: path.read_bytes() for name, path in kwargs["files"].items()}
        assert len(files) == 1
        assert {name: sha256_bytes(data) for name, data in files.items()} == kwargs[
            "expected_file_sha256"
        ]
        assert len(kwargs["idempotency_key"]) <= 128
        metadata = json.dumps([kwargs["request"], kwargs["result"]], ensure_ascii=False)
        assert "private-question" not in metadata
        assert "학생 1" not in metadata
        seen.append((kwargs, files))
        key, request_sha = kwargs["idempotency_key"], content_sha256(kwargs["request"])
        if key in receipts:
            old_sha, result = receipts[key]
            if old_sha != request_sha:
                raise ValueError("IDEMPOTENCY_CONFLICT")
            return result
        serial = f"{len(receipts) + 1:032x}"
        data = files[kwargs["primary_file"]]
        result = CatalogArtifact(
            job_id="job_" + serial,
            artifact_id="artifact_" + serial,
            revision_id="rev_" + serial,
            content_hash=sha256_bytes(data),
            manifest_hash=sha256_bytes(b"manifest"),
            content_bytes=len(data),
            nas_path="not-public",
            manifest={},
        )
        receipts[key] = request_sha, result
        return result

    service.commit_file_set.side_effect = commit
    return service, seen


def inputs():
    resolved = source(("private-question",), ("student",))
    value = confirmed(question(resolved), (resolved,))
    return resolved, value


def test_question_publication_pins_original_sources_and_replays(tmp_path):
    service, seen = publisher(tmp_path)
    resolved, value = inputs()
    check = Mock()
    first = publish_kakao_question(service, question=value, sources=(resolved,), authorize=check)
    again = publish_kakao_question(service, question=value, sources=(resolved,), authorize=check)
    assert first == again
    assert first.published.question.sources == value.sources
    assert first.published.pointer.artifact_id != value.question_id
    assert first.published.pointer.artifact_revision_id != value.question_revision_id
    assert first.publication_job_id.startswith("job_")
    assert set(seen[0][1]) == {"question.json"}
    assert json.loads(seen[0][1]["question.json"])["student"]["display_name"] == "학생 1"
    assert check.call_count == 6
    assert list(tmp_path.iterdir()) == []


def test_packet_publication_reuses_question_pointers_without_copying_sources(tmp_path):
    service, seen = publisher(tmp_path)
    _, value = inputs()
    selected = (published(value),)
    bundle = packet((value,))
    first = publish_kakao_packet(service, packet=bundle, questions=selected, authorize=lambda: None)
    again = publish_kakao_packet(service, packet=bundle, questions=selected, authorize=lambda: None)
    assert first == again
    assert set(seen[0][1]) == {"packet.json"}
    raw = seen[0][1]["packet.json"]
    assert b"private-question" not in raw
    assert first.packet.questions[0].manifest == selected[0].pointer
    assert first.pointer.sha256 == sha256_bytes(raw)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("kind", ["question", "packet"])
@pytest.mark.parametrize("denied_at,count", [(1, 0), (2, 0), (3, 1)])
def test_current_authority_revocation_never_returns_adoptable_result(
    tmp_path, kind, denied_at, count
):
    service, seen = publisher(tmp_path)
    resolved, value = inputs()
    calls = 0

    def authorize():
        nonlocal calls
        calls += 1
        if calls == denied_at:
            raise PermissionError("revoked")

    with pytest.raises(PermissionError):
        if kind == "question":
            publish_kakao_question(
                service, question=value, sources=(resolved,), authorize=authorize
            )
        else:
            publish_kakao_packet(
                service, packet=packet((value,)), questions=(published(value),), authorize=authorize
            )
    assert len(seen) == count
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("fault", ["hash", "source", "review_reasons"])
def test_forged_question_content_or_hidden_blocker_rejected_before_publication(tmp_path, fault):
    service, seen = publisher(tmp_path)
    resolved, value = inputs()
    if fault == "hash":
        block = value.ordered_blocks[0].model_copy(
            update={"source_text_sha256": "sha256:" + "0" * 64}
        )
        value = value.model_copy(update={"ordered_blocks": (block,)})
    elif fault == "source":
        resolved = source(("different-content",), ("student",))
    else:
        resolved = source(("private-question",), ("student",), context_verified=False)
        value = confirmed(question(resolved), (resolved,)).model_copy(update={"review_reasons": ()})
    with pytest.raises(ValueError, match="KAKAO_ARCHIVE_"):
        publish_kakao_question(service, question=value, sources=(resolved,), authorize=lambda: None)
    assert seen == []


def test_packet_blockers_cannot_be_hidden_by_submitted_dto(tmp_path):
    service, seen = publisher(tmp_path)
    value = question()
    bundle = packet((value,), mode="DRAFT")
    entry = bundle.questions[0].model_copy(update={"final_blockers": ()})
    forged = bundle.model_copy(update={"mode": "FINAL", "questions": (entry,)})
    with pytest.raises(ValueError, match="KAKAO_ARCHIVE_FINAL_BLOCKED"):
        publish_kakao_packet(
            service, packet=forged, questions=(published(value),), authorize=lambda: None
        )
    assert seen == []


def test_packet_must_pin_the_supplied_exact_manifest_not_a_successor(tmp_path):
    service, seen = publisher(tmp_path)
    resolved, value = inputs()
    bundle = packet((value,))
    successor = confirmed(value, (resolved,), number=11)
    with pytest.raises(ValueError, match="KAKAO_ARCHIVE_PACKET_MANIFEST_MISMATCH"):
        publish_kakao_packet(
            service, packet=bundle, questions=(published(successor),), authorize=lambda: None
        )
    assert seen == []


def test_same_identity_changed_manifest_does_not_get_new_publication_key(tmp_path):
    service, seen = publisher(tmp_path)
    resolved, value = inputs()
    publish_kakao_question(service, question=value, sources=(resolved,), authorize=lambda: None)
    changed = value.model_copy(update={"source_stale": True})
    with pytest.raises(ValueError, match="IDEMPOTENCY_CONFLICT"):
        publish_kakao_question(
            service, question=changed, sources=(resolved,), authorize=lambda: None
        )
    assert seen[0][0]["idempotency_key"] == seen[1][0]["idempotency_key"]


def test_lost_publication_response_replays_same_artifact(tmp_path):
    service, seen = publisher(tmp_path)
    resolved, value = inputs()
    commit = service.commit_file_set.side_effect
    interrupted = False

    def interrupt_once(**kwargs):
        nonlocal interrupted
        result = commit(**kwargs)
        if not interrupted:
            interrupted = True
            raise TimeoutError("lost response after commit")
        return result

    service.commit_file_set.side_effect = interrupt_once
    with pytest.raises(TimeoutError):
        publish_kakao_question(service, question=value, sources=(resolved,), authorize=lambda: None)
    result = publish_kakao_question(
        service, question=value, sources=(resolved,), authorize=lambda: None
    )
    assert result.publication_job_id == "job_" + "0" * 31 + "1"
    assert seen[0][1] == seen[1][1]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "field,value", [("content_hash", "sha256:" + "0" * 64), ("content_bytes", 1)]
)
def test_invalid_artifact_receipt_rejected(tmp_path, field, value):
    service, _ = publisher(tmp_path)
    resolved, selected = inputs()
    commit = service.commit_file_set.side_effect
    service.commit_file_set.side_effect = lambda **kwargs: replace(
        commit(**kwargs), **{field: value}
    )
    with pytest.raises(ValueError, match="KAKAO_ARCHIVE_PUBLICATION_MISMATCH"):
        publish_kakao_question(
            service, question=selected, sources=(resolved,), authorize=lambda: None
        )
    assert list(tmp_path.iterdir()) == []
