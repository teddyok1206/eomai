"""Native source rendering tests are synthetic protocol/media checks, not model quality."""

from __future__ import annotations

import ast
import hashlib
import io
import os
import struct
import subprocess
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_image_contracts import content_json_bytes, content_sha256
from eom_image_contracts.source_pdf_crops import (
    SOURCE_PDF_CROP_COMMAND_SCHEMA_REF,
    SOURCE_PDF_CROP_SET_SCHEMA_REF,
    NativeSourcePdfRenderRequest,
    NativeSourcePdfRenderResult,
    native_source_pdf_render_request,
    validate_native_source_pdf_render_result,
)
from eom_image_contracts.validation import SCHEMA_SHA256, load_schema, validate_contract
from eom_image_trainer import source_pdf_render as worker
from eom_orchestrator import source_pdf_crop_processing as processing
from eom_orchestrator import source_pdf_crop_publication as publication
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.source_pdf_crop_inputs import (
    PreparedScienceSourcePdfCrops,
    ScienceSourcePdfCropRead,
)
from PIL import Image, ImageDraw
from pydantic import ValidationError

from tests.unit.test_science_source_page_crops import _fixture_review
from tests.unit.test_science_source_pdf_crops import _command, _pointer


def _sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _request(monkeypatch):
    review, lineage, _ = _fixture_review(monkeypatch, count=1)
    command = _command(review)
    selection = review.selections[0]
    source = next(
        s
        for p in lineage.plans
        for s in p.selected_sources
        if s.document_id == selection.document_id
    )
    return native_source_pdf_render_request(command, source, (selection,)), command, review


def _png(width, height):
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((20, 20, width - 20, height - 20), outline="black", width=3)
    stream = io.BytesIO()
    image.save(stream, format="PNG", compress_level=9)
    return stream.getvalue()


def _packet(request, fault=None):
    members, images = [], {}
    for region in request.regions:
        left, top, right, bottom = region.pixel_box
        width, height = (right - left) * 4, (bottom - top) * 4
        raw = _png(width, height)
        if fault == "bad_idat_crc":
            offset = 8
            while raw[offset + 4 : offset + 8] != b"IDAT":
                offset += 12 + struct.unpack_from(">I", raw, offset)[0]
            raw = raw[: offset + 8] + bytes([raw[offset + 8] ^ 1]) + raw[offset + 9 :]
        images["crops/" + region.selection_id + ".png"] = raw
        members.append(
            {
                "selection_id": region.selection_id,
                "member_path": "crops/" + region.selection_id + ".png",
                "sha256": _sha(raw),
                "size_bytes": len(raw),
                "width_px": width,
                "height_px": height,
                "perceptual_hash": "0" * 16,
            }
        )
    value = {
        "schema_version": "local-image-science-source-pdf-render-result/1.0",
        "request_sha256": request.request_sha256,
        "members": members,
        "activation_policy": "FORBIDDEN",
    }
    if fault == "wrong_request":
        value["request_sha256"] = "sha256:" + "f" * 64
    if fault == "bad_dimensions":
        members[0]["width_px"] -= 4
    if fault == "wrong_hash":
        members[0]["sha256"] = "sha256:" + "f" * 64
    if fault == "extra_metadata":
        value["worker_private_path"] = "/root/secret"
    stream = io.BytesIO()
    with zipfile.ZipFile(
        stream,
        "w",
        compression=zipfile.ZIP_DEFLATED if fault == "compressed" else zipfile.ZIP_STORED,
    ) as archive:
        archive.writestr(
            "result.json", content_json_bytes(value) + (b" " if fault == "noncanonical" else b"")
        )
        for name, raw in images.items():
            if fault != "missing":
                archive.writestr(name, raw)
        if fault == "extra":
            archive.writestr("../../outside", b"bad")
    return stream.getvalue()


