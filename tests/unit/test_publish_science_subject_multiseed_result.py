from __future__ import annotations

import struct
import zlib
from pathlib import Path

from eom_identifiers import sha256_bytes
from eom_image_contracts import (
    LocalImageScienceVisualSubjectMultiseedResult,
    content_json_bytes,
    content_sha256,
)

from scripts.image_trainer import publish_science_subject_multiseed_result as publication
from tests.unit.test_science_visual_subject_benchmark_contracts import (
    NOW,
    _multiseed_command,
    _multiseed_initials,
    _multiseed_plan,
    _multiseed_result,
)


def _png(width: int = 800, height: int = 500) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    rows = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows, level=9))
        + chunk(b"IEND", b"")
    )


def test_subject_multiseed_publication_closes_exact_png_file_set(tmp_path: Path) -> None:
    inventory, initial_plan, initial_review = _multiseed_initials()
    plan = _multiseed_plan(inventory, initial_plan, initial_review)
    command = _multiseed_command(plan)
    initial = _multiseed_result(plan, command)
    png = _png()
    outputs = [
        {
            **output.model_dump(mode="json"),
            "bytes": len(png),
            "sha256": sha256_bytes(png),
        }
        for output in initial.outputs
    ]
    body = {
        **initial.model_dump(mode="json", exclude={"result_sha256"}),
        "outputs": outputs,
        "started_at": NOW.isoformat().replace("+00:00", "Z"),
        "completed_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    result = LocalImageScienceVisualSubjectMultiseedResult.model_validate(
        {**body, "result_sha256": content_sha256(body)}
    )
    workspace = tmp_path / command.run_id
    inputs = workspace / "inputs"
    outputs_root = workspace / "outputs"
    inputs.mkdir(parents=True)
    outputs_root.mkdir()
    (workspace / "command.json").write_bytes(content_json_bytes(command.model_dump(mode="json")))
    (inputs / "subject-multiseed-plan.json").write_bytes(
        content_json_bytes(plan.model_dump(mode="json"))
    )
    (workspace / "result.json").write_bytes(
        content_json_bytes(result.model_dump(mode="json")) + b"\n"
    )
    for output in result.outputs:
        (workspace / output.relative_path).write_bytes(png)
    for path in workspace.rglob("*"):
        if path.is_file():
            path.chmod(0o600)

    loaded_command, loaded_plan, loaded_result, result_payload = publication._load(workspace)
    members = publication._members(workspace, loaded_result, result_payload)

    assert loaded_command == command
    assert loaded_plan == plan
    assert len(members) == len(result.outputs) + 1
    assert publication._png_dimensions(png) == (800, 500)


def test_subject_multiseed_publication_rejects_extra_output(tmp_path: Path) -> None:
    inventory, initial_plan, initial_review = _multiseed_initials()
    plan = _multiseed_plan(inventory, initial_plan, initial_review)
    command = _multiseed_command(plan)
    result = _multiseed_result(plan, command)
    workspace = tmp_path / command.run_id
    outputs_root = workspace / "outputs"
    outputs_root.mkdir(parents=True)
    (outputs_root / "unexpected.png").write_bytes(_png())

    try:
        publication._members(workspace, result, b"{}\n")
    except publication.ScienceSubjectMultiseedPublicationError as exc:
        assert str(exc) == "SCIENCE_SUBJECT_MULTISEED_OUTPUT_INVALID"
    else:
        raise AssertionError("extra output must fail closed")
