from __future__ import annotations

import binascii
import hashlib
import json
import stat
import struct
import zlib
from copy import deepcopy
from pathlib import Path

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator.codex_compatibility_probe import (
    COMPATIBILITY_PROMPT,
    compatibility_output_schema,
    compatibility_probe_input,
    compatibility_probe_prompt,
    materialize_compatibility_inputs,
    synthetic_probe_png,
    validate_probe_result,
)
from eom_workflow.codex_compatibility import CodexCompatibilityInvocation
from eom_workflow.control_schemas import load_control_schema, validate_control_contract
from jsonschema import Draft202012Validator, ValidationError


def _invocation(
    *, case_digit: str = "2", image: bytes | None = None
) -> CodexCompatibilityInvocation:
    body = {
        "schema_version": "codex-compatibility-invocation/1.0",
        "run_id": "codexcompat_" + "1" * 32,
        "case_id": "compatcase_" + case_digit * 32,
        "request_sha256": "sha256:" + "3" * 64,
        "job_id": "job_" + "4" * 32,
        "model": "gpt-6.1-sol",
        "reasoning_effort": "high",
        "image_sha256": "sha256:"
        + hashlib.sha256(synthetic_probe_png() if image is None else image).hexdigest(),
    }
    return CodexCompatibilityInvocation.model_validate(
        {**body, "invocation_sha256": content_sha256(body)}
    )


def _result(invocation: CodexCompatibilityInvocation) -> dict[str, object]:
    return {
        "schema_version": "codex-compatibility-probe-result/1.0",
        "run_id": invocation.run_id,
        "case_id": invocation.case_id,
        "request_sha256": invocation.request_sha256,
        "arithmetic_sum": 43,
        "rectangle_count": 1,
        "outline_circle_count": 1,
        "left_shape": "square",
        "right_shape": "circle",
    }


def test_output_schema_pins_nonce_but_does_not_supply_task_answers() -> None:
    invocation = _invocation()
    original = load_control_schema("codex-compatibility-probe-result")
    before = content_sha256(original)

    schema = compatibility_output_schema(invocation)

    Draft202012Validator.check_schema(schema)
    properties = schema["properties"]
    assert isinstance(properties, dict)
    for name in ("run_id", "case_id", "request_sha256"):
        assert properties[name]["const"] == getattr(invocation, name)
    for name in (
        "arithmetic_sum",
        "rectangle_count",
        "outline_circle_count",
        "left_shape",
        "right_shape",
    ):
        assert "const" not in properties[name]
    deliberately_wrong = {**_result(invocation), "arithmetic_sum": 44, "left_shape": "triangle"}
    Draft202012Validator(schema).validate(deliberately_wrong)
    assert content_sha256(load_control_schema("codex-compatibility-probe-result")) == before


def test_each_output_schema_uses_its_own_nonce_without_mutating_another() -> None:
    first = _invocation()
    second = _invocation(case_digit="5")
    first_schema = compatibility_output_schema(first)
    second_schema = compatibility_output_schema(second)

    Draft202012Validator(first_schema).validate(_result(first))
    Draft202012Validator(second_schema).validate(_result(second))
    with pytest.raises(ValidationError, match="expected"):
        Draft202012Validator(first_schema).validate(_result(second))


def test_native_output_projection_has_explicit_types_and_preserves_canonical_contract() -> None:
    invocation = _invocation()
    canonical = load_control_schema("codex-compatibility-probe-result")
    before = content_sha256(canonical)
    expected = deepcopy(canonical)
    for name in ("schema_version", "left_shape", "right_shape"):
        assert "type" not in canonical["properties"][name]
        expected["properties"][name]["type"] = "string"
    for name in ("run_id", "case_id", "request_sha256"):
        expected["properties"][name]["const"] = getattr(invocation, name)

    native = compatibility_output_schema(invocation)

    assert native == expected
    assert native["type"] == "object" and native["additionalProperties"] is False
    assert set(native["required"]) == set(native["properties"])
    assert all("type" in value for value in native["properties"].values())
    assert content_sha256(load_control_schema("codex-compatibility-probe-result")) == before
    # The projection supplies task types, not task answers: even wrong facts still
    # require application validation after schema-constrained generation.
    wrong_facts = {**_result(invocation), "arithmetic_sum": 44, "left_shape": "triangle"}
    Draft202012Validator(canonical).validate(wrong_facts)
    Draft202012Validator(native).validate(wrong_facts)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "another-result/1.0"),
        ("schema_version", None),
        ("left_shape", "ellipse"),
        ("left_shape", 1),
        ("right_shape", "ellipse"),
        ("right_shape", None),
    ],
)
def test_native_string_projection_preserves_wire_const_and_enum_rejections(
    field: str, value: object
) -> None:
    invocation = _invocation()
    document = {**_result(invocation), field: value}

    for schema in (
        load_control_schema("codex-compatibility-probe-result"),
        compatibility_output_schema(invocation),
    ):
        with pytest.raises(ValidationError):
            Draft202012Validator(schema).validate(document)


