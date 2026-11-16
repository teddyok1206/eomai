"""Anonymous photo bytes; no real student, account, NAS or runtime mutations."""

import io
import json
from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from eom_catalog_contracts.kakao_media import MEDIA_BLOB_REF, KakaoMediaBlobReceipt
from eom_catalog_service import kakao_media_publication as media
from eom_catalog_service.artifacts import CatalogArtifact, CatalogArtifactService
from eom_identifiers import content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from PIL import Image
from pydantic import ValidationError

BINDING = "kakaobinding_" + "1" * 32


def photo(kind="PNG", *, orientation=None):
    output = io.BytesIO()
    with Image.new("RGB", (24, 18), (44, 80, 120)) as image:
        options = {}
        if orientation is not None:
            exif = image.getexif()
            exif[274] = orientation
            options["exif"] = exif
        image.save(output, kind, **options)
    return output.getvalue()


def publisher(tmp_path):
    service = Mock(spec=CatalogArtifactService)
    service.settings = SimpleNamespace(staging_root=tmp_path)
    calls, prior = [], {}

    def commit(**kwargs):
        payloads = {name: path.read_bytes() for name, path in kwargs["files"].items()}
        assert kwargs["expected_file_sha256"] == {
            name: sha256_bytes(raw) for name, raw in payloads.items()
        }
        key, request_hash = kwargs["idempotency_key"], content_sha256(kwargs["request"])
        calls.append((kwargs, payloads))
        if key in prior:
            original_hash, result = prior[key]
            assert original_hash == request_hash
            return result
        suffix = f"{len(prior) + 1:032x}"
        primary = payloads[kwargs["primary_file"]]
        result = CatalogArtifact(
            job_id="job_" + suffix,
            artifact_id="artifact_" + suffix,
            revision_id="rev_" + suffix,
            content_hash=sha256_bytes(primary),
            manifest_hash=sha256_bytes(b"manifest"),
            content_bytes=len(primary),
            nas_path="never-exposed",
            manifest={},
        )
        prior[key] = request_hash, result
        return result

    service.commit_file_set.side_effect = commit
    return service, calls


def test_schema_mirror_and_actual_byte_receipt():
    canonical = Path(__file__).parents[2] / "schemas/kakao-archive/media-blob-v1.schema.json"
    packaged = files("eom_catalog_contracts").joinpath(
        "resources/kakao-archive/media-blob-v1.schema.json"
    )
    assert canonical.read_bytes() == packaged.read_bytes()
    schema = json.loads(canonical.read_bytes())
    Draft202012Validator.check_schema(schema)
    receipt = media.inspect_kakao_media(BINDING, photo())
    Draft202012Validator(schema).validate(receipt.model_dump(mode="json"))
    assert receipt.pixel_count == 24 * 18


@pytest.mark.parametrize(
    "kind,mime", [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")]
)
def test_actual_formats_keep_original_and_replay_same_binding(tmp_path, kind, mime):
    service, calls = publisher(tmp_path)
    source = photo(kind)
    authorize = Mock()
    first = media.publish_kakao_media(
        service, source_binding_id=BINDING, source=source, authorize=authorize
    )
    second = media.publish_kakao_media(
        service, source_binding_id=BINDING, source=source, authorize=authorize
    )
    assert first == second
    assert first.receipt.media_type == mime
    assert first.original.sha256 == sha256_bytes(source)
    assert first.manifest.schema_ref == MEDIA_BLOB_REF
    assert first.original.artifact_id == first.manifest.artifact_id
    assert first.original.artifact_revision_id == first.manifest.artifact_revision_id
    assert calls[0][1][first.original.member_path] == source
    assert set(calls[0][0]["request"]) == set(KakaoMediaBlobReceipt.model_fields)
    assert authorize.call_count == 6
    assert list(tmp_path.iterdir()) == []
    assert "never-exposed" not in repr(first)


def test_exif_original_is_not_reencoded_or_rotated(tmp_path):
    service, calls = publisher(tmp_path)
    source = photo("JPEG", orientation=6)
    result = media.publish_kakao_media(
        service, source_binding_id=BINDING, source=source, authorize=lambda: None
    )
    with Image.open(io.BytesIO(calls[0][1][result.original.member_path])) as image:
        assert image.getexif()[274] == 6
    assert calls[0][1][result.original.member_path] == source


def test_same_photo_different_bindings_cannot_share_publication(tmp_path):
    service, calls = publisher(tmp_path)
    first = media.publish_kakao_media(
        service, source_binding_id=BINDING, source=photo(), authorize=lambda: None
    )
    second = media.publish_kakao_media(
        service,
        source_binding_id="kakaobinding_" + "2" * 32,
        source=photo(),
        authorize=lambda: None,
    )
    assert first.original.sha256 == second.original.sha256
    assert first.original.artifact_id != second.original.artifact_id
    assert calls[0][0]["idempotency_key"] != calls[1][0]["idempotency_key"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_bytes", True),
        ("source_bytes", 0),
        ("source_bytes", 33554433),
        ("width_px", True),
        ("width_px", 0),
        ("pixel_count", 50000001),
        ("pixel_count", 1),
        ("original_bytes_preserved", 1),
        ("original_bytes_preserved", False),
        ("source_sha256", "not-a-hash"),
        ("media_type", "image/svg+xml"),
        ("room_id", "private-room"),
        ("observed_at_utc", "2026-11-16T00:00:00Z"),
        ("suggested_filename", "private-student.jpeg"),
    ],
)
def test_receipt_rejects_forged_or_observation_specific_metadata(field, value):
    value_dict = media.inspect_kakao_media(BINDING, photo()).model_dump(mode="json")
    value_dict[field] = value
    with pytest.raises(ValidationError):
        KakaoMediaBlobReceipt.model_validate(value_dict)


