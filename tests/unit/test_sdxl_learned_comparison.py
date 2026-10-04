from __future__ import annotations

import io
import os
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageInformativeLineartExtractionCommand,
    LocalImageInformativeLineartExtractionResult,
    LocalImageSdxlLearnedComparisonCommand,
    content_json_bytes,
    validate_sdxl_learned_comparison_result,
)
from eom_image_provider import sdxl_learned_comparison as worker
from eom_image_provider import sdxl_lora_material as material
from eom_image_provider import sdxl_pair_inference as pair_inference
from eom_image_provider.provider import ProviderError
from eom_orchestrator import sdxl_learned_comparison_inputs as admission
from eom_orchestrator import sdxl_probe_inputs as original
from eom_orchestrator import sdxl_probe_workspace as handoff
from eom_orchestrator.control_artifact_resolution import ControlArtifactResolutionError
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from PIL import Image

from tests.unit.test_informative_lineart_extraction_contracts import (
    _command as _extraction_fixture,
)
from tests.unit.test_informative_lineart_extraction_contracts import (
    _result,
    _seal_command,
    _seal_result,
)
from tests.unit.test_local_image_training_control_artifacts import _Publisher
from tests.unit.test_sdxl_learned_comparison_contracts import _seal
from tests.unit.test_sdxl_lineart_probe import FakeBackend
from tests.unit.test_sdxl_lora_evaluation import _evaluation_fixture
from tests.unit.test_sdxl_probe_inputs import _Reader, _sha
from tests.unit.test_sdxl_probe_workspace import _operator


def _fixture():
    evaluation, records = _evaluation_fixture()
    extraction, baseline, _, _ = _extraction_fixture()
    extraction = LocalImageInformativeLineartExtractionCommand.model_validate(
        _seal_command(
            {
                **extraction.model_dump(mode="json"),
                "baseline_command": evaluation.evaluation.baseline_command.model_dump(mode="json"),
            }
        )
    )
    raw = io.BytesIO()
    Image.new("RGB", (832, 512), "black").save(raw, format="PNG")
    pixels = raw.getvalue()
    result_value = _result(extraction, baseline)
    for output in result_value["outputs"]:
        output["conditioning_sha256"] = _sha(pixels)
        output["conditioning_size_bytes"] = len(pixels)
    result = LocalImageInformativeLineartExtractionResult.model_validate(_seal_result(result_value))

    def metadata(model, family, identity):
        payload = content_json_bytes(model.model_dump(mode="json"))
        pointer = ImageEvaluationArtifactMember(
            artifact_id="artifact_" + identity * 32,
            artifact_revision_id="rev_" + identity * 32,
            member_path="manifests/" + family + ".json",
            schema_ref="eom://schemas/image-provider/local-image-" + family + "/1.0",
            media_type="application/json",
            sha256=_sha(payload),
        )
        records[pointer] = payload
        return pointer.model_dump(mode="json")

    command = LocalImageSdxlLearnedComparisonCommand.model_validate(
        _seal(
            {
                "schema_version": "local-image-sdxl-learned-comparison-command/1.0",
                "source_commit": "a" * 40,
                "created_at": "2026-10-04T01:00:00Z",
                "purpose": "EVALUATION_ONLY_MATCHED_LEARNED_CONDITIONING",
                "activation_policy": "FORBIDDEN",
                "baseline_command": evaluation.evaluation.baseline_command.model_dump(mode="json"),
                "extraction_command": metadata(
                    extraction, "informative-lineart-extraction-command", "a"
                ),
                "extraction_result": metadata(result, "informative-lineart-extraction-result", "b"),
                "lora_evaluation_command": metadata(
                    evaluation, "sdxl-lora-evaluation-command", "c"
                ),
                "conditioning_policy": "PINNED_LEARNED_FINE_INVERTED/1.0",
                "case_ids": [case.case_id for case in baseline.cases[:2]],
                "seed": baseline.cases[0].seeds[0],
                "budget": {"maximum_duration_ms": 120000, "maximum_peak_gpu_memory_bytes": 2**30},
            }
        )
    )
    for output in result.outputs:
        pointer = ImageEvaluationArtifactMember(
            **{
                **command.extraction_result.model_dump(mode="json"),
                "member_path": output.conditioning_member_path,
                "sha256": output.conditioning_sha256,
                "schema_ref": "eom://schemas/image-provider/local-image-informative-lineart-extraction-conditioning/1.0",
                "media_type": "image/png",
            }
        )
        records[pointer] = pixels
    return command, records