def test_png_is_deterministic_valid_binary_with_expected_dimensions_and_pixels() -> None:
    image = synthetic_probe_png()
    assert image == synthetic_probe_png()
    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(image) < 4096
    offset = 8
    chunks: list[tuple[bytes, bytes]] = []
    while offset < len(image):
        length = struct.unpack(">I", image[offset : offset + 4])[0]
        kind = image[offset + 4 : offset + 8]
        payload = image[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", image[offset + 8 + length : offset + 12 + length])[0]
        assert expected_crc == binascii.crc32(kind + payload) & 0xFFFFFFFF
        chunks.append((kind, payload))
        offset += 12 + length
    assert offset == len(image)
    assert [kind for kind, _ in chunks] == [b"IHDR", b"IDAT", b"IEND"]
    assert struct.unpack(">IIBBBBB", chunks[0][1]) == (128, 96, 8, 0, 0, 0, 0)
    pixels = zlib.decompress(chunks[1][1])
    assert len(pixels) == (128 + 1) * 96
    assert all(pixels[y * 129] == 0 for y in range(96))

    def pixel(x: int, y: int) -> int:
        return pixels[y * 129 + x + 1]

    assert pixel(32, 48) == 0  # Filled left square.
    assert pixel(16, 32) == 0 and pixel(47, 63) == 0
    assert pixel(15, 32) == 255 and pixel(48, 63) == 255
    assert pixel(96, 48) == 255  # Hollow right circle.
    assert pixel(96, 28) == 0 and pixel(76, 48) == 0
    assert pixel(96, 26) == 255
    assert pixel(0, 0) == pixel(127, 95) == 255


def test_prompt_asks_for_observation_without_revealing_correct_answers() -> None:
    prompt = COMPATIBILITY_PROMPT.lower()
    assert "attached png" in prompt and "add the two integers" in prompt
    assert "do not use tools" in prompt
    for leaked_answer in (
        "43",
        '"rectangle_count": 1',
        '"outline_circle_count": 1',
        '"left_shape": "square"',
        '"right_shape": "circle"',
        "square on the left",
        "circle on the right",
    ):
        assert leaked_answer not in prompt


def test_no_tools_stdin_contains_the_exact_task_input_not_its_answers() -> None:
    invocation = _invocation()
    prompt = compatibility_probe_prompt(invocation)
    instructions, payload = prompt.split("\nDiagnostic input JSON:\n", 1)
    assert json.loads(payload) == compatibility_probe_input(invocation)
    assert json.loads(payload)["addends"] == [17, 26]
    assert "Do not open worker-input.json" in instructions
    assert "Do not use tools" in instructions
    assert '"arithmetic_sum"' not in payload
    assert '"left_shape"' not in payload


def test_correct_probe_result_preserves_exact_identity() -> None:
    invocation = _invocation()

    result = validate_probe_result(_result(invocation), invocation)

    assert result.run_id == invocation.run_id
    assert result.case_id == invocation.case_id
    assert result.request_sha256 == invocation.request_sha256
    assert result.arithmetic_sum == 43


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("run_id", "codexcompat_" + "6" * 32),
        ("case_id", "compatcase_" + "6" * 32),
        ("request_sha256", "sha256:" + "6" * 64),
    ],
)
def test_result_cannot_replay_another_nonce_or_request_hash(field: str, value: str) -> None:
    invocation = _invocation()
    document = {**_result(invocation), field: value}
    validate_control_contract("codex-compatibility-probe-result", document)

    with pytest.raises(ValueError, match="identity"):
        validate_probe_result(document, invocation)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("arithmetic_sum", 42),
        ("rectangle_count", 0),
        ("outline_circle_count", 2),
        ("left_shape", "circle"),
        ("right_shape", "square"),
    ],
)
def test_schema_valid_but_incorrect_facts_fail(field: str, value: object) -> None:
    invocation = _invocation()
    document = {**_result(invocation), field: value}
    validate_control_contract("codex-compatibility-probe-result", document)

    with pytest.raises(ValueError, match="incorrect"):
        validate_probe_result(document, invocation)


def test_materialization_writes_only_exact_small_local_inputs(tmp_path: Path) -> None:
    image = synthetic_probe_png()
    invocation = _invocation(image=image)

    materialize_compatibility_inputs(tmp_path, invocation, image)

    assert {path.name for path in tmp_path.iterdir()} == {
        "codex-compatibility-invocation.json",
        "compatibility-input.png",
        "AGENTS.md",
    }
    assert (tmp_path / "compatibility-input.png").read_bytes() == image
    document = json.loads((tmp_path / "codex-compatibility-invocation.json").read_bytes())
    assert document == invocation.model_dump(mode="json")
    validate_control_contract("codex-compatibility-invocation", document)
    assert "execution-plan" not in (tmp_path / "AGENTS.md").read_text()
    for path in tmp_path.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o640
        assert path.stat().st_gid == tmp_path.stat().st_gid


def test_image_hash_mismatch_fails_before_any_materialization(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="pinned"):
        materialize_compatibility_inputs(tmp_path, _invocation(), b"different image")

    assert not tuple(tmp_path.iterdir())


def test_materialization_does_not_overwrite_existing_or_symlinked_input(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.write_bytes(b"retain")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "codex-compatibility-invocation.json").symlink_to(outside)

    with pytest.raises(FileExistsError):
        materialize_compatibility_inputs(workspace, _invocation(), synthetic_probe_png())

    assert outside.read_bytes() == b"retain"
    assert not (workspace / "compatibility-input.png").exists()