@pytest.mark.parametrize(
    "source", [b"", b"<svg></svg>", b"not-an-image", b"%PDF-1.7", b"\xff\xd8\xffbad"]
)
def test_invalid_image_never_published(tmp_path, source):
    service, calls = publisher(tmp_path)
    with pytest.raises(ValueError, match="KAKAO_ARCHIVE_MEDIA_"):
        media.publish_kakao_media(
            service, source_binding_id=BINDING, source=source, authorize=lambda: None
        )
    assert calls == [] and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "width,height", [(30001, 1), (1, 30001), (10000, 10000), (True, 2), (0, 2)]
)
def test_header_pixel_limit_precedes_decode(monkeypatch, width, height):
    source = photo()
    image = MagicMock()
    image.__enter__.return_value = image
    image.size, image.format = (width, height), "PNG"
    monkeypatch.setattr(Image, "open", lambda *args, **kwargs: image)
    with pytest.raises(ValueError, match="DIMENSIONS_INVALID"):
        media.inspect_kakao_media(BINDING, source)
    image.verify.assert_not_called()
    image.load.assert_not_called()


def test_byte_limit_precedes_image_parser(monkeypatch):
    source = photo()
    monkeypatch.setattr(media, "MAX_MEDIA_BYTES", len(source) - 1)
    parse = Mock(side_effect=AssertionError("must not parse oversized input"))
    monkeypatch.setattr(Image, "open", parse)
    with pytest.raises(ValueError, match="SIZE_INVALID"):
        media.inspect_kakao_media(BINDING, source)
    parse.assert_not_called()


@pytest.mark.parametrize("denied_at,expected_calls", [(1, 0), (2, 0), (3, 1)])
def test_revoke_at_each_boundary_preserves_result_without_exposure(
    tmp_path, denied_at, expected_calls
):
    service, calls = publisher(tmp_path)
    count = 0

    def authorize():
        nonlocal count
        count += 1
        if count == denied_at:
            raise PermissionError("current access revoked")

    with pytest.raises(PermissionError):
        media.publish_kakao_media(
            service, source_binding_id=BINDING, source=photo(), authorize=authorize
        )
    assert len(calls) == expected_calls
    assert list(tmp_path.iterdir()) == []


def test_publication_hash_mismatch_is_not_adopted(tmp_path):
    service, calls = publisher(tmp_path)
    commit = service.commit_file_set.side_effect

    def corrupt(**kwargs):
        result = commit(**kwargs)
        from dataclasses import replace

        return replace(result, content_hash=sha256_bytes(b"different receipt"))

    service.commit_file_set.side_effect = corrupt
    with pytest.raises(ValueError, match="PUBLICATION_MISMATCH"):
        media.publish_kakao_media(
            service, source_binding_id=BINDING, source=photo(), authorize=lambda: None
        )
    assert len(calls) == 1 and list(tmp_path.iterdir()) == []
