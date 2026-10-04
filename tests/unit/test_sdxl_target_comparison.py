"""CPU contract/admission/replay tests; never certify image quality or CUDA execution."""

from __future__ import annotations

import copy
import json
import os
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from eom_image_contracts.models import (
    ImageEvaluationArtifactMember,
    content_json_bytes,
    content_sha256,
)
from eom_image_contracts.sdxl_lineart_probe import LocalImageSdxlLineartProbeCommand
from eom_image_contracts.sdxl_reviewed_micro import (
    LocalImageSdxlReviewedMicroCommand,
    parse_sdxl_reviewed_micro_sources,
)
from eom_image_contracts.sdxl_target_comparison import (
    LocalImageSdxlTargetComparisonCommand,
    LocalImageSdxlTargetComparisonResult,
    validate_sdxl_target_comparison_result,
)
from eom_image_contracts.validation import validate_contract
from eom_image_provider import sdxl_lora_material as material
from eom_image_provider import sdxl_pair_inference as inference
from eom_image_provider import sdxl_target_comparison as worker
from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_comparison_command import load_sdxl_comparison_command
from eom_orchestrator import sdxl_probe_inputs as originals
from eom_orchestrator import sdxl_probe_workspace as handoff
from eom_orchestrator import sdxl_target_comparison_inputs as admission
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from eom_orchestrator.sdxl_micro_inputs import AdmittedSdxlReviewedMicroSources
from eom_orchestrator.sdxl_probe_inputs import SdxlProbeInputMember
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit.test_local_image_training_control_artifacts import _Publisher
from tests.unit.test_sdxl_learned_comparison import _Backend as FakeBackend
from tests.unit.test_sdxl_micro_runner import _write
from tests.unit.test_sdxl_probe_inputs import _Reader, _sha
from tests.unit.test_sdxl_probe_workspace import _operator
from tests.unit.test_sdxl_reviewed_evaluation import _fixture as _reviewed_fixture


def _seal(value):
    value = copy.deepcopy(value)
    value.pop("run_id", None)
    value.pop("command_sha256", None)
    value["run_id"] = "imgsdxltargetcmprun_" + content_sha256(value)[7:39]
    value["command_sha256"] = content_sha256(value)
    return value


def _fixture(tmp_path, monkeypatch):
    evaluation, records, metadata = _reviewed_fixture(tmp_path, monkeypatch)
    training = LocalImageSdxlReviewedMicroCommand.model_validate_json(
        records[evaluation.evaluation.training_command]
    )
    baseline = LocalImageSdxlLineartProbeCommand.model_validate_json(
        records[evaluation.evaluation.baseline_command]
    )
    targets = parse_sdxl_reviewed_micro_sources(training, metadata)
    expressions = {
        decision["sample_id"]: decision["expression"]
        for decision in json.loads(metadata["inputs/target-batches/0/command.json"])["decisions"]
        if decision["disposition"] == "PREPARE"
    }
    raw = content_json_bytes(evaluation.model_dump(mode="json"))
    pin = ImageEvaluationArtifactMember(
        artifact_id="artifact_" + "d" * 32,
        artifact_revision_id="rev_" + "d" * 32,
        member_path="manifests/sdxl-lora-evaluation-command.json",
        schema_ref="eom://schemas/image-provider/local-image-sdxl-lora-evaluation-command/1.1",
        media_type="application/json",
        sha256=_sha(raw),
    )
    records[pin] = raw
    cases = []
    for i, sample in enumerate(training.training_samples):
        value = baseline.cases[0].model_dump(mode="json", exclude={"case_id", "staged_member_path"})
        value.update(
            depiction_key="TARGET_RECTANGLE_" + str(i),
            reference_image=sample.source_image.model_dump(mode="json"),
            reference_width_px=768,
            reference_height_px=512,
            seeds=[104729],
        )
        value["case_id"] = "imgsdxlcase_" + content_sha256(value)[7:39]
        value["staged_member_path"] = "inputs/" + value["case_id"] + ".png"
        cases.append(
            dict(
                sample_id=sample.sample_id,
                target_id=sample.target_id,
                target_revision_id=sample.target_revision_id,
                expression=expressions[sample.sample_id],
                case=value,
            )
        )
        records[sample.source_image] = (
            tmp_path / training.training_run_id / sample.staged_member_path
        ).read_bytes()
    command = LocalImageSdxlTargetComparisonCommand.model_validate(
        _seal(
            dict(
                schema_version="local-image-sdxl-target-comparison-command/1.0",
                source_commit="a" * 40,
                created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                purpose="EVALUATION_ONLY_MATCHED_REVIEWED_TARGET",
                activation_policy="FORBIDDEN",
                case_relation="REVIEWED_TRAIN_TARGET_NOT_HOLDOUT",
                lora_evaluation_command=pin.model_dump(mode="json"),
                conditioning_policy="FIT_GRAYSCALE_INVERT_832X512/1.0",
                cases=sorted(cases, key=lambda entry: entry["case"]["case_id"]),
                seed=104729,
                budget=dict(maximum_duration_ms=120000, maximum_peak_gpu_memory_bytes=2**30),
            )
        )
    )
    admitted = AdmittedSdxlReviewedMicroSources(
        training,
        tuple(SdxlProbeInputMember(name, _sha(raw), raw) for name, raw in sorted(metadata.items())),
        tuple(targets.values()),
    )
    return command, records, admitted


