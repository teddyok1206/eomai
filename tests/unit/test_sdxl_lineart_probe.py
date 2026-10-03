from __future__ import annotations

import copy
import hashlib
import io
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from eom_image_contracts import (
    LocalImageRuntime,
    LocalImageSdxlLineartProbeCommand,
    LocalImageSdxlLineartProbeResult,
    LocalImageSdxlLineartPromptPolicy,
    content_json_bytes,
    content_sha256,
    text_sha256,
    validate_contract,
    validate_sdxl_lineart_probe_result,
)
from eom_image_provider import sdxl_lineart_probe as probe
from eom_image_provider.provider import GeneratedBackground, ProviderError
from eom_image_provider.sdxl_model_resolution import ResolvedSdxlStack
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from PIL import Image, ImageDraw
from pydantic import ValidationError

from tests.unit.test_sdxl_lineart_stack_contract import _stack


def _png(*, size: tuple[int, int] = (40, 20), mode: str = "RGB") -> bytes:
    image = Image.new(mode, size, "white")
    ImageDraw.Draw(image).rectangle((4, 4, size[0] - 4, size[1] - 4), outline="black")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _sha(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _policy(cases: object) -> bytes:
    pointer = {
        "artifact_id": "artifact_" + "d" * 32,
        "artifact_revision_id": "rev_" + "e" * 32,
        "member_path": "manifest.json",
        "schema_ref": "eom://schemas/image-provider/test/1.0",
        "media_type": "application/json",
        "sha256": _sha(b"fixture manifest"),
    }
    return content_json_bytes(
        {
            "schema_version": "local-image-sdxl-lineart-prompt-policy/1.0",
            "crop_set": pointer,
            "training_authorization": pointer,
            "experiment_authorization": {
                "approved_at": "2026-10-03T06:00:00Z",
                "approved_by": "fixture.operator",
                "approval_message_sha256": _sha(b"fixture approval"),
                "permitted_uses": ["INTERNAL_SDXL_COMPARISON"],
                "external_export": "FORBIDDEN",
                "automatic_activation": "FORBIDDEN",
            },
            "experiment_partition": "TRAIN",
            "catalog_policy_revision": "local-gpu-image-prompt-policy/1.7",
            "sources": [
                {"role": role, "source_name": role + ".md", "sha256": _sha(role.encode())}
                for role in ("AUTHORING_GUIDANCE", "EDITOR_HANDOFF", "ILLUSTRATION_GUIDANCE")
            ],
            "cases": cases,
        }
    )


def _command() -> dict[str, object]:
    stack = _stack()
    pointer = {
        "artifact_id": "artifact_" + "a" * 32,
        "artifact_revision_id": "rev_" + "b" * 32,
        "member_path": "reference.png",
        "schema_ref": "eom://schemas/image-provider/local-image-science-visual-crop/1.0",
        "media_type": "image/png",
        "sha256": _sha(_png()),
    }
    case = {
        "depiction_key": "TEST_RECTANGLE",
        "reference_image": pointer,
        "reference_width_px": 40,
        "reference_height_px": 20,
        "prompt_en": "Black and white scientific line drawing of one rectangle.",
        "negative_prompt_en": "text, watermark, color, decorative background",
        "seeds": [1, 2],
    }
    case["prompt_sha256"] = text_sha256(str(case["prompt_en"]))
    case["negative_prompt_sha256"] = text_sha256(str(case["negative_prompt_en"]))
    case_id = "imgsdxlcase_" + content_sha256(case)[7:39]
    case["case_id"] = case_id
    case["staged_member_path"] = f"inputs/{case_id}.png"
    value = {
        "schema_version": "local-image-sdxl-lineart-probe-command/1.0",
        "run_id": "imgsdxlproberun_" + "c" * 32,
        "created_at": "2026-10-03T06:00:00Z",
        "model": {
            key: stack[key]
            for key in (
                "model_id",
                "model_revision_id",
                "manifest_sha256",
                "provider_family",
                "runtime_contract_version",
            )
        },
        "prompt_policy": {
            **pointer,
            "member_path": "policy.json",
            "schema_ref": "eom://schemas/image-provider/local-image-sdxl-lineart-prompt-policy/1.0",
            "media_type": "application/json",
            "sha256": _sha(_policy([case])),
        },
        "style_track": "OBJECT_LINE_ART",
        "conditioning_policy": "FIT_GRAYSCALE_INVERT_832X512/1.0",
        "inference_steps": 20,
        "guidance_scale": 7.0,
        "adapter_conditioning_scale": 0.8,
        "budget": {"maximum_duration_ms": 30000, "maximum_peak_gpu_memory_bytes": 2**30},
        "cases": [case],
    }
    return {**value, "command_sha256": content_sha256(value)}


class FakeBackend:
    def __init__(self, *, fault: str | None = None) -> None:
        self.fault = fault
        self.opens = 0
        self.calls = 0

    @contextmanager
    def open(self, _stack: ResolvedSdxlStack) -> Iterator[FakeBackend]:
        self.opens += 1
        yield self

    def generate(self, **_kwargs: object) -> GeneratedBackground:
        self.calls += 1
        if self.fault == "second" and self.calls == 2:
            raise ProviderError("SDXL_PROBE_OOM")
        if self.fault == "unexpected":
            raise ProviderError("INTERNAL_UNSUPPORTED_CODE")
        return GeneratedBackground(
            png_bytes=_png(size=(832, 512)),
            runtime=LocalImageRuntime(
                python_version="3.11.14",
                torch_version="2.7.1",
                diffusers_version="0.35.2",
                transformers_version="4.56.2",
                cuda_version="12.8",
                gpu_name="fixture GPU",
                compute_capability="12.0",
                peak_gpu_memory_bytes=100 + self.calls,
            ),
        )


def _workspace(tmp_path: Path, command: LocalImageSdxlLineartProbeCommand) -> Path:
    tmp_path.chmod(0o700)
    (tmp_path / "inputs").mkdir(mode=0o700)
    (tmp_path / "inputs/prompt-policy.json").write_bytes(
        _policy([case.model_dump(mode="json") for case in command.cases])
    )
    (tmp_path / command.cases[0].staged_member_path).write_bytes(_png())
    (tmp_path / "command.json").write_bytes(content_json_bytes(command.model_dump(mode="json")))
    for path in (tmp_path / "inputs").iterdir():
        path.chmod(0o644)
    (tmp_path / "command.json").chmod(0o644)
    return tmp_path


def _run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: FakeBackend
) -> tuple[
    LocalImageSdxlLineartProbeCommand,
    LocalImageSdxlLineartProbeResult,
]:
    command = LocalImageSdxlLineartProbeCommand.model_validate(_command())
    _workspace(tmp_path, command)
    monkeypatch.setattr(probe, "resolve_sdxl_stack", lambda *a, **k: object())
    result = probe.run_sdxl_lineart_probe(
        command=command,
        model_store_root=tmp_path,
        workspace=tmp_path,
        backend=backend,
    )
    return command, result