def test_request_result_schema_roundtrip_and_package_guards(monkeypatch):
    request, _, _ = _request(monkeypatch)
    result_raw = _packet(request)
    outputs = processing.parse_native_source_pdf_render_response(request, result_raw)
    assert len(outputs) == 1
    with zipfile.ZipFile(io.BytesIO(result_raw)) as archive:
        result = NativeSourcePdfRenderResult.model_validate_json(archive.read("result.json"))
    validate_native_source_pdf_render_result(request, result)
    root = Path(__file__).resolve().parents[2]
    for kind, value in (("request", request), ("result", result)):
        name = "science-source-pdf-render-" + kind
        filename = "local-image-" + name + "-v1.schema.json"
        assert load_schema(name)["$schema"].endswith("2020-12/schema")
        validate_contract(name, value.model_dump(mode="json"))
        assert (
            type(value).model_validate_json(content_json_bytes(value.model_dump(mode="json")))
            == value
        )
        raw = (root / "schemas/image-provider" / filename).read_bytes()
        assert _sha(raw) == SCHEMA_SHA256[name]
        assert (
            raw
            == (
                root / "packages/image_contracts/eom_image_contracts/schemas" / filename
            ).read_bytes()
        )
        for script in ("image_provider", "image_trainer"):
            assert filename in (root / "scripts" / script / "build_release.sh").read_text()
    assert (
        "eom_image_trainer/source_pdf_render.py"
        in (root / "scripts/image_trainer/build_release.sh").read_text()
    )


@pytest.mark.parametrize(
    ("relative", "forbidden"),
    [
        (
            "packages/image_contracts/eom_image_contracts/source_pdf_crops.py",
            ("eom_orchestrator", "eom_image_trainer", "sqlalchemy", "subprocess", "pathlib"),
        ),
        (
            "services/image_trainer/eom_image_trainer/source_pdf_render.py",
            ("eom_orchestrator", "eom_catalog_service", "sqlalchemy", "torch", "requests"),
        ),
        (
            "services/orchestrator/eom_orchestrator/source_pdf_crop_publication.py",
            ("eom_catalog_service", "eom_image_trainer", "eom_item_registry"),
        ),
    ],
)
def test_native_source_modules_preserve_dependency_direction(relative, forbidden):
    root = Path(__file__).resolve().parents[2]
    imports = set()
    for node in ast.walk(ast.parse((root / relative).read_text())):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    assert not {
        name
        for name in imports
        if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)
    }


@pytest.mark.parametrize(
    "change", ["reserved", "oversized", "wrong_page", "frame", "dpi", "renderer", "hash"]
)
def test_request_rejects_reserved_drift_and_unbounded_values(monkeypatch, change):
    request, _, _ = _request(monkeypatch)
    value = request.model_dump(mode="json")
    if change == "reserved":
        value["source"]["partition"] = "HOLDOUT"
    elif change == "oversized":
        value["source"]["bytes"] = 64 * 1024**2 + 1
    elif change == "wrong_page":
        value["regions"][0]["source_page"]["member_path"] = "pages/wrong/page-1.png"
    elif change == "frame":
        value["regions"][0]["pixel_box"] = [0, 0, 10000, 10000]
    elif change == "renderer":
        value["renderer"]["path"] = "/usr/bin/tesseract"
    elif change == "dpi":
        value["render_dpi"] = 288
    else:
        value["request_sha256"] = "sha256:" + "f" * 64
    if change != "hash":
        value["request_sha256"] = content_sha256(
            {k: v for k, v in value.items() if k != "request_sha256"}
        )
    with pytest.raises(ValidationError):
        NativeSourcePdfRenderRequest.model_validate(value)


@pytest.mark.parametrize(
    "fault",
    [
        "extra",
        "missing",
        "compressed",
        "wrong_request",
        "wrong_hash",
        "bad_dimensions",
        "bad_idat_crc",
        "extra_metadata",
        "noncanonical",
    ],
)
def test_response_drift_and_corrupted_png_refused(monkeypatch, fault):
    request, _, _ = _request(monkeypatch)
    with pytest.raises(ValueError, match="RESPONSE_INVALID"):
        processing.parse_native_source_pdf_render_response(request, _packet(request, fault))