def _prepare(tmp_path, monkeypatch, *, fail_lineage=False):
    command, records, admitted = _fixture(tmp_path, monkeypatch)
    reader = _Reader(records)
    monkeypatch.setattr(admission, "resolve_control_artifact_member", reader)
    monkeypatch.setattr(originals, "resolve_control_artifact_member", reader)
    trace = []

    def lineage(*args):
        trace.append("FULL_LINEAGE")
        if fail_lineage:
            raise ValueError("missing original PDF fixture")
        return admitted

    monkeypatch.setattr(admission, "resolve_sdxl_reviewed_micro_sources", lineage)

    def batch(engine, reads):
        trace.append("PIXELS_WEIGHTS")
        assert trace[0] == "FULL_LINEAGE"
        return tuple(
            reader(engine, read.pointer, maximum_bytes=read.maximum_bytes) for read in reads
        )

    monkeypatch.setattr(admission, "resolve_control_artifact_members", batch)
    prepared = admission.prepare_sdxl_target_comparison_inputs(object(), command)
    assert trace == ["FULL_LINEAGE", "PIXELS_WEIGHTS"]
    return prepared, reader


def _stage(tmp_path, monkeypatch):
    prepared, _ = _prepare(tmp_path, monkeypatch)
    root = tmp_path / "worker"
    root.mkdir(mode=0o700)
    for file in prepared.files:
        _write(root / file.member_path, file.payload)
    actual_read = material.read_staged_member
    monkeypatch.setattr(
        material,
        "read_staged_member",
        lambda *a, **k: actual_read(*a, **{**k, "expected_owner_uid": os.geteuid()}),
    )
    monkeypatch.setattr(worker, "resolve_sdxl_stack", lambda *a, **k: object())
    leases = []

    @contextmanager
    def lease(path):
        leases.append("ENTER")
        try:
            yield
        finally:
            leases.append("EXIT")

    monkeypatch.setattr(inference, "acquire_gpu_lease", lease)
    return prepared, root, leases


def _run(prepared, root, backend):
    return worker.run_sdxl_target_comparison(
        command=prepared.command,
        workspace=root,
        model_store_root=root / "models",
        gpu_lock=root / "gpu.lock",
        backend=backend,
    )


def test_canonical_new_contract_and_only_selected_pixels(tmp_path, monkeypatch):
    prepared, reader = _prepare(tmp_path, monkeypatch)
    validate_contract("sdxl-target-comparison-command", prepared.command.model_dump(mode="json"))
    assert sum(pin.media_type == "image/png" for pin in reader.calls) == len(prepared.command.cases)
    assert set(admission.sdxl_target_comparison_input_hashes(prepared)) == {
        file.member_path for file in prepared.files
    }
    assert not any(file.member_path.startswith("inputs/targets/") for file in prepared.files)
    with pytest.raises(SchemaError):
        validate_contract(
            "sdxl-learned-comparison-command", prepared.command.model_dump(mode="json")
        )
    publisher = _Publisher()
    pointer = LocalImageTrainingControlArtifactPublisher(
        publisher, source_commit=prepared.command.source_commit
    ).commit_sdxl_target_comparison_command(prepared.command)
    assert pointer.sha256 == _sha(content_json_bytes(prepared.command.model_dump(mode="json")))


