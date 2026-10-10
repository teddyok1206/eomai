"""Deterministic diagnostic inputs and result validation, not item authoring."""

from __future__ import annotations

import binascii
import json
import os
import struct
import zlib
from copy import deepcopy
from pathlib import Path

from eom_workflow.codex_compatibility import (
    CodexCompatibilityInvocation,
    CodexCompatibilityProbeResult,
)
from eom_workflow.control_schemas import load_control_schema, validate_control_contract

COMPATIBILITY_PROMPT = """This is an EOM execution compatibility diagnostic, not item authoring.
Use the diagnostic input JSON below and the attached PNG. Return ONLY JSON matching the
provided output schema. Do not open worker-input.json or other files.
Copy the run_id, case_id, and request_sha256 from the input exactly. Add the two integers in the
input and return arithmetic_sum. Inspect the PNG pixels: return the count of filled rectangles
(including squares),
the count of outlined circles, and the shape on the left and right (square, circle, or triangle).
Do not use tools, search, PostgreSQL, NAS, external files, or another worker. Do not invent an
execution-plan ID. All required information is already in the input and attached image.
"""


def compatibility_probe_input(invocation: CodexCompatibilityInvocation) -> dict[str, object]:
    return {
        "run_id": invocation.run_id,
        "case_id": invocation.case_id,
        "request_sha256": invocation.request_sha256,
        "addends": [17, 26],
    }


def compatibility_probe_prompt(invocation: CodexCompatibilityInvocation) -> str:
    # The helper forwards prompt.txt as stdin. A no-tools probe cannot read a separate
    # input file, so supply the small immutable task value here without revealing answers.
    return (
        COMPATIBILITY_PROMPT
        + "\nDiagnostic input JSON:\n"
        + json.dumps(compatibility_probe_input(invocation), sort_keys=True, separators=(",", ":"))
    )


def synthetic_probe_png() -> bytes:
    """A filled square on the left and a hollow circle on the right, grayscale PNG."""

    width, height = 128, 96
    pixels = bytearray()
    for y in range(height):
        pixels.append(0)  # PNG no-filter scanline.
        for x in range(width):
            radius_squared = (x - 96) ** 2 + (y - 48) ** 2
            black = (16 <= x < 48 and 32 <= y < 64) or 18**2 <= radius_squared <= 21**2
            pixels.append(0 if black else 255)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(pixels)))
        + chunk(b"IEND", b"")
    )


def compatibility_output_schema(invocation: CodexCompatibilityInvocation) -> dict[str, object]:
    """Pin identities, while leaving task answers unconstrained by the schema."""

    schema = deepcopy(load_control_schema("codex-compatibility-probe-result"))
    # Native strict output requires an explicit type even when const/enum already
    # restricts every accepted value to a string. Preserve the released wire schema.
    for key in ("schema_version", "left_shape", "right_shape"):
        schema["properties"][key]["type"] = "string"
    for key in ("run_id", "case_id", "request_sha256"):
        schema["properties"][key]["const"] = getattr(invocation, key)
    return schema


def validate_probe_result(
    document: object, invocation: CodexCompatibilityInvocation
) -> CodexCompatibilityProbeResult:
    validate_control_contract("codex-compatibility-probe-result", document)
    result = CodexCompatibilityProbeResult.model_validate(document)
    if any(
        getattr(result, key) != getattr(invocation, key)
        for key in ("run_id", "case_id", "request_sha256")
    ):
        raise ValueError("compatibility result identity differs from its invocation")
    if (
        result.arithmetic_sum != 43
        or result.rectangle_count != 1
        or result.outline_circle_count != 1
        or result.left_shape != "square"
        or result.right_shape != "circle"
    ):
        raise ValueError("compatibility task answers are incorrect")
    return result


def materialize_compatibility_inputs(
    workspace: Path, invocation: CodexCompatibilityInvocation, image: bytes
) -> None:
    """One explicit local materialization; never accepts an arbitrary external image path."""

    import hashlib

    if "sha256:" + hashlib.sha256(image).hexdigest() != invocation.image_sha256:
        raise ValueError("diagnostic image differs from the pinned invocation")
    group_id = workspace.stat().st_gid
    files = {
        "codex-compatibility-invocation.json": invocation.model_dump_json().encode() + b"\n",
        "compatibility-input.png": image,
        "AGENTS.md": (
            b"# Maintenance compatibility probe\n"
            b"This is a synthetic diagnostic only. Follow prompt.txt; use no tools. "
            b"Return only the structured result. Do not perform authoring, review, "
            b"registration, or persistence.\n"
        ),
    }
    validate_control_contract(
        "codex-compatibility-invocation", json.loads(invocation.model_dump_json())
    )
    for name, payload in files.items():
        descriptor = os.open(
            workspace / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640
        )
        with os.fdopen(descriptor, "wb") as stream:
            os.fchown(stream.fileno(), -1, group_id)
            os.fchmod(stream.fileno(), 0o640)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