def _prepare(monkeypatch, *, fault=None):
    command, records = _fixture()
    if fault == "corrupt":
        records[command.extraction_result] += b"broken"
    if fault == "missing":
        del records[command.lora_evaluation_command]
    if fault == "crop":
        records[
            original.LocalImageSdxlLineartProbeCommand.model_validate_json(
                records[command.baseline_command]
            ).prompt_policy
        ] += b"broken"
    reader = _Reader(records)
    batches = []
    monkeypatch.setattr(admission, "resolve_control_artifact_member", reader)
    monkeypatch.setattr(original, "resolve_control_artifact_member", reader)

    def batch(engine, reads):
        batches.append(reads)
        return tuple(
            reader(engine, entry.pointer, maximum_bytes=entry.maximum_bytes) for entry in reads
        )

    monkeypatch.setattr(admission, "resolve_control_artifact_members", batch)
    return command, reader, batches


def test_original_lineage_before_one_batch_of_only_derived_conditionings_and_adapter(monkeypatch):
    command, reader, batches = _prepare(monkeypatch)
    prepared = admission.prepare_sdxl_learned_comparison_inputs(object(), command)
    assert len(batches) == 1 and len(batches[0]) == len(command.case_ids) + 2
    assert len(prepared.files) == len(command.case_ids) + 11
    assert {
        pointer.artifact_revision_id
        for pointer in reader.calls
        if pointer.media_type == "image/png"
    } == {command.extraction_result.artifact_revision_id}
    assert not any(file.member_path.startswith("inputs/crops/") for file in prepared.files)
    assert admission.sdxl_learned_input_hashes(command, prepared.sources) == {
        file.member_path: file.sha256 for file in prepared.files
    }


@pytest.mark.parametrize("fault", ["corrupt", "missing", "crop"])
def test_bad_provenance_never_materializes_any_conditioning_or_adapter(monkeypatch, fault):
    command, _, batches = _prepare(monkeypatch, fault=fault)
    with pytest.raises((ValueError, KeyError, ControlArtifactResolutionError)):
        admission.prepare_sdxl_learned_comparison_inputs(object(), command)
    assert not batches


def test_supported_publication_and_exclusive_handoff(monkeypatch, tmp_path):
    command, _, _ = _prepare(monkeypatch)
    prepared = admission.prepare_sdxl_learned_comparison_inputs(object(), command)
    boundary = LocalImageTrainingControlArtifactPublisher(_Publisher(), source_commit="a" * 40)
    pointer = boundary.commit_sdxl_learned_comparison_command(command)
    assert pointer.schema_ref.endswith("local-image-sdxl-learned-comparison-command/1.0")
    assert boundary.publisher.arguments["idempotency_key"].endswith(command.command_sha256[7:])
    root, owner, ownership = _operator(monkeypatch, tmp_path)
    staged = handoff.stage_sdxl_learned_comparison_inputs(
        prepared, workspace_parent=root, worker=owner
    )
    assert staged.systemd_unit == f"eom-image-sdxl-learned-comparison@{command.run_id}.service"
    assert ownership[-1] == (staged.workspace, owner.uid, owner.gid)
    with pytest.raises(handoff.SdxlProbeHandoffError, match="EXISTS"):
        handoff.stage_sdxl_learned_comparison_inputs(prepared, workspace_parent=root, worker=owner)
    for file in prepared.files:
        assert (staged.workspace / file.member_path).read_bytes() == file.payload