def test_source_mismatch_prevents_subprocess_and_worker_tool(monkeypatch):
    request, _, _ = _request(monkeypatch)
    monkeypatch.setattr(
        processing.subprocess, "run", lambda *_a, **_k: pytest.fail("premature process")
    )
    with pytest.raises(ValueError, match="SOURCE_BYTES_MISMATCH"):
        processing.process_source_pdf_crops(request, b"not a PDF")
    with pytest.raises(worker.NativePdfRenderError, match="SOURCE_BYTES_MISMATCH"):
        worker.render_native_source_pdf(request, b"not a PDF")


@pytest.mark.parametrize("fault", [None, "timeout", "failed"])
def test_fixed_cpu_sandbox_and_no_automatic_retry(monkeypatch, fault):
    request, _, _ = _request(monkeypatch)
    raw = b"%PDF-fixture" + b"x" * (request.source.bytes - 12)
    value = request.model_dump(mode="json")
    digest = _sha(raw)
    old_id = request.source.document_id
    value["source"]["pdf"]["sha256"] = digest
    value["source"]["document_id"] = "sciencedoc_" + digest[7:39]
    value["regions"][0]["source_page"]["member_path"] = value["regions"][0]["source_page"][
        "member_path"
    ].replace(old_id, value["source"]["document_id"])
    value["request_sha256"] = content_sha256(
        {k: v for k, v in value.items() if k != "request_sha256"}
    )
    request = NativeSourcePdfRenderRequest.model_validate(value)
    calls = []

    def invoke(arguments, **kwargs):
        calls.append(arguments)
        assert arguments[0] == "/usr/bin/systemd-run"
        for property_value in (
            "PrivateNetwork=yes",
            "PrivateDevices=yes",
            "ProtectHome=yes",
            "NoNewPrivileges=yes",
            "MemoryMax=1G",
            "RuntimeMaxSec=45",
            "CapabilityBoundingSet=",
        ):
            assert property_value in arguments
        assert "--uid=eom-image" in arguments and "--gid=eom-image" in arguments
        assert kwargs["input"] == raw and kwargs["timeout"] == 55
        assert not any("TOKEN" in key or "DATABASE" in key for key in kwargs["env"])
        assert arguments[-4:-1] == ["-I", "-m", "eom_image_trainer.source_pdf_render"]
        if fault == "timeout":
            raise subprocess.TimeoutExpired(arguments, 55)
        return SimpleNamespace(
            returncode=1 if fault == "failed" else 0, stdout=_packet(request), stderr=b""
        )

    monkeypatch.setattr(processing.subprocess, "run", invoke)
    if fault:
        with pytest.raises(
            ValueError, match="OBSERVATION_TIMEOUT" if fault == "timeout" else "PROCESS_FAILED"
        ):
            processing.process_source_pdf_crops(request, raw)
    else:
        assert len(processing.process_source_pdf_crops(request, raw)) == 1
    assert len(calls) == 1


def _publication_fixture(monkeypatch):
    request, command, review = _request(monkeypatch)
    raw = content_json_bytes(command.model_dump(mode="json"))
    pointer = _pointer(raw, SOURCE_PDF_CROP_COMMAND_SCHEMA_REF, "science-source-pdf-crop-command")
    read = ScienceSourcePdfCropRead(request.source, review.selections)
    prepared = PreparedScienceSourcePdfCrops(command, review, (read,))
    monkeypatch.setattr(publication, "resolve_control_artifact_member", lambda *_a, **_k: raw)
    monkeypatch.setattr(publication, "prepare_source_pdf_crop_reads", lambda *_: prepared)
    monkeypatch.setattr(
        publication, "iter_source_pdf_crop_payloads", lambda *_: iter(((read, b"synthetic"),))
    )
    calls = []

    class Publisher:
        def __init__(self, _engine, _settings):
            pass

        def publish(self, **arguments):
            ControlFileSetPublisher._request(object.__new__(ControlFileSetPublisher), **arguments)
            calls.append(arguments)
            member = next(
                m for m in arguments["members"] if m.file_name == arguments["primary_file"]
            )
            return SimpleNamespace(
                primary_sha256=member.sha256,
                artifact_id="artifact_" + "1" * 32,
                artifact_revision_id="rev_" + "2" * 32,
                primary_file=member.file_name,
            )

    monkeypatch.setattr(publication, "ControlFileSetPublisher", Publisher)
    return command, review, pointer, prepared, calls


