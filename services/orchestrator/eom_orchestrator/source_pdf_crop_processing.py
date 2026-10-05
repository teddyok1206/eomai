"""Fixed isolated CPU process boundary for already-admitted native PDF frames."""

from __future__ import annotations

import hashlib
import io
import struct
import subprocess
import zipfile
import zlib

from eom_image_contracts import content_json_bytes
from eom_image_contracts.source_page_crops import ScienceSourcePageCropMember
from eom_image_contracts.source_pdf_crops import (
    NativeSourcePdfRenderRequest,
    NativeSourcePdfRenderResult,
    validate_native_source_pdf_render_result,
)
from eom_image_contracts.validation import validate_contract

from eom_orchestrator.source_page_crop_processing import ScienceSourcePageCropPixels

_PYTHON = "/srv/eom/conda/envs/eom-image-trainer/bin/python"
_MAX_PNG_BYTES = 8 * 1024**2
_MAX_METADATA_BYTES = 16 * 1024
_SANDBOX = (
    "NoNewPrivileges=yes",
    "PrivateTmp=yes",
    "PrivateNetwork=yes",
    "PrivateDevices=yes",
    "ProtectSystem=strict",
    "ProtectHome=yes",
    "ProtectKernelTunables=yes",
    "ProtectKernelModules=yes",
    "ProtectKernelLogs=yes",
    "ProtectControlGroups=yes",
    "RestrictSUIDSGID=yes",
    "LockPersonality=yes",
    "RestrictRealtime=yes",
    "CapabilityBoundingSet=",
    "AmbientCapabilities=",
    "RestrictAddressFamilies=AF_UNIX",
    "MemoryMax=1G",
    "TasksMax=32",
    "RuntimeMaxSec=45",
    "TimeoutStopSec=5",
    "UMask=0077",
    "InaccessiblePaths=/mnt/nas /home/eom/EOM /home/eom/EOMIS /etc/eom "
    "/root/.codex /srv/eom/worker-homes /var/run/docker.sock",
)


def _validate_png_chunks(raw: bytes, *, width: int, height: int) -> None:
    """Validate the complete bounded RGB stream, not just the header/hash or ZIP CRC."""
    offset, raster_size, idat_seen, ended = 8, 0, False, False
    maximum = (width * 3 + 1) * height
    decoder = zlib.decompressobj()
    while offset < len(raw):
        if offset + 12 > len(raw):
            raise ValueError("NATIVE_PDF_RENDER_PNG_INVALID")
        length = struct.unpack_from(">I", raw, offset)[0]
        kind = raw[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(raw) or (
            zlib.crc32(raw[offset + 4 : end - 4]) != struct.unpack_from(">I", raw, end - 4)[0]
        ):
            raise ValueError("NATIVE_PDF_RENDER_PNG_INVALID")
        data = raw[offset + 8 : end - 4]
        if kind == b"IHDR":
            if offset != 8 or length != 13:
                raise ValueError("NATIVE_PDF_RENDER_PNG_INVALID")
        elif kind == b"IDAT":
            if ended or decoder.eof:
                raise ValueError("NATIVE_PDF_RENDER_PNG_INVALID")
            idat_seen = True
            decoded = decoder.decompress(data, maximum + 1 - raster_size)
            stride = width * 3 + 1
            if any(
                decoded[index] > 4 for index in range((-raster_size) % stride, len(decoded), stride)
            ):
                raise ValueError("NATIVE_PDF_RENDER_PNG_INVALID")
            raster_size += len(decoded)
            if raster_size > maximum or decoder.unconsumed_tail or decoder.unused_data:
                raise ValueError("NATIVE_PDF_RENDER_PNG_INVALID")
        elif kind == b"IEND":
            if length != 0 or not idat_seen or end != len(raw):
                raise ValueError("NATIVE_PDF_RENDER_PNG_INVALID")
            ended = True
        else:
            # The installed worker emits only canonical Pillow RGB IHDR/IDAT/IEND.
            raise ValueError("NATIVE_PDF_RENDER_PNG_INVALID")
        offset = end
    if not ended or not decoder.eof or raster_size != maximum:
        raise ValueError("NATIVE_PDF_RENDER_PNG_INVALID")


def validate_native_source_pdf_crop_pixels(
    member: ScienceSourcePageCropMember, payload: bytes
) -> ScienceSourcePageCropPixels:
    """One media-admission rule for worker output and canonical read-only replay."""
    if len(payload) != member.size_bytes or (
        "sha256:" + hashlib.sha256(payload).hexdigest() != member.sha256
    ):
        raise ValueError("NATIVE_PDF_RENDER_PNG_HASH_MISMATCH")
    output = ScienceSourcePageCropPixels(
        member.selection_id, payload, member.width_px, member.height_px, member.perceptual_hash
    )
    _validate_png_chunks(payload, width=member.width_px, height=member.height_px)
    return output


def parse_native_source_pdf_render_response(
    request: NativeSourcePdfRenderRequest, payload: bytes
) -> tuple[ScienceSourcePageCropPixels, ...]:
    """Admit exact response closure and full PNG streams before canonical publication."""
    maximum = len(request.regions) * (_MAX_PNG_BYTES + 512) + _MAX_METADATA_BYTES
    if not 64 <= len(payload) <= maximum:
        raise ValueError("NATIVE_PDF_RENDER_RESPONSE_SIZE_INVALID")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            expected = {"crops/" + region.selection_id + ".png" for region in request.regions}
            expected.add("result.json")
            entries = archive.infolist()
            if (
                archive.comment
                or len(entries) != len(expected)
                or {entry.filename for entry in entries} != expected
                or any(
                    entry.flag_bits & 1
                    or entry.compress_type != zipfile.ZIP_STORED
                    or not 0
                    < entry.file_size
                    <= (_MAX_METADATA_BYTES if entry.filename == "result.json" else _MAX_PNG_BYTES)
                    for entry in entries
                )
            ):
                raise ValueError("NATIVE_PDF_RENDER_MEMBER_CLOSURE_INVALID")
            raw = archive.read("result.json")
            result = NativeSourcePdfRenderResult.model_validate_json(raw)
            if raw != content_json_bytes(result.model_dump(mode="json")):
                raise ValueError("NATIVE_PDF_RENDER_RESULT_NONCANONICAL")
            validate_native_source_pdf_render_result(request, result)
            outputs = []
            for member in result.members:
                image = archive.read(member.member_path)
                outputs.append(validate_native_source_pdf_crop_pixels(member, image))
            return tuple(outputs)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, struct.error, zlib.error) as exc:
        raise ValueError("NATIVE_PDF_RENDER_RESPONSE_INVALID") from exc