class _Backend(FakeBackend):
    def __init__(self, fault=None):
        super().__init__(fault=fault)
        self.arms = []
        self.received = []

    @contextmanager
    def open(self, stack, *, style_adapter=None):
        self.arms.append("BASE" if style_adapter is None else "LORA")
        self.opens += 1
        yield self

    def generate(self, **kwargs):
        self.received.append(kwargs)
        if self.fault == "oom":
            self.calls += 1
            raise ProviderError("SDXL_PROBE_OOM")
        return super().generate(**kwargs)


def _stage(monkeypatch, tmp_path):
    command, _, _ = _prepare(monkeypatch)
    prepared = admission.prepare_sdxl_learned_comparison_inputs(object(), command)
    tmp_path.chmod(0o700)
    for file in prepared.files:
        path = tmp_path / file.member_path
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_bytes(file.payload)
        path.chmod(0o600)
    read_original = material.read_staged_member

    def read(root, relative, **kwargs):
        assert kwargs.pop("expected_owner_uid") == 0
        return read_original(root, relative, expected_owner_uid=os.geteuid(), **kwargs)

    monkeypatch.setattr(material, "read_staged_member", read)
    monkeypatch.setattr(worker, "resolve_sdxl_stack", lambda *a, **k: object())
    leases = []

    @contextmanager
    def lease(_path):
        leases.append("ENTER")
        yield
        leases.append("EXIT")

    monkeypatch.setattr(pair_inference, "acquire_gpu_lease", lease)
    return prepared, leases


def _run(prepared, tmp_path, backend):
    return worker.run_sdxl_learned_comparison(
        command=prepared.command,
        workspace=tmp_path,
        model_store_root=tmp_path,
        gpu_lock=tmp_path / "gpu.lock",
        backend=backend,
    )


@pytest.mark.parametrize("fault", [None, "second", "unexpected", "oom"])
def test_fresh_arms_original_settings_exact_conditioning_terminal_prefix_and_offline_replay(
    monkeypatch,
    tmp_path,
    fault,
):
    prepared, leases = _stage(monkeypatch, tmp_path)
    backend = _Backend(fault=fault)
    result = _run(prepared, tmp_path, backend)
    assert result.status == ("SUCCEEDED" if fault is None else "FAILED")
    validate_sdxl_learned_comparison_result(prepared.command, prepared.sources, result)
    if fault is None:
        assert len(result.outputs) == 4 and backend.arms == ["BASE", "LORA"]
        assert leases == ["ENTER", "EXIT"]
    cases = {case.case_id: case for case in prepared.sources.baseline.cases}
    for call in backend.received:
        assert call["command"] == prepared.sources.baseline
        assert call["seed"] == prepared.command.seed
        case = next(case for case in cases.values() if case.prompt_en == call["prompt"])
        assert call["negative_prompt"] == case.negative_prompt_en
        assert (
            call["conditioning"]
            == (tmp_path / f"inputs/conditioning/{case.case_id}.png").read_bytes()
        )
    calls = backend.calls
    monkeypatch.setattr(
        pair_inference, "acquire_gpu_lease", lambda *a, **k: pytest.fail("replay entered GPU")
    )
    for name in ("resolve_sdxl_stack", "load_sdxl_lora_material"):
        monkeypatch.setattr(worker, name, lambda *a, **k: pytest.fail("replay entered model/GPU"))
    assert _run(prepared, tmp_path, backend) == result and backend.calls == calls


@pytest.mark.parametrize("fault", ["conditioning", "final", "raw", "result", "partial"])
def test_tamper_or_unreceipted_outputs_cannot_regenerate(monkeypatch, tmp_path, fault):
    prepared, _ = _stage(monkeypatch, tmp_path)
    backend = _Backend()
    result = _run(prepared, tmp_path, backend)
    if fault == "partial":
        (tmp_path / "result.json").unlink()
    else:
        member = {
            "conditioning": f"inputs/conditioning/{prepared.command.case_ids[0]}.png",
            "final": result.outputs[0].member_path,
            "raw": result.outputs[0].raw_member_path,
            "result": "result.json",
        }[fault]
        (tmp_path / member).write_bytes(b"corrupt")
    with pytest.raises(ProviderError):
        _run(prepared, tmp_path, backend)
    assert backend.calls == 4


