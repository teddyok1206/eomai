"""No live data: test Catalog publication ownership and replay, not NAS persistence."""

import json
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.kakao_snapshot import KakaoRoomSnapshot
from eom_catalog_service.artifacts import CatalogArtifact, CatalogArtifactService
from eom_catalog_service.kakao_archive_intake import publish_kakao_capture
from eom_catalog_service.kakao_csv_parser import parse_kakao_csv
from eom_identifiers import content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from pydantic import ValidationError


def _input():
    source = b"DATE,USER,MESSAGE\n2026-10-01 00:00:00,private-student,private-message\n"
    normalized = parse_kakao_csv(
        source,
        source_binding_id="kakaobinding_" + "1" * 32,
        room_id="kakaoroom_" + "2" * 32,
        snapshot_revision_id="kakaosnapshotrev_" + "3" * 32,
        normalization_revision_id="kakaonormalizationrev_" + "4" * 32,
        observed_at_utc=datetime(2026, 11, 16, tzinfo=UTC),
    )
    snapshot = KakaoRoomSnapshot(
        source_binding_id=normalized.source_binding_id,
        room_id=normalized.room_id,
        snapshot_revision_id=normalized.snapshot_revision_id,
        source_sha256=normalized.source_sha256,
        source_bytes=normalized.source_bytes,
        observed_at_utc=normalized.observed_at_utc,
        csv_scope="unknown",
    )
    return dict(source=source, snapshot=snapshot, normalization=normalized)


def test_snapshot_schema_canonical_and_packaged_bytes_match():
    canonical = Path(__file__).parents[2] / "schemas/kakao-archive/room-snapshot-v1.schema.json"
    resource = files("eom_catalog_contracts").joinpath(
        "resources/kakao-archive/room-snapshot-v1.schema.json"
    )
    assert canonical.read_bytes() == resource.read_bytes()
    Draft202012Validator.check_schema(json.loads(resource.read_bytes()))


@pytest.mark.parametrize(
    "key,value",
    [
        ("source_bytes", True),
        ("source_bytes", 0),
        ("source_bytes", 33554433),
        ("csv_scope", "complete"),
        ("source_sha256", "0" * 64),
        ("source_binding_id", "kakaoroom_" + "1" * 32),
        ("observed_at_utc", "2026-11-16T10:00:00+09:00"),
        ("authority", "ADMIN"),
    ],
)
def test_snapshot_rejects_invalid_or_untrusted_authority(key, value):
    payload = _input()["snapshot"].model_dump(mode="json")
    payload[key] = value
    with pytest.raises(ValidationError):
        KakaoRoomSnapshot.model_validate(payload)


def _publisher(tmp_path):
    publisher = Mock(spec=CatalogArtifactService)
    publisher.settings = SimpleNamespace(staging_root=tmp_path)
    captured = []
    prior = {}

    def commit(**kwargs):
        files = {name: path.read_bytes() for name, path in kwargs["files"].items()}
        assert {name: sha256_bytes(data) for name, data in files.items()} == kwargs[
            "expected_file_sha256"
        ]
        metadata = json.dumps([kwargs["request"], kwargs["result"], kwargs["file_metadata"]])
        assert "private-student" not in metadata
        assert "private-message" not in metadata
        key = kwargs["idempotency_key"]
        request_sha = content_sha256(kwargs["request"])
        captured.append((kwargs, files))
        if key in prior:
            old_sha, result = prior[key]
            if old_sha != request_sha:
                raise ValueError("CONFLICT")
            return result
        serial = str(len(prior) + 1) * 32
        primary = files[kwargs["primary_file"]]
        result = CatalogArtifact(
            job_id="job_" + serial,
            artifact_id="artifact_" + serial,
            revision_id="rev_" + serial,
            content_hash=sha256_bytes(primary),
            manifest_hash=sha256_bytes(b"manifest"),
            content_bytes=len(primary),
            nas_path="not-exposed",
            manifest={},
        )
        prior[key] = (request_sha, result)
        return result

    publisher.commit_file_set.side_effect = commit
    return publisher, captured