def test_command_schema_typed_hash_parity_and_release_members() -> None:
    value = _command()
    validate_contract("sdxl-lineart-probe-command", value)
    assert LocalImageSdxlLineartProbeCommand.model_validate(value).model_dump(mode="json") == value
    root = Path(__file__).resolve().parents[2]
    for kind in ("command", "result"):
        member = f"local-image-sdxl-lineart-probe-{kind}-v1.schema.json"
        assert (root / "schemas/image-provider" / member).read_bytes() == (
            root / "packages/image_contracts/eom_image_contracts/schemas" / member
        ).read_bytes()


@pytest.mark.parametrize(
    "fault", [None, "missing_source", "duplicate_source", "scope", "export", "partition"]
)
def test_prompt_provenance_keeps_original_permission_and_explicit_experiment_scope(
    fault: str | None,
) -> None:
    value = json.loads(_policy(_command()["cases"]))
    if fault == "missing_source":
        value["sources"].pop()
    elif fault == "duplicate_source":
        value["sources"][2] = value["sources"][1]
    elif fault == "scope":
        value["experiment_authorization"]["permitted_uses"] = ["INTERNAL_SSD1B_LORA_TRAINING"]
    elif fault == "export":
        value["experiment_authorization"]["external_export"] = "ALLOWED"
    elif fault == "partition":
        value["experiment_partition"] = "HOLDOUT"
    if fault is None:
        validate_contract("sdxl-lineart-prompt-policy", value)
        assert (
            LocalImageSdxlLineartPromptPolicy.model_validate(value).model_dump(mode="json") == value
        )
    else:
        with pytest.raises(ValidationError):
            LocalImageSdxlLineartPromptPolicy.model_validate(value)