def test_full_lineage_failure_prevents_pixel_reads(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="missing original PDF"):
        _prepare(tmp_path, monkeypatch, fail_lineage=True)


@pytest.mark.parametrize("fault", [None, "second", "oom", "unexpected"])
def test_one_lease_two_fresh_arms_and_zero_model_replay(tmp_path, monkeypatch, fault):
    prepared, root, leases = _stage(tmp_path, monkeypatch)
    backend = FakeBackend(fault)
    result = _run(prepared, root, backend)
    assert result.status == ("SUCCEEDED" if fault is None else "FAILED")
    assert leases == ["ENTER", "EXIT"]
    if fault is None:
        assert backend.arms == ["BASE", "LORA"]
        assert [out.arm for out in result.outputs] == ["BASE", "BASE", "LORA", "LORA"]
        assert tuple(out.conditioning_sha256 for out in result.outputs[:2]) == tuple(
            out.conditioning_sha256 for out in result.outputs[2:]
        )
    validate_sdxl_target_comparison_result(prepared.command, prepared.sources, result)
    assert load_sdxl_comparison_command(root, root / "command.json") == prepared.command
    for name in ("resolve_sdxl_stack", "load_sdxl_lora_material"):
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
    "fault",
    ["holdout", "old_eval", "duplicate", "seed", "hash", "source_revision", "expression", "time"],
)
def test_closed_scope_and_exact_target_lineage(tmp_path, monkeypatch, fault):
    prepared, root, _ = _stage(tmp_path, monkeypatch)
    value = prepared.command.model_dump(mode="json")
    if fault == "holdout":
        value["case_relation"] = "HOLDOUT_PASS"
    elif fault == "old_eval":
        value["lora_evaluation_command"]["schema_ref"] = value["lora_evaluation_command"][
            "schema_ref"
        ].replace("1.1", "1.0")
    elif fault == "duplicate":
        value["cases"] = [value["cases"][0]] * 2
    elif fault == "seed":
        value["seed"] += 1
    elif fault == "source_revision":
        value["cases"][0]["target_revision_id"] = "imgsdxltargetrev_" + "0" * 32
    elif fault == "expression":
        value["cases"][0]["expression"] = (
            "FINE_HATCHING"
            if value["cases"][0]["expression"] != "FINE_HATCHING"
            else "CLEAN_CONTOUR"
        )
    elif fault == "time":
        value["created_at"] = "2020-01-01T00:00:00Z"
    if fault != "hash":
        value = _seal(value)
    else:
        value["command_sha256"] = "sha256:" + "0" * 64
    if fault in {"source_revision", "expression", "time"}:
        command = LocalImageSdxlTargetComparisonCommand.model_validate(value)
        _write(root / "command.json", content_json_bytes(command.model_dump(mode="json")))
        with pytest.raises(ProviderError, match="INPUT_INVALID"):
            _run(replace(prepared, command=command), root, FakeBackend())
        assert not (root / "outputs").exists()
    else:
        with pytest.raises(ValidationError):
            LocalImageSdxlTargetComparisonCommand.model_validate(value)


@pytest.mark.parametrize(
    "member",
    [
        "inputs/lora-evaluation-command.json",
        "inputs/source-crop-set.json",
        "inputs/prompt-policy.json",
        "reference",
        "conditioning",
        "final",
        "raw",
    ],
)
def test_hash_tamper_never_regenerates(tmp_path, monkeypatch, member):
    prepared, root, leases = _stage(tmp_path, monkeypatch)
    if member in {"conditioning", "final", "raw"}:
        result = _run(prepared, root, FakeBackend())
        path = (
            result.conditionings[0].member_path
            if member == "conditioning"
            else (
                result.outputs[0].member_path
                if member == "final"
                else result.outputs[0].raw_member_path
            )
        )
    else:
        path = (
            prepared.command.cases[0].case.staged_member_path if member == "reference" else member
        )
    _write(root / path, b"tampered")
    with pytest.raises(ProviderError):
        _run(prepared, root, FakeBackend())
    assert len(leases) <= 2