def test_publication_commits_only_full_native_set_and_keeps_target_review_pending(
    monkeypatch, tmp_path
):
    command, _review, pointer, _prepared, calls = _publication_fixture(monkeypatch)

    def process(request, _raw):
        return processing.parse_native_source_pdf_render_response(request, _packet(request))

    result = publication.materialize_and_publish_source_pdf_crops(
        object(),
        object(),
        pointer,
        workspace=tmp_path / "success",
        created_at=datetime(2026, 10, 4, 16, tzinfo=UTC),
        execution_source_commit="b" * 40,
        process=process,
    )
    assert (
        result.crop_set.command == pointer
        and result.crop_set.command_sha256 == command.command_sha256
    )
    assert result.crop_set.state == "RENDERED_SOURCE_DERIVATIVES_PENDING_TARGET_REVIEW"
    assert result.crop_set.activation_policy == "FORBIDDEN"
    assert len(calls) == 1 and len(calls[0]["members"]) == 2
    assert calls[0]["source_commit"] == "b" * 40
    assert calls[0]["idempotency_key"] == "source-pdf-crop-set:" + command.command_sha256
    assert calls[0]["artifact_type"] == "control_local_image_science_source_pdf_crop_set"
    with pytest.raises(ValueError, match="NOT_EXCLUSIVE"):
        publication.materialize_and_publish_source_pdf_crops(
            object(),
            object(),
            pointer,
            workspace=tmp_path / "success",
            created_at=datetime(2026, 10, 4, 16, tzinfo=UTC),
            execution_source_commit="b" * 40,
            process=lambda *_: pytest.fail("renderer replayed"),
        )


@pytest.mark.parametrize("fault", ["process", "coverage"])
def test_failed_processor_never_commits_success_or_retries(monkeypatch, tmp_path, fault):
    _command_value, _review, pointer, _prepared, calls = _publication_fixture(monkeypatch)
    invocations = []

    def process(*_args):
        invocations.append(1)
        if fault == "process":
            raise ValueError("NATIVE_PDF_RENDER_OBSERVATION_TIMEOUT")
        return ()

    with pytest.raises(ValueError):
        publication.materialize_and_publish_source_pdf_crops(
            object(),
            object(),
            pointer,
            workspace=tmp_path / "failed",
            created_at=datetime(2026, 10, 4, 16, tzinfo=UTC),
            execution_source_commit="b" * 40,
            process=process,
        )
    assert invocations == [1] and calls == []
    assert not (tmp_path / "failed/manifests/science-source-pdf-crop-set.json").exists()