def test_raw_normalized_separate_pointer_only_metadata_and_stable_replay(tmp_path):
    publisher, calls = _publisher(tmp_path)
    authorized = Mock()
    args = _input()
    first = publish_kakao_capture(publisher, **args, authorize=authorized)
    second = publish_kakao_capture(publisher, **args, authorize=authorized)
    assert first == second
    assert first.source.artifact_id == first.snapshot.artifact_id
    assert first.source.artifact_id != first.normalization.artifact_id
    assert first.source.sha256 == sha256_bytes(args["source"])
    assert calls[0][1]["source.csv"] == args["source"]
    assert json.loads(calls[1][1]["normalization.json"])["messages"][0]["text"] == "private-message"
    assert calls[1][0]["request"]["source"] == first.source.model_dump(mode="json")
    assert "nas_path" not in repr(first)
    assert authorized.call_count == 8
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("fault", ["raw", "identity", "normalized_text"])
def test_untrusted_changed_payload_never_publishes(tmp_path, fault):
    publisher, calls = _publisher(tmp_path)
    args = _input()
    if fault == "raw":
        args["source"] += b"x"
    elif fault == "identity":
        args["snapshot"] = args["snapshot"].model_copy(update={"room_id": "kakaoroom_" + "8" * 32})
    else:
        normalized = args["normalization"]
        message = normalized.messages[0].model_copy(update={"text": "forged"})
        args["normalization"] = normalized.model_copy(update={"messages": (message,)})
    with pytest.raises(ValueError, match="KAKAO_ARCHIVE_"):
        publish_kakao_capture(publisher, **args, authorize=lambda: None)
    assert calls == []


@pytest.mark.parametrize("denied_call,publications", [(1, 0), (2, 0), (3, 1), (4, 2)])
def test_current_authority_rechecked_at_each_boundary(tmp_path, denied_call, publications):
    publisher, calls = _publisher(tmp_path)
    count = 0

    def authorize():
        nonlocal count
        count += 1
        if count == denied_call:
            raise PermissionError("denied")

    with pytest.raises(PermissionError):
        publish_kakao_capture(publisher, **_input(), authorize=authorize)
    assert len(calls) == publications
    assert list(tmp_path.iterdir()) == []


def test_changed_capture_same_identity_conflicts_not_new_key(tmp_path):
    publisher, calls = _publisher(tmp_path)
    args = _input()
    publish_kakao_capture(publisher, **args, authorize=lambda: None)
    args["snapshot"] = args["snapshot"].model_copy(update={"csv_scope": "loaded_window"})
    with pytest.raises(ValueError, match="CONFLICT"):
        publish_kakao_capture(publisher, **args, authorize=lambda: None)
    assert calls[0][0]["idempotency_key"] == calls[2][0]["idempotency_key"]


def test_completed_raw_publication_is_reused_after_normalization_interruption(tmp_path):
    publisher, calls = _publisher(tmp_path)
    commit = publisher.commit_file_set.side_effect
    interrupted = False

    def stop_once(**kwargs):
        nonlocal interrupted
        if kwargs["artifact_type"] == "kakao-message-normalization" and not interrupted:
            interrupted = True
            raise OSError("simulated unavailable")
        return commit(**kwargs)

    publisher.commit_file_set.side_effect = stop_once
    with pytest.raises(OSError):
        publish_kakao_capture(publisher, **_input(), authorize=lambda: None)
    result = publish_kakao_capture(publisher, **_input(), authorize=lambda: None)
    assert result.snapshot_publication_job_id == "job_" + "1" * 32
    assert calls[0][0]["idempotency_key"] == calls[1][0]["idempotency_key"]
    assert list(tmp_path.iterdir()) == []