def test_semantic_prompt_policy_mismatch_fails_before_model_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = _command()
    policy = json.loads(_policy(value["cases"]))
    policy["cases"][0]["reference_width_px"] += 1
    case = policy["cases"][0]
    identity = content_sha256(
        {key: item for key, item in case.items() if key not in {"case_id", "staged_member_path"}}
    )[7:39]
    case["case_id"] = "imgsdxlcase_" + identity
    case["staged_member_path"] = "inputs/" + case["case_id"] + ".png"
    raw = content_json_bytes(policy)
    value["prompt_policy"]["sha256"] = _sha(raw)
    value["command_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "command_sha256"}
    )
    command = LocalImageSdxlLineartProbeCommand.model_validate(value)
    _workspace(tmp_path, command)
    (tmp_path / "inputs/prompt-policy.json").write_bytes(raw)
    monkeypatch.setattr(
        probe, "resolve_sdxl_stack", lambda *a, **k: pytest.fail("model resolution must not run")
    )
    backend = FakeBackend()
    result = probe.run_sdxl_lineart_probe(
        command=command, model_store_root=tmp_path, workspace=tmp_path, backend=backend
    )
    assert result.status == "FAILED" and result.error_code == "SDXL_PROBE_INPUT_INVALID"
    assert backend.calls == 0 and backend.opens == 0


@pytest.mark.parametrize(
    "fault", ["seed", "prompt", "member", "case", "timestamp", "hash", "oversized"]
)
def test_command_rejects_mismatched_or_unbounded_values(fault: str) -> None:
    value = copy.deepcopy(_command())
    if fault == "timestamp":
        value["created_at"] = "2026-10-03T06:00:00+09:00"
    elif fault == "hash":
        value["command_sha256"] = "sha256:" + "f" * 64
    elif fault == "oversized":
        value["cases"] *= 7
    else:
        case = value["cases"][0]
        case[
            {
                "seed": "seeds",
                "prompt": "prompt_en",
                "member": "staged_member_path",
                "case": "case_id",
            }[fault]
        ] = {
            "seed": [1, 1],
            "prompt": "silently changed prompt",
            "member": "inputs/../escape.png",
            "case": "imgsdxlcase_" + "f" * 32,
        }[fault]
    with pytest.raises(ValidationError):
        LocalImageSdxlLineartProbeCommand.model_validate(value)


def test_polarity_geometry_and_publication_are_explicit() -> None:
    raw = _png()
    conditioning = probe.lineart_conditioning(raw, expected_size=(40, 20))
    with Image.open(io.BytesIO(conditioning)) as image:
        assert image.size == (832, 512) and image.mode == "RGB"
        assert image.getpixel((0, 0)) == (0, 0, 0)
        assert image.getpixel((416, 256)) == (0, 0, 0)
        assert image.getextrema()[0][1] == 255
    with pytest.raises(ProviderError, match="INPUT_INVALID"):
        probe.lineart_conditioning(raw, expected_size=(41, 20))