def test_handoff_is_exclusive_and_uses_existing_unit(tmp_path, monkeypatch):
    prepared, _ = _prepare(tmp_path, monkeypatch)
    parent, owner, _ = _operator(monkeypatch, tmp_path)
    staged = handoff.stage_sdxl_target_comparison_inputs(
        prepared, workspace_parent=parent, worker=owner
    )
    assert (
        staged.systemd_unit
        == f"eom-image-sdxl-learned-comparison@{prepared.command.run_id}.service"
    )
    with pytest.raises(handoff.SdxlProbeHandoffError, match="WORKSPACE_EXISTS"):
        handoff.stage_sdxl_target_comparison_inputs(prepared, workspace_parent=parent, worker=owner)


@pytest.mark.parametrize("fault", ["missing", "extra", "duplicate", "changed"])
def test_handoff_rejects_noncanonical_closure(tmp_path, monkeypatch, fault):
    prepared, _ = _prepare(tmp_path, monkeypatch)
    parent, owner, _ = _operator(monkeypatch, tmp_path)
    files = list(prepared.files)
    if fault == "missing":
        files.pop()
    elif fault == "extra":
        files.append(SdxlProbeInputMember("inputs/extra", _sha(b"x"), b"x"))
    elif fault == "duplicate":
        files.append(files[-1])
    else:
        files[-1] = replace(files[-1], payload=b"x")
    with pytest.raises((ValueError, KeyError, handoff.SdxlProbeHandoffError)):
        handoff.stage_sdxl_target_comparison_inputs(
            replace(prepared, files=tuple(files)), workspace_parent=parent, worker=owner
        )
    assert not list(parent.iterdir())


@pytest.mark.parametrize(
    "fault", ["missing", "extra", "order", "reference", "conditioning", "model", "scope", "hash"]
)
def test_result_invariants_reject_false_success(tmp_path, monkeypatch, fault):
    prepared, root, _ = _stage(tmp_path, monkeypatch)
    result = _run(prepared, root, FakeBackend())
    value = result.model_dump(mode="json")
    if fault == "missing":
        value["outputs"].pop()
    elif fault == "extra":
        value["outputs"].append(value["outputs"][-1])
    elif fault == "order":
        value["outputs"].reverse()
    elif fault in {"reference", "conditioning"}:
        value["outputs"][0][fault + "_sha256"] = "sha256:" + "0" * 64
    elif fault == "model":
        value["model"]["model_revision_id"] = "imgmodelrev_" + "0" * 32
    elif fault == "scope":
        value["case_relation"] = "HOLDOUT_PASS"
    if fault != "hash":
        value["result_sha256"] = content_sha256(
            {key: val for key, val in value.items() if key != "result_sha256"}
        )
    else:
        value["result_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        changed = LocalImageSdxlTargetComparisonResult.model_validate(value)
        validate_sdxl_target_comparison_result(prepared.command, prepared.sources, changed)


def test_partial_unreceipted_outputs_refuse_new_model_calls(tmp_path, monkeypatch):
    prepared, root, leases = _stage(tmp_path, monkeypatch)
    (root / "outputs").mkdir(mode=0o700)
    with pytest.raises(ProviderError, match="OUTPUT_INVALID"):
        _run(prepared, root, FakeBackend())
    assert leases == []


@pytest.mark.parametrize("budget", ["time", "memory"])
def test_resource_ceiling_is_enforced_and_failure_is_replayable(tmp_path, monkeypatch, budget):
    prepared, root, leases = _stage(tmp_path, monkeypatch)
    value = prepared.command.model_dump(mode="json")
    value["budget"][
        "maximum_duration_ms" if budget == "time" else "maximum_peak_gpu_memory_bytes"
    ] = 1
    command = LocalImageSdxlTargetComparisonCommand.model_validate(_seal(value))
    _write(root / "command.json", content_json_bytes(command.model_dump(mode="json")))
    prepared = replace(prepared, command=command)
    if budget == "time":
        clock = iter(index / 100 for index in range(100))
        monkeypatch.setattr(worker.time, "monotonic", lambda: next(clock))
    result = _run(prepared, root, FakeBackend())
    assert result.status == "FAILED" and result.error_code == "SDXL_PROBE_BUDGET_EXCEEDED"
    assert _run(prepared, root, FakeBackend()) == result
    assert leases == ["ENTER", "EXIT"]