def test_isolated_unit_and_dispatch_have_no_production_or_network_access(monkeypatch):
    command, _ = _fixture()
    staged = handoff.StagedSdxlProbe(
        Path("/srv/eom/image-training-workspaces") / command.run_id,
        f"eom-image-sdxl-learned-comparison@{command.run_id}.service",
        command.command_sha256,
    )
    calls = []
    monkeypatch.setattr(handoff.os, "geteuid", lambda: 0)
    monkeypatch.setattr(handoff.subprocess, "run", lambda *a, **k: calls.append((a, k)))
    handoff.dispatch_sdxl_learned_comparison(staged)
    assert calls[0][0][0] == ["systemctl", "start", "--no-block", staged.systemd_unit]
    with pytest.raises(handoff.SdxlProbeHandoffError, match="INVALID"):
        handoff.dispatch_sdxl_learned_comparison(
            replace(staged, workspace=Path("/tmp") / command.run_id)
        )
    unit = Path("infra/systemd/eom-image-sdxl-learned-comparison@.service").read_text()
    for required in (
        "PrivateNetwork=true",
        "User=eom-image",
        "Restart=no",
        "NoNewPrivileges=true",
        "InaccessiblePaths=/mnt/nas",
        "InaccessiblePaths=/etc/eom",
        "InaccessiblePaths=/home/eom/EOM",
        "HF_HUB_OFFLINE=1",
        "sdxl-learned-comparison --command",
    ):
        assert required in unit
    assert "ReadWritePaths=/srv/eom/models" not in unit


def test_failure_in_second_arm_preserves_only_completed_first_arm(monkeypatch, tmp_path):
    prepared, _ = _stage(monkeypatch, tmp_path)

    class FailedLora(_Backend):
        def generate(self, **kwargs):
            if self.calls == 2:
                self.calls += 1
                raise ProviderError("SDXL_PROBE_OOM")
            return super().generate(**kwargs)

    backend = FailedLora()
    result = _run(prepared, tmp_path, backend)
    assert result.status == "FAILED" and result.error_code == "SDXL_PROBE_OOM"
    assert tuple(output.arm for output in result.outputs) == ("BASE", "BASE")
    assert backend.arms == ["BASE", "LORA"] and backend.calls == 3
    assert _run(prepared, tmp_path, backend) == result and backend.calls == 3


@pytest.mark.parametrize("budget", ["time", "memory"])
def test_budget_failure_is_terminal_and_never_retried(monkeypatch, tmp_path, budget):
    prepared, _ = _stage(monkeypatch, tmp_path)
    value = prepared.command.model_dump(mode="json")
    value["budget"][
        "maximum_duration_ms" if budget == "time" else "maximum_peak_gpu_memory_bytes"
    ] = 1
    command = LocalImageSdxlLearnedComparisonCommand.model_validate(_seal(value))
    (tmp_path / "command.json").write_bytes(content_json_bytes(command.model_dump(mode="json")))
    prepared = replace(prepared, command=command)
    if budget == "time":
        clock = iter(index / 100 for index in range(100))
        monkeypatch.setattr(worker.time, "monotonic", lambda: next(clock))
    backend = _Backend()
    result = _run(prepared, tmp_path, backend)
    assert result.status == "FAILED" and result.error_code == "SDXL_PROBE_BUDGET_EXCEEDED"
    calls = backend.calls
    assert _run(prepared, tmp_path, backend) == result and backend.calls == calls


def test_malformed_generated_png_is_output_failure_not_quality_success(monkeypatch, tmp_path):
    prepared, _ = _stage(monkeypatch, tmp_path)

    class BadPng(_Backend):
        def generate(self, **kwargs):
            generated = super().generate(**kwargs)
            return replace(generated, png_bytes=b"not-png")

    result = _run(prepared, tmp_path, BadPng())
    assert result.status == "FAILED" and result.error_code == "SDXL_PROBE_OUTPUT_INVALID"
    assert not result.outputs