def test_frozen_budget_cannot_exceed_isolated_hard_timeout() -> None:
    value = _command()
    value["budget"]["maximum_duration_ms"] = 1_800_001
    with pytest.raises(ValidationError):
        LocalImageSdxlLineartProbeCommand.model_validate(value)
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("sdxl-lineart-probe-command", value)


def test_one_model_load_full_coverage_and_hash_checked_zero_call_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = FakeBackend()
    command, result = _run(tmp_path, monkeypatch, backend)
    validate_contract("sdxl-lineart-probe-result", result.model_dump(mode="json"))
    validate_sdxl_lineart_probe_result(command, result)
    assert result.status == "SUCCEEDED" and backend.opens == 1 and backend.calls == 2
    assert result.runtime.peak_gpu_memory_bytes == 102
    with Image.open(tmp_path / result.outputs[0].member_path) as image:
        assert image.mode == "L" and image.size == (800, 500)
    assert probe.load_sdxl_probe_command(tmp_path, tmp_path / "command.json") == command
    replay = probe.run_sdxl_lineart_probe(
        command=command,
        model_store_root=tmp_path,
        workspace=tmp_path,
        backend=backend,
    )
    assert replay == result and backend.calls == 2
    (tmp_path / result.outputs[0].member_path).write_bytes(b"changed")
    with pytest.raises(ProviderError, match="HASH_MISMATCH"):
        probe.run_sdxl_lineart_probe(
            command=command,
            model_store_root=tmp_path,
            workspace=tmp_path,
            backend=backend,
        )
    assert backend.calls == 2


@pytest.mark.parametrize("fault", ["second", "unexpected"])
def test_partial_failure_is_terminal_and_does_not_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    backend = FakeBackend(fault=fault)
    command, result = _run(tmp_path, monkeypatch, backend)
    assert result.status == "FAILED"
    assert result.error_code == (
        "SDXL_PROBE_OOM" if fault == "second" else "SDXL_PROBE_EXEC_FAILED"
    )
    validate_sdxl_lineart_probe_result(command, result)
    calls = backend.calls
    assert (
        probe.run_sdxl_lineart_probe(
            command=command,
            model_store_root=tmp_path,
            workspace=tmp_path,
            backend=backend,
        )
        == result
    )
    assert backend.calls == calls


def test_reference_hash_failure_occurs_before_model_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    command = LocalImageSdxlLineartProbeCommand.model_validate(_command())
    _workspace(tmp_path, command)
    (tmp_path / command.cases[0].staged_member_path).write_bytes(b"changed")
    monkeypatch.setattr(probe, "resolve_sdxl_stack", lambda *a, **k: object())
    backend = FakeBackend()
    result = probe.run_sdxl_lineart_probe(
        command=command,
        model_store_root=tmp_path,
        workspace=tmp_path,
        backend=backend,
    )
    assert result.status == "FAILED" and result.error_code == "SDXL_PROBE_HASH_MISMATCH"
    assert backend.opens == backend.calls == 0


def test_unreceipted_outputs_and_symlinked_commands_fail_closed(tmp_path: Path) -> None:
    command = LocalImageSdxlLineartProbeCommand.model_validate(_command())
    _workspace(tmp_path, command)
    (tmp_path / "outputs").mkdir(mode=0o700)
    with pytest.raises(ProviderError, match="OUTPUT_INVALID"):
        probe.run_sdxl_lineart_probe(
            command=command,
            model_store_root=tmp_path,
            workspace=tmp_path,
            backend=FakeBackend(),
        )
    (tmp_path / "command.json").unlink()
    (tmp_path / "command.json").symlink_to(tmp_path / "inputs/prompt-policy.json")
    with pytest.raises(ProviderError, match="INPUT_INVALID"):
        probe.load_sdxl_probe_command(tmp_path, tmp_path / "command.json")
