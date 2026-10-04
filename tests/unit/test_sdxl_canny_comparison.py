"""Synthetic CPU boundary tests, not controller tensor or visual-quality acceptance."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_image_contracts.models import (
    ImageEvaluationArtifactMember,
    content_json_bytes,
    content_sha256,
)
from eom_image_contracts.sdxl_canny_comparison import (
    LocalImageSdxlCannyComparisonCommand,
    LocalImageSdxlCannyComparisonResult,
    LocalImageSdxlCannyDetailReview,
    SdxlCannyControlParameters,
    validate_sdxl_canny_comparison_result,
)
from eom_image_contracts.sdxl_canny_conditioning import (
    LocalImageSdxlCannyConditioningCommand,
    SdxlCannyPolicy,
    SdxlCannyRuntime,
)
from eom_image_contracts.sdxl_canny_controlnet import sdxl_canny_controller_pointer
from eom_image_contracts.validation import SCHEMA_FILES, SCHEMA_SHA256
from eom_image_provider import sdxl_canny_comparison as worker
from eom_image_provider import sdxl_canny_conditioning as cpu
from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_comparison_command import load_sdxl_comparison_command
from eom_orchestrator import sdxl_canny_comparison_inputs as admission
from eom_orchestrator import sdxl_probe_workspace as handoff
from eom_orchestrator.control_artifact_resolution import ControlArtifactResolutionError
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from eom_orchestrator.sdxl_target_comparison_inputs import ResolvedSdxlTargetComparisonMetadata

from tests.unit.test_local_image_training_control_artifacts import _Publisher
from tests.unit.test_sdxl_canny_conditioning import _fake_edges
from tests.unit.test_sdxl_canny_conditioning import _seal as _cpu_seal
from tests.unit.test_sdxl_canny_controller import _manifest
from tests.unit.test_sdxl_learned_comparison import _Backend as FakeBackend
from tests.unit.test_sdxl_micro_runner import _write
from tests.unit.test_sdxl_probe_inputs import _Reader
from tests.unit.test_sdxl_probe_workspace import _operator
from tests.unit.test_sdxl_target_comparison import _run as _old_run
from tests.unit.test_sdxl_target_comparison import _stage as _old_stage


def _sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _seal(value):
    value = copy.deepcopy(value)
    value.pop("run_id", None)
    value.pop("command_sha256", None)
    value["run_id"] = "imgsdxlcannycmprun_" + content_sha256(value)[7:39]
    value["command_sha256"] = content_sha256(value)
    return value


def _fixture(tmp_path, monkeypatch):
    parent, old_root, leases = _old_stage(tmp_path, monkeypatch)
    baseline = _old_run(parent, old_root, FakeBackend())
    assert baseline.status == "SUCCEEDED"
    leases.clear()
    records = {}

    def pin(model, family, identity):
        raw = content_json_bytes(model.model_dump(mode="json"))
        pointer = ImageEvaluationArtifactMember(
            artifact_id="artifact_" + identity * 32,
            artifact_revision_id="rev_" + identity * 32,
            member_path="manifests/" + family + ".json",
            schema_ref="eom://schemas/image-provider/local-image-" + family + "/1.0",
            media_type="application/json",
            sha256=_sha(raw),
        )
        records[pointer] = raw
        return pointer

    policy = SdxlCannyPolicy()
    runtime = SdxlCannyRuntime(pillow_version="12.3.0", numpy_version="2.4.6")
    preparation = LocalImageSdxlCannyConditioningCommand.model_validate(
        _cpu_seal(
            dict(
                schema_version="local-image-sdxl-canny-conditioning-command/1.0",
                source_commit="a" * 40,
                created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                purpose="EVALUATION_ONLY_CANNY_INPUT_PREPARATION",
                activation_policy="FORBIDDEN",
                case_relation="REVIEWED_TRAIN_TARGET_NOT_HOLDOUT",
                source_command=pin(
                    parent.command, "sdxl-target-comparison-command", "1"
                ).model_dump(mode="json"),
                policy=policy.model_dump(mode="json"),
                policy_sha256=content_sha256(policy.model_dump(mode="json")),
                runtime=runtime.model_dump(mode="json"),
                budget=dict(
                    maximum_duration_ms=30000, maximum_outputs=3, maximum_input_png_bytes=16777216
                ),
            )
        )
    )
    cpu_root = tmp_path / "cpu"
    cpu_root.mkdir(mode=0o700)
    for file in parent.files:
        if not file.member_path.startswith("inputs/adapter/"):
            _write(
                cpu_root
                / (
                    "inputs/parent-command.json"
                    if file.member_path == "command.json"
                    else file.member_path
                ),
                file.payload,
            )
    _write(cpu_root / "command.json", content_json_bytes(preparation.model_dump(mode="json")))
    monkeypatch.setattr(cpu, "read_canny_runtime", lambda: runtime)
    conditionings = cpu.run_sdxl_canny_conditioning(
        command=preparation, workspace=cpu_root, extractor=_fake_edges
    )
    command_pin = pin(preparation, "sdxl-canny-conditioning-command", "2")
    result_pin = pin(conditionings, "sdxl-canny-conditioning-result", "3")
    evidence = dict(
        status="OWN_CANNY_SOURCE_DETAIL_REVIEW_COMPLETE",
        created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        conditioning_result_sha256=result_pin.sha256,
        conditioning_artifact_id=result_pin.artifact_id,
        conditioning_artifact_revision_id=result_pin.artifact_revision_id,
        final_illustration_quality="NOT_EVALUATED",
        review_mode="OWN_DIRECT_SOURCE_AND_CONDITIONING_NOT_BLIND",
        rows=[
            dict(
                case_id=out.case_id,
                source=dict(sha256=out.source.sha256),
                sha256=out.sha256,
                own_input_detail_status="PASS",
            )
            for out in conditionings.outputs
        ],
    )
    raw = content_json_bytes(evidence)
    evidence_pin = ImageEvaluationArtifactMember(
        artifact_id="artifact_" + "4" * 32,
        artifact_revision_id="rev_" + "4" * 32,
        member_path="reports/own-input-review.json",
        schema_ref="eom://schemas/operations/plain-text-log/1.0",
        media_type="text/plain",
        sha256=_sha(raw),
    )
    records[evidence_pin] = raw
    value = dict(
        schema_version="local-image-sdxl-canny-detail-review/1.0",
        created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        created_by="tests.own-review",
        conditioning_command=command_pin.model_dump(mode="json"),
        conditioning_result=result_pin.model_dump(mode="json"),
        own_review_evidence=evidence_pin.model_dump(mode="json"),
        mode=evidence["review_mode"],
        final_illustration_quality="NOT_EVALUATED",
        decisions=[
            dict(
                case_id=out.case_id,
                source_sha256=out.source.sha256,
                conditioning_sha256=out.sha256,
                disposition="PASS",
                reason="Synthetic source-detail fixture, not quality acceptance",
            )
            for out in conditionings.outputs
        ],
    )
    value["review_sha256"] = content_sha256(value)
    review = LocalImageSdxlCannyDetailReview.model_validate(value)
    command = LocalImageSdxlCannyComparisonCommand.model_validate(
        _seal(
            dict(
                schema_version="local-image-sdxl-canny-comparison-command/1.0",
                source_commit="a" * 40,
                created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                purpose="EVALUATION_ONLY_MATCHED_CANNY_CONTROLNET",
                activation_policy="FORBIDDEN",
                case_relation="REVIEWED_TRAIN_TARGET_NOT_HOLDOUT",
                conditioning_command=command_pin.model_dump(mode="json"),
                conditioning_result=result_pin.model_dump(mode="json"),
                detail_review=pin(review, "sdxl-canny-detail-review", "5").model_dump(mode="json"),
                baseline_result=pin(baseline, "sdxl-target-comparison-result", "6").model_dump(
                    mode="json"
                ),
                controller=sdxl_canny_controller_pointer(_manifest()).model_dump(mode="json"),
                control=SdxlCannyControlParameters().model_dump(mode="json"),
                budget=dict(
                    maximum_duration_ms=120000,
                    maximum_peak_gpu_memory_bytes=2**30,
                    maximum_outputs=6,
                ),
            )
        )
    )
    source_metadata = ResolvedSdxlTargetComparisonMetadata(
        parent.command,
        parent.sources,
        tuple(
            file
            for file in parent.files
            if not file.member_path.endswith((".png", ".safetensors"))
            and not file.member_path.startswith("inputs/adapter/")
        ),
    )
    files = {file.member_path: file.payload for file in parent.files}
    for out in conditionings.outputs:
        records[
            ImageEvaluationArtifactMember(
                artifact_id=result_pin.artifact_id,
                artifact_revision_id=result_pin.artifact_revision_id,
                member_path=out.member_path,
                schema_ref="eom://schemas/image-provider/local-image-sdxl-canny-conditioning-output/1.0",
                media_type="image/png",
                sha256=out.sha256,
            )
        ] = (cpu_root / out.member_path).read_bytes()
    for file in parent.sources.lora.manifest.files:
        pin_ = parent.sources.evaluation.evaluation.training_result
        records[
            ImageEvaluationArtifactMember(
                artifact_id=pin_.artifact_id,
                artifact_revision_id=pin_.artifact_revision_id,
                member_path="adapter/" + file.relative_path,
                schema_ref="eom://schemas/image-provider/local-image-lora-adapter-file/1.0",
                media_type="application/json"
                if file.relative_path.endswith(".json")
                else "application/octet-stream",
                sha256=file.sha256,
            )
        ] = files["inputs/adapter/" + file.relative_path]
    reader = _Reader(records)
    trace = []
    monkeypatch.setattr(admission, "resolve_control_artifact_member", reader)

    def lineage(engine, checked):
        assert checked == parent.command
        trace.append("LINEAGE")
        return source_metadata

    def batch(engine, reads):
        assert trace == ["LINEAGE"]
        trace.append("MAPS_ADAPTER")
        return tuple(
            reader(engine, read.pointer, maximum_bytes=read.maximum_bytes) for read in reads
        )

    monkeypatch.setattr(admission, "resolve_sdxl_target_comparison_metadata", lineage)
    monkeypatch.setattr(admission, "resolve_control_artifact_members", batch)
    return command, reader, trace, leases


def _prepared(tmp_path, monkeypatch):
    command, reader, trace, leases = _fixture(tmp_path, monkeypatch)
    prepared = admission.prepare_sdxl_canny_comparison_inputs(object(), command)
    assert trace == ["LINEAGE", "MAPS_ADAPTER"]
    return prepared, reader, leases


def _stage(tmp_path, monkeypatch):
    prepared, reader, leases = _prepared(tmp_path, monkeypatch)
    root = tmp_path / "spatial"
    root.mkdir(mode=0o700)
    for file in prepared.files:
        _write(root / file.member_path, file.payload)
    monkeypatch.setattr(worker, "resolve_sdxl_stack", lambda *a, **k: object())
    monkeypatch.setattr(worker, "resolve_sdxl_canny_controller", lambda *a, **k: object())
    return prepared, root, reader, leases


def _run(prepared, root, backend):
    return worker.run_sdxl_canny_comparison(
        command=prepared.command,
        workspace=root,
        model_store_root=root / "models",
        gpu_lock=root / "gpu.lock",
        backend_factory=lambda *a: backend,
    )


def test_admission_reads_only_maps_adapter_and_publication(tmp_path, monkeypatch):
    prepared, reader, _ = _prepared(tmp_path, monkeypatch)
    assert admission.sdxl_canny_comparison_input_hashes(prepared) == {
        file.member_path: file.sha256 for file in prepared.files
    }
    assert {pin.artifact_revision_id for pin in reader.calls if pin.media_type == "image/png"} == {
        prepared.command.conditioning_result.artifact_revision_id
    }
    assert not any(
        file.member_path.startswith("inputs/targets/")
        or file.member_path.startswith("inputs/crops/")
        for file in prepared.files
    )
    publisher = LocalImageTrainingControlArtifactPublisher(
        _Publisher(), source_commit=prepared.command.source_commit
    )
    for model, name in (
        (prepared.command, "commit_sdxl_canny_comparison_command"),
        (prepared.sources.review, "commit_sdxl_canny_detail_review"),
    ):
        pointer = getattr(publisher, name)(model)
        assert pointer.sha256 == _sha(content_json_bytes(model.model_dump(mode="json")))


@pytest.mark.parametrize("fault", [None, "second", "oom", "unexpected"])
def test_one_lease_fresh_arms_prefix_and_zero_model_replay(tmp_path, monkeypatch, fault):
    prepared, root, _, leases = _stage(tmp_path, monkeypatch)
    backend = FakeBackend(fault)
    result = _run(prepared, root, backend)
    assert result.status == ("SUCCEEDED" if fault is None else "FAILED")
    assert leases == ["ENTER", "EXIT"]
    if fault is None:
        assert backend.arms == ["BASE", "LORA"] and len(result.outputs) == 4
    validate_sdxl_canny_comparison_result(prepared.command, prepared.sources, result)
    assert load_sdxl_comparison_command(root, root / "command.json") == prepared.command
    for name in ("resolve_sdxl_stack", "resolve_sdxl_canny_controller", "load_sdxl_lora_material"):
        monkeypatch.setattr(worker, name, lambda *a, **k: pytest.fail("replay entered model"))
    before = {
        path: (path.stat().st_mtime_ns, path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    }
    assert _run(prepared, root, FakeBackend()) == result
    assert leases == ["ENTER", "EXIT"]
    assert all(
        (path.stat().st_mtime_ns, path.read_bytes()) == stamp for path, stamp in before.items()
    )


@pytest.mark.parametrize(
    "fault", ["holdout", "activation", "prompt", "count", "control", "hash", "member"]
)
def test_closed_command_cannot_change_scope_or_factor(tmp_path, monkeypatch, fault):
    command, _, _, _ = _fixture(tmp_path, monkeypatch)
    value = command.model_dump(mode="json")
    if fault == "holdout":
        value["case_relation"] = "HOLDOUT"
    elif fault == "activation":
        value["activation_policy"] = "ALLOWED"
    elif fault == "prompt":
        value["prompt"] = "replace frozen prompt"
    elif fault == "count":
        value["budget"]["maximum_outputs"] = 12
    elif fault == "control":
        value["control"]["conditioning_scale"] = 0.5
    elif fault == "member":
        value["detail_review"]["member_path"] = "manifests/other.json"
    else:
        value["command_sha256"] = "sha256:" + "0" * 64
    if fault != "hash":
        value = _seal(value)
    with pytest.raises(ValueError):
        LocalImageSdxlCannyComparisonCommand.model_validate(value)


@pytest.mark.parametrize(
    "fault", ["missing", "hash", "canonical", "review_fail", "review_source", "time"]
)
def test_source_fault_rejects_before_pixels(tmp_path, monkeypatch, fault):
    command, reader, trace, _ = _fixture(tmp_path, monkeypatch)
    if fault in {"review_fail", "review_source", "time"}:
        old = command.detail_review
        value = json.loads(reader.records[old])
        if fault == "review_fail":
            value["decisions"][0]["disposition"] = "FAIL"
        elif fault == "review_source":
            value["decisions"][0]["source_sha256"] = "sha256:" + "0" * 64
        else:
            value["created_at"] = "2020-01-01T00:00:00Z"
        value["review_sha256"] = content_sha256(
            {k: v for k, v in value.items() if k != "review_sha256"}
        )
        raw = content_json_bytes(value)
        new = old.model_copy(update={"sha256": _sha(raw)})
        reader.records[new] = raw
        value = command.model_dump(mode="json")
        value["detail_review"] = new.model_dump(mode="json")
        command = LocalImageSdxlCannyComparisonCommand.model_validate(_seal(value))
    elif fault == "missing":
        del reader.records[command.conditioning_result]
    elif fault == "hash":
        reader.records[command.conditioning_result] += b" "
    else:
        old = command.conditioning_result
        raw = json.dumps(json.loads(reader.records[old]), indent=2).encode()
        new = old.model_copy(update={"sha256": _sha(raw)})
        reader.records[new] = raw
        value = command.model_dump(mode="json")
        value["conditioning_result"] = new.model_dump(mode="json")
        command = LocalImageSdxlCannyComparisonCommand.model_validate(_seal(value))
    with pytest.raises((ValueError, KeyError, AssertionError, ControlArtifactResolutionError)):
        admission.prepare_sdxl_canny_comparison_inputs(object(), command)
    assert "MAPS_ADAPTER" not in trace


@pytest.mark.parametrize(
    "fault", ["extra", "tamper", "linked_dir", "partial", "noncanonical", "missing_dir"]
)
def test_replay_fails_closed_before_model(tmp_path, monkeypatch, fault):
    prepared, root, _, _ = _stage(tmp_path, monkeypatch)
    result = _run(prepared, root, FakeBackend())
    if fault == "extra":
        _write(root / "outputs" / "extra.png", b"uncommitted")
    elif fault == "tamper":
        (root / result.outputs[0].member_path).write_bytes(b"bad")
    elif fault == "linked_dir":
        (root / "outputs" / "linked").symlink_to(tmp_path, target_is_directory=True)
    elif fault == "partial":
        (root / "result.json").unlink()
    elif fault == "missing_dir":
        path = root / "outputs" / "lora" / "raw"
        for file in path.iterdir():
            file.unlink()
        path.rmdir()
    else:
        (root / "result.json").write_bytes(
            json.dumps(result.model_dump(mode="json"), indent=2).encode()
        )
    monkeypatch.setattr(
        worker, "resolve_sdxl_stack", lambda *a, **k: pytest.fail("invalid replay reached model")
    )
    with pytest.raises(ProviderError):
        _run(prepared, root, FakeBackend())


@pytest.mark.parametrize(
    "fault", ["quality", "controller", "source", "map", "order", "runtime", "budget"]
)
def test_result_cannot_invent_acceptance_or_other_identity(tmp_path, monkeypatch, fault):
    prepared, root, _, _ = _stage(tmp_path, monkeypatch)
    value = _run(prepared, root, FakeBackend()).model_dump(mode="json")
    if fault == "quality":
        value["quality_acceptance"] = "PASS"
    elif fault == "controller":
        value["controller"]["manifest_sha256"] = "sha256:" + "0" * 64
    elif fault == "source":
        value["outputs"][0]["reference_sha256"] = "sha256:" + "0" * 64
    elif fault == "map":
        value["outputs"][0]["conditioning_sha256"] = "sha256:" + "0" * 64
    elif fault == "order":
        value["outputs"].reverse()
    elif fault == "runtime":
        value["runtime"] = None
    else:
        value["duration_ms"] = prepared.command.budget.maximum_duration_ms + 1
    value["result_sha256"] = content_sha256(
        {k: v for k, v in value.items() if k != "result_sha256"}
    )
    with pytest.raises(ValueError):
        result = LocalImageSdxlCannyComparisonResult.model_validate(value)
        validate_sdxl_canny_comparison_result(prepared.command, prepared.sources, result)


def test_exclusive_operator_handoff_and_exact_replay(tmp_path, monkeypatch):
    prepared, _, _ = _prepared(tmp_path, monkeypatch)
    parent, owner, _ = _operator(monkeypatch, tmp_path)
    result = handoff.stage_sdxl_canny_comparison_inputs(
        prepared, workspace_parent=parent, worker=owner
    )
    assert (
        result.systemd_unit
        == "eom-image-sdxl-learned-comparison@" + prepared.command.run_id + ".service"
    )
    with pytest.raises(handoff.SdxlProbeHandoffError, match="WORKSPACE_EXISTS"):
        handoff.stage_sdxl_canny_comparison_inputs(prepared, workspace_parent=parent, worker=owner)
    changed = replace(prepared, files=prepared.files[:-1])
    with pytest.raises((ValueError, KeyError, handoff.SdxlProbeHandoffError)):
        handoff.stage_sdxl_canny_comparison_inputs(changed, workspace_parent=parent, worker=owner)


def test_generated_schema_copies_and_hashes():
    root = Path(__file__).resolve().parents[2]
    for model, name in (
        (LocalImageSdxlCannyDetailReview, "sdxl-canny-detail-review"),
        (LocalImageSdxlCannyComparisonCommand, "sdxl-canny-comparison-command"),
        (LocalImageSdxlCannyComparisonResult, "sdxl-canny-comparison-result"),
    ):
        raw = (root / "schemas/image-provider" / SCHEMA_FILES[name]).read_bytes()
        assert _sha(raw) == SCHEMA_SHA256[name]
        assert (
            raw
            == (
                root / "packages/image_contracts/eom_image_contracts/schemas" / SCHEMA_FILES[name]
            ).read_bytes()
        )
        generated = model.model_json_schema()
        generated.update(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$id": "eom://schemas/image-provider/local-image-" + name + "/1.0",
            }
        )
        assert json.loads(raw) == generated