def process_source_pdf_crops(
    request: NativeSourcePdfRenderRequest, payload: bytes
) -> tuple[ScienceSourcePageCropPixels, ...]:
    """One deterministic unit per request; no automatic redispatch after unknown completion."""
    validate_contract("science-source-pdf-render-request", request.model_dump(mode="json"))
    request = NativeSourcePdfRenderRequest.model_validate(request.model_dump(mode="json"))
    if len(payload) != request.source.bytes or (
        "sha256:" + hashlib.sha256(payload).hexdigest() != request.source.pdf.sha256
    ):
        raise ValueError("NATIVE_PDF_RENDER_SOURCE_BYTES_MISMATCH")
    raw = content_json_bytes(request.model_dump(mode="json"))
    if len(raw) > _MAX_METADATA_BYTES:
        raise ValueError("NATIVE_PDF_RENDER_REQUEST_SIZE_INVALID")
    arguments = [
        "/usr/bin/systemd-run",
        "--quiet",
        "--wait",
        "--pipe",
        "--collect",
        "--unit=eom-image-native-pdf-" + request.request_sha256[7:31],
        "--uid=eom-image",
        "--gid=eom-image",
        "--service-type=exec",
    ]
    arguments.extend(flag for value in _SANDBOX for flag in ("--property", value))
    arguments.extend(
        [
            "--",
            _PYTHON,
            "-I",
            "-m",
            "eom_image_trainer.source_pdf_render",
            raw.decode("utf-8"),
        ]
    )
    try:
        completed = subprocess.run(
            arguments,
            input=payload,
            capture_output=True,
            check=False,
            timeout=55,
            env={"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"},
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("NATIVE_PDF_RENDER_OBSERVATION_TIMEOUT") from exc
    except OSError as exc:
        raise ValueError("NATIVE_PDF_RENDER_UNAVAILABLE") from exc
    if completed.returncode != 0 or len(completed.stderr) > 64 * 1024:
        raise ValueError("NATIVE_PDF_RENDER_PROCESS_FAILED")
    return parse_native_source_pdf_render_response(request, completed.stdout)