def test_canonical_replay_checks_pointers_and_bytes_without_pdf_or_renderer(monkeypatch, tmp_path):
    _command_value, _review, pointer, _prepared, _calls = _publication_fixture(monkeypatch)
    result = publication.materialize_and_publish_source_pdf_crops(
        object(),
        object(),
        pointer,
        workspace=tmp_path / "source",
        created_at=datetime(2026, 10, 4, 16, tzinfo=UTC),
        execution_source_commit="b" * 40,
        process=lambda request, _raw: processing.parse_native_source_pdf_render_response(
            request, _packet(request)
        ),
    )
    set_raw = content_json_bytes(result.crop_set.model_dump(mode="json"))
    set_pointer = _pointer(
        set_raw, SOURCE_PDF_CROP_SET_SCHEMA_REF, "science-source-pdf-crop-set", index=20
    )
    command_raw = content_json_bytes(_command_value.model_dump(mode="json"))

    def metadata(_engine, target, *, maximum_bytes):
        assert target.media_type == "application/json"
        return set_raw if target == set_pointer else command_raw

    def png_batch(_engine, reads):
        assert all(
            r.pointer.media_type == "image/png"
            and r.pointer.artifact_revision_id == set_pointer.artifact_revision_id
            for r in reads
        )
        return tuple((tmp_path / "source" / r.pointer.member_path).read_bytes() for r in reads)

    monkeypatch.setattr(publication, "resolve_control_artifact_member", metadata)
    monkeypatch.setattr(publication, "resolve_control_artifact_members", png_batch)
    monkeypatch.setattr(
        publication, "iter_source_pdf_crop_payloads", lambda *_: pytest.fail("PDF read")
    )
    monkeypatch.setattr(
        publication, "process_source_pdf_crops", lambda *_: pytest.fail("renderer replayed")
    )
    assert publication.replay_published_source_pdf_crops(object(), set_pointer) == result.crop_set
    monkeypatch.setattr(publication, "resolve_control_artifact_members", lambda *_: (b"broken",))
    with pytest.raises(ValueError, match="PNG_HASH_MISMATCH"):
        publication.replay_published_source_pdf_crops(object(), set_pointer)


def _synthetic_pdf(rotation=0):
    stream = b"0 0 0 RG 1 w 30 50 90 100 re S 20 20 m 150 200 l S\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200.5 250.5] "
            f"/Rotate {rotation} /Resources << >> /Contents 4 0 R >>"
        ).encode(),
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"endstream",
    ]
    raw, offsets = b"%PDF-1.4\n%" + b"x" * 1024 + b"\n", [0]
    for index, value in enumerate(objects, 1):
        offsets.append(len(raw))
        raw += f"{index} 0 obj\n".encode() + value + b"\nendobj\n"
    xref = len(raw)
    raw += b"xref\n0 5\n0000000000 65535 f \n"
    raw += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    return raw + f"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


@pytest.mark.native_pdf_toolchain
@pytest.mark.skipif(
    os.environ.get("EOM_NATIVE_PDF_TOOLCHAIN_TESTS") != "1",
    reason="opt-in synthetic Poppler CPU test",
)
@pytest.mark.parametrize("rotation", [0, 90])
def test_actual_native_clip_equals_full_render_with_rotation_and_fractional_page(
    monkeypatch, rotation
):
    request, _, _ = _request(monkeypatch)
    pdf = _synthetic_pdf(rotation)
    value = request.model_dump(mode="json")
    digest = _sha(pdf)
    document = "sciencedoc_" + digest[7:39]
    value["source"].update(document_id=document, bytes=len(pdf), page_count=1)
    value["source"]["pdf"]["sha256"] = digest
    region = value["regions"][0]
    region.update(
        physical_page=1,
        page_width_px=501 if rotation else 401,
        page_height_px=401 if rotation else 501,
        pixel_box=[40, 80, 200, 280],
    )
    region["source_page"]["member_path"] = f"pages/{document}/page-1.png"
    value["renderer"]["sha256"] = _sha(Path("/usr/bin/pdftoppm").read_bytes())
    value["request_sha256"] = content_sha256(
        {k: v for k, v in value.items() if k != "request_sha256"}
    )
    request = NativeSourcePdfRenderRequest.model_validate(value)
    outputs = processing.parse_native_source_pdf_render_response(
        request, worker.render_native_source_pdf(request, pdf)
    )
    full = subprocess.run(
        ["/usr/bin/pdftoppm", "-singlefile", "-r", "576", "-png", "-"],
        input=pdf,
        capture_output=True,
        check=True,
        timeout=15,
    ).stdout
    with Image.open(io.BytesIO(full)) as image, Image.open(io.BytesIO(outputs[0].payload)) as crop:
        assert crop.tobytes() == image.crop((160, 320, 800, 1120)).tobytes()
    assert len(outputs) == 1
