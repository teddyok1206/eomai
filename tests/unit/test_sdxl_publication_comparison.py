"""CPU protocol/admission/handoff/replay tests, not scientific or visual acceptance."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from importlib import metadata
from pathlib import Path

import pytest
from eom_image_contracts.models import (
    ImageEvaluationArtifactMember,
    content_json_bytes,
    content_sha256,
)
from eom_image_contracts.sdxl_publication_comparison import (
    LocalImageSdxlPublicationComparisonCommand,
    LocalImageSdxlPublicationComparisonResult,
    parse_sdxl_publication_sources,
    sdxl_publication_source_pointer,
    validate_sdxl_publication_result,
)
from eom_image_contracts.validation import validate_contract
from eom_image_contracts.visual_reference import LocalImageAssessmentLineArtPostprocessV2
from eom_image_provider import sdxl_publication_comparison as worker
from eom_image_provider.assessment_line_art import AssessmentLineArtError, assessment_line_art_v2
from eom_image_provider.provider import ProviderError
from eom_orchestrator import sdxl_probe_workspace as handoff
from eom_orchestrator import sdxl_publication_inputs as admission
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from eom_orchestrator.sdxl_target_comparison_inputs import ResolvedSdxlTargetComparisonMetadata
from jsonschema import ValidationError as SchemaError
from PIL import Image
from pydantic import ValidationError

from tests.unit.test_assessment_line_art import _textured_subject_png
from tests.unit.test_local_image_training_control_artifacts import _Publisher
from tests.unit.test_sdxl_micro_runner import _write
from tests.unit.test_sdxl_probe_workspace import _operator
from tests.unit.test_sdxl_target_comparison import FakeBackend, _run, _stage


def _seal(value):
    value = copy.deepcopy(value)
    value.pop("run_id", None)
    value.pop("command_sha256", None)
    value["run_id"] = "imgsdxlpublicationrun_" + content_sha256(value)[7:39]
    value["command_sha256"] = content_sha256(value)
    return value


def _fixture(tmp_path, monkeypatch):
    parent, root, _ = _stage(tmp_path, monkeypatch)
    with Image.open(io.BytesIO(_textured_subject_png())) as image:
        raw = Image.new("RGB", (832, 512), "white")
        raw.paste(image, (16, 6))
    buffer = io.BytesIO()
    raw.save(buffer, format="PNG", compress_level=9)
    payload = buffer.getvalue()
    backend = FakeBackend()
    original_generate = backend.generate

    def generate(**kwargs):
        return replace(original_generate(**kwargs), png_bytes=payload)

    backend.generate = generate
    result = _run(parent, root, backend)
    assert result.status == "SUCCEEDED", result.error_code
    records = {}

    def pin(model, kind, digit):
        raw = content_json_bytes(model.model_dump(mode="json"))
        pointer = ImageEvaluationArtifactMember(
            artifact_id="artifact_" + digit * 32,
            artifact_revision_id="rev_" + digit * 32,
            member_path=f"manifests/sdxl-target-comparison-{kind}.json",
            schema_ref=f"eom://schemas/image-provider/local-image-sdxl-target-comparison-{kind}/1.0",
            media_type="application/json",
            sha256="sha256:" + hashlib.sha256(raw).hexdigest(),
        )
        records[pointer] = raw
        return pointer

    source_command, source_result = pin(parent.command, "command", "5"), pin(result, "result", "6")
    policy = LocalImageAssessmentLineArtPostprocessV2()
    command = LocalImageSdxlPublicationComparisonCommand.model_validate(
        _seal(
            dict(
                schema_version="local-image-sdxl-publication-comparison-command/1.0",
                source_commit="a" * 40,
                created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                purpose="EVALUATION_ONLY_PINNED_CPU_PUBLICATION",
                activation_policy="FORBIDDEN",
                case_relation="REVIEWED_TRAIN_TARGET_NOT_HOLDOUT",
                source_command=source_command.model_dump(mode="json"),
                source_result=source_result.model_dump(mode="json"),
                postprocess=policy.model_dump(mode="json"),
                policy_sha256=content_sha256(policy.model_dump(mode="json")),
                pillow_version=metadata.version("Pillow"),
                budget=dict(
                    maximum_outputs=6,
                    maximum_duration_ms=90000,
                    maximum_input_png_bytes=16_777_216,
                ),
            )
        )
    )
    for output in result.outputs:
        records[sdxl_publication_source_pointer(command, output)] = (
            root / output.member_path
        ).read_bytes()
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
    trace = []

    def batch(engine, reads):
        trace.append(
            "NATIVE_PIXELS" if reads[0].pointer.media_type == "image/png" else "PARENT_METADATA"
        )
        if reads[0].pointer.media_type == "image/png":
            assert trace[-2] == "FULL_LINEAGE"
        payloads = tuple(records[read.pointer] for read in reads)
        for read, payload in zip(reads, payloads, strict=True):
            if len(payload) > read.maximum_bytes or (
                "sha256:" + hashlib.sha256(payload).hexdigest() != read.pointer.sha256
            ):
                raise ValueError("invalid test artifact pointer")
        return payloads

    def lineage(engine, checked):
        assert checked == parent.command
        trace.append("FULL_LINEAGE")
        return source_metadata

    monkeypatch.setattr(admission, "resolve_control_artifact_members", batch)
    monkeypatch.setattr(admission, "resolve_sdxl_target_comparison_metadata", lineage)
    return command, records, source_metadata, result, trace


def _prepared(tmp_path, monkeypatch):
    command, records, _source_metadata, parent, trace = _fixture(tmp_path, monkeypatch)
    prepared = admission.prepare_sdxl_publication_inputs(object(), command)
    assert trace == ["PARENT_METADATA", "FULL_LINEAGE", "NATIVE_PIXELS"]
    return prepared, records, parent


def _worker(tmp_path, monkeypatch):
    prepared, records, parent = _prepared(tmp_path, monkeypatch)
    root = tmp_path / "publication-worker"
    root.mkdir(mode=0o700)
    for file in prepared.files:
        _write(root / file.member_path, file.payload)
    return prepared, root, records, parent


def test_closed_contract_and_only_native_png_materialization(tmp_path, monkeypatch):
    prepared, _, parent = _prepared(tmp_path, monkeypatch)
    command = prepared.command
    validate_contract("sdxl-publication-comparison-command", command.model_dump(mode="json"))
    files = {file.member_path: file for file in prepared.files}
    assert sum(name.endswith(".png") for name in files) == len(parent.outputs)
    assert not any(
        name.endswith(".safetensors") or name.startswith("inputs/adapter/") for name in files
    )
    assert admission.sdxl_publication_input_hashes(prepared) == {
        name: file.sha256 for name, file in files.items()
    }
    assert (
        parse_sdxl_publication_sources(
            command, {name: file.payload for name, file in files.items()}
        )
        == prepared.sources
    )
    publisher = _Publisher()
    pointer = LocalImageTrainingControlArtifactPublisher(
        publisher, source_commit="a" * 40
    ).commit_sdxl_publication_comparison_command(command)
    assert pointer.schema_ref.endswith("sdxl-publication-comparison-command/1.0")
    assert publisher.arguments["idempotency_key"].endswith(command.command_sha256[7:])
    with pytest.raises(SchemaError):
        validate_contract("sdxl-target-comparison-command", command.model_dump(mode="json"))


def test_cpu_derivatives_preserve_parent_and_transform_free_replay(tmp_path, monkeypatch):
    prepared, root, _, parent = _worker(tmp_path, monkeypatch)
    before = {file.member_path: (root / file.member_path).read_bytes() for file in prepared.files}
    result = worker.run_sdxl_publication_comparison(command=prepared.command, workspace=root)
    assert result.status == "SUCCEEDED" and len(result.outputs) == len(parent.outputs)
    assert (
        result.quality_state == "UNREVIEWED_PUBLICATION_CANDIDATES"
        and result.activation_policy == "FORBIDDEN"
    )
    assert "torch" not in sys.modules
    validate_sdxl_publication_result(prepared.command, prepared.sources, result)
    validate_contract("sdxl-publication-comparison-result", result.model_dump(mode="json"))
    assert all((root / name).read_bytes() == pixels for name, pixels in before.items())
    files = {
        path: (path.stat().st_mtime_ns, path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    }

    def denied(*args, **kwargs):
        pytest.fail("replay entered the pixel transform")

    assert (
        worker.run_sdxl_publication_comparison(
            command=prepared.command, workspace=root, postprocessor=denied
        )
        == result
    )
    assert all(
        (path.stat().st_mtime_ns, path.read_bytes()) == snapshot for path, snapshot in files.items()
    )
    assert worker.load_sdxl_publication_command(root, root / "command.json") == prepared.command


@pytest.mark.parametrize(
    "fault",
    ["scope", "activation", "schema", "member", "policy", "policy_hash", "hash", "utc", "budget"],
)
def test_command_rejects_loosened_scope_policy_or_identity(tmp_path, monkeypatch, fault):
    command, *_ = _fixture(tmp_path, monkeypatch)
    value = command.model_dump(mode="json")
    if fault == "scope":
        value["case_relation"] = "HOLDOUT_PASS"
    elif fault == "activation":
        value["activation_policy"] = "ALLOWED"
    elif fault == "schema":
        value["source_result"]["schema_ref"] = "eom://schemas/image-provider/unknown/1.0"
    elif fault == "member":
        value["source_result"]["member_path"] = "../../untrusted.json"
    elif fault == "policy":
        value["postprocess"]["foreground_ratio_max"] = 0.99
    elif fault == "policy_hash":
        value["policy_sha256"] = "sha256:" + "0" * 64
    elif fault == "utc":
        value["created_at"] = "2026-10-04T09:00:00"
    elif fault == "budget":
        value["budget"]["maximum_outputs"] = 7
    if fault != "hash":
        value = _seal(value)
    else:
        value["command_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValidationError):
        LocalImageSdxlPublicationComparisonCommand.model_validate(value)


@pytest.mark.parametrize("fault", ["missing", "stale", "hash", "lineage", "parent_failed", "time"])
def test_invalid_parent_or_lineage_is_rejected_before_pixels(tmp_path, monkeypatch, fault):
    command, records, _source_metadata, parent, trace = _fixture(tmp_path, monkeypatch)
    if fault in {"missing", "stale"}:
        records.pop(command.source_result)
    elif fault == "hash":
        records[command.source_result] = b"{}"
    elif fault == "lineage":

        def denied(*args):
            raise ValueError("missing original PDF")

        monkeypatch.setattr(admission, "resolve_sdxl_target_comparison_metadata", denied)
    elif fault == "parent_failed":
        value = parent.model_dump(mode="json")
        value.update(status="FAILED", error_code="SDXL_PROBE_EXEC_FAILED")
        value["result_sha256"] = content_sha256(
            {k: v for k, v in value.items() if k != "result_sha256"}
        )
        payload = content_json_bytes(value)
        pointer = command.source_result.model_copy(
            update={"sha256": "sha256:" + hashlib.sha256(payload).hexdigest()}
        )
        records[pointer] = payload
        value = command.model_dump(mode="json")
        value["source_result"] = pointer.model_dump(mode="json")
        command = LocalImageSdxlPublicationComparisonCommand.model_validate(_seal(value))
    else:
        value = command.model_dump(mode="json")
        value["created_at"] = (
            (parent.completed_at - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        )
        command = LocalImageSdxlPublicationComparisonCommand.model_validate(_seal(value))
    with pytest.raises((ValueError, KeyError, ValidationError)):
        admission.prepare_sdxl_publication_inputs(object(), command)
    assert "NATIVE_PIXELS" not in trace


@pytest.mark.parametrize(
    "member",
    [
        "command.json",
        "inputs/parent-command.json",
        "inputs/parent-result.json",
        "inputs/source-crop-set.json",
        "native",
        "result",
        "output",
    ],
)
def test_tamper_or_missing_pixels_never_reprocess(tmp_path, monkeypatch, member):
    prepared, root, _, _ = _worker(tmp_path, monkeypatch)
    if member in {"result", "output"}:
        result = worker.run_sdxl_publication_comparison(command=prepared.command, workspace=root)
        member = "result.json" if member == "result" else result.outputs[0].member_path
    elif member == "native":
        member = next(
            file.member_path for file in prepared.files if file.member_path.endswith(".png")
        )
    _write(root / member, b"tampered")

    def denied(*args, **kwargs):
        pytest.fail("invalid input/output entered transform")

    with pytest.raises(ProviderError):
        worker.run_sdxl_publication_comparison(
            command=prepared.command, workspace=root, postprocessor=denied
        )


def test_partial_failure_is_not_success_and_replays_without_transform(tmp_path, monkeypatch):
    prepared, root, _, _ = _worker(tmp_path, monkeypatch)
    calls = []

    def failing(payload, *, policy):
        calls.append(payload)
        if len(calls) == 2:
            raise AssessmentLineArtError("LOCAL_IMAGE_LINE_ART_FINE_DETAIL_INVALID")
        return assessment_line_art_v2(payload, policy=policy)

    result = worker.run_sdxl_publication_comparison(
        command=prepared.command, workspace=root, postprocessor=failing
    )
    assert (
        result.status == "FAILED"
        and result.error_code == "LOCAL_IMAGE_LINE_ART_FINE_DETAIL_INVALID"
    )
    assert len(result.outputs) == 1
    assert (
        worker.run_sdxl_publication_comparison(
            command=prepared.command, workspace=root, postprocessor=failing
        )
        == result
    )
    assert len(calls) == 2


def test_unreceipted_output_and_wrong_runtime_do_not_enter_transform(tmp_path, monkeypatch):
    prepared, root, _, _ = _worker(tmp_path, monkeypatch)
    (root / "outputs").mkdir(mode=0o700)
    with pytest.raises(ProviderError, match="OUTPUT_INVALID"):
        worker.run_sdxl_publication_comparison(command=prepared.command, workspace=root)
    other = tmp_path / "wrong-runtime"
    other.mkdir(mode=0o700)
    value = prepared.command.model_dump(mode="json")
    value["pillow_version"] = "0.0.0"
    command = LocalImageSdxlPublicationComparisonCommand.model_validate(_seal(value))
    for file in prepared.files:
        _write(other / file.member_path, file.payload)
    _write(other / "command.json", content_json_bytes(command.model_dump(mode="json")))
    with pytest.raises(ProviderError, match="INPUT_INVALID"):
        worker.run_sdxl_publication_comparison(command=command, workspace=other)
    assert not (other / "outputs").exists()


@pytest.mark.parametrize(
    "fault", ["missing", "order", "source", "hash", "quality", "tones", "metric", "runtime"]
)
def test_false_success_and_quality_claims_fail(tmp_path, monkeypatch, fault):
    prepared, root, _, _ = _worker(tmp_path, monkeypatch)
    result = worker.run_sdxl_publication_comparison(command=prepared.command, workspace=root)
    value = result.model_dump(mode="json")
    if fault == "missing":
        value["outputs"].pop()
    elif fault == "order":
        value["outputs"].reverse()
    elif fault == "source":
        value["outputs"][0]["source"]["artifact_revision_id"] = "rev_" + "0" * 32
    elif fault == "quality":
        value["quality_state"] = "ACCEPTED"
    elif fault == "tones":
        value["outputs"][0]["output_tones"] = [255, 96]
    elif fault == "metric":
        value["outputs"][0]["metrics"]["output_fine_detail_ratio"] = 0.99
    elif fault == "runtime":
        value["runtime"]["pillow_version"] = "0.0.0"
    if fault != "hash":
        value["result_sha256"] = content_sha256(
            {k: v for k, v in value.items() if k != "result_sha256"}
        )
    else:
        value["result_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        changed = LocalImageSdxlPublicationComparisonResult.model_validate(value)
        validate_sdxl_publication_result(prepared.command, prepared.sources, changed)


@pytest.mark.parametrize("fault", [None, "missing", "extra", "duplicate", "hash"])
def test_exclusive_handoff_exact_input_closure(tmp_path, monkeypatch, fault):
    prepared, _, _ = _prepared(tmp_path, monkeypatch)
    parent, owner, _ = _operator(monkeypatch, tmp_path)
    files = list(prepared.files)
    if fault == "missing":
        files.pop()
    elif fault == "extra":
        files.append(replace(files[-1], member_path="inputs/extra"))
    elif fault == "duplicate":
        files.append(files[-1])
    elif fault == "hash":
        files[-1] = replace(files[-1], payload=b"bad")
    if fault:
        with pytest.raises((ValueError, KeyError, handoff.SdxlProbeHandoffError)):
            handoff.stage_sdxl_publication_inputs(
                replace(prepared, files=tuple(files)), workspace_parent=parent, worker=owner
            )
        assert not list(parent.iterdir())
    else:
        staged = handoff.stage_sdxl_publication_inputs(
            prepared, workspace_parent=parent, worker=owner
        )
        assert (
            staged.systemd_unit
            == f"eom-image-sdxl-publication-comparison@{prepared.command.run_id}.service"
        )
        assert all(
            (staged.workspace / file.member_path).stat().st_mode & 0o777 == 0o440
            for file in prepared.files
        )
        with pytest.raises(handoff.SdxlProbeHandoffError, match="EXISTS"):
            handoff.stage_sdxl_publication_inputs(prepared, workspace_parent=parent, worker=owner)


def test_schema_resources_and_cpu_unit_are_explicit():
    root = Path(__file__).resolve().parents[2]
    for kind in ("command", "result"):
        name = f"local-image-sdxl-publication-comparison-{kind}-v1.schema.json"
        source = (root / "schemas/image-provider" / name).read_bytes()
        installed = (
            root / "packages/image_contracts/eom_image_contracts/schemas" / name
        ).read_bytes()
        assert (
            source == installed
            and json.loads(source)["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        )
    unit = (root / "infra/systemd/eom-image-sdxl-publication-comparison@.service").read_text()
    for required in (
        "PrivateDevices=true",
        "PrivateNetwork=true",
        "User=eom-image",
        "Restart=no",
        "InaccessiblePaths=/mnt/nas",
        "InaccessiblePaths=/srv/eom/models/image",
        "InaccessiblePaths=/home/eom/EOM",
        "sdxl-publication-comparison --command",
        "TimeoutStartSec=120",
    ):
        assert required in unit
    assert "gpu-lock" not in unit and "model-store-root" not in unit


@pytest.mark.parametrize("fault", ["symlink", "hardlink", "group_writable", "workspace_writable"])
def test_unsafe_materializations_fail_before_transform(tmp_path, monkeypatch, fault):
    prepared, root, _, _ = _worker(tmp_path, monkeypatch)
    member = next(file.member_path for file in prepared.files if file.member_path.endswith(".png"))
    target = root / member
    if fault in {"symlink", "hardlink"}:
        other = tmp_path / "other.png"
        if fault == "symlink":
            target.rename(other)
            target.symlink_to(other)
        else:
            os.link(target, other)
    elif fault == "group_writable":
        target.chmod(0o660)
    else:
        root.chmod(0o770)

    def denied(*args, **kwargs):
        pytest.fail("unsafe materialization entered transform")

    with pytest.raises(ProviderError, match="INPUT_INVALID"):
        worker.run_sdxl_publication_comparison(
            command=prepared.command, workspace=root, postprocessor=denied
        )
    assert not (root / "outputs").exists()


@pytest.mark.parametrize("fault", ["mode", "dimensions", "color"])
def test_native_media_or_derivative_color_is_not_silently_converted(fault):
    image = Image.new("RGB", (800, 500), "white")
    if fault == "mode":
        image = image.convert("L")
    elif fault == "dimensions":
        image = image.resize((801, 500))
    else:
        image.putpixel((300, 200), (32, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    with pytest.raises(ValueError):
        worker.publication_png_tones(buffer.getvalue(), mode="RGB")


@pytest.mark.parametrize("fault", ["before", "after", "unexpected"])
def test_budget_and_unexpected_failures_are_terminal_and_do_not_auto_retry(
    tmp_path, monkeypatch, fault
):
    prepared, root, _, _ = _worker(tmp_path, monkeypatch)
    calls = []
    clock = iter([0.0, 91.0] if fault == "before" else [0.0, 0.0, 91.0])
    if fault != "unexpected":
        monkeypatch.setattr(worker.time, "monotonic", lambda: next(clock, 91.0))

    def processor(payload, *, policy):
        calls.append(payload)
        if fault == "unexpected":
            raise RuntimeError("private operator details must not enter receipt")
        return assessment_line_art_v2(payload, policy=policy)

    result = worker.run_sdxl_publication_comparison(
        command=prepared.command, workspace=root, postprocessor=processor
    )
    assert result.status == "FAILED" and not result.outputs
    assert result.error_code == (
        "SDXL_PUBLICATION_EXEC_FAILED"
        if fault == "unexpected"
        else "SDXL_PUBLICATION_BUDGET_EXCEEDED"
    )
    count = len(calls)
    assert count == (0 if fault == "before" else 1)
    assert (
        worker.run_sdxl_publication_comparison(
            command=prepared.command, workspace=root, postprocessor=processor
        )
        == result
    )
    assert len(calls) == count
    assert "private operator" not in (root / "result.json").read_text()


def test_extra_output_is_not_accepted_on_replay(tmp_path, monkeypatch):
    prepared, root, _, _ = _worker(tmp_path, monkeypatch)
    worker.run_sdxl_publication_comparison(command=prepared.command, workspace=root)
    _write(root / "outputs/base/unreceipted.png", b"unexpected")
    with pytest.raises(ProviderError, match="OUTPUT_INVALID"):
        worker.run_sdxl_publication_comparison(command=prepared.command, workspace=root)


@pytest.mark.parametrize("fault", [None, "unit", "workspace", "hash", "timeout"])
def test_dispatch_only_exact_fixed_cpu_unit_no_second_identity(tmp_path, monkeypatch, fault):
    monkeypatch.setattr(handoff.os, "geteuid", lambda: 0)
    run = "imgsdxlpublicationrun_" + "a" * 32
    staged = handoff.StagedSdxlProbe(
        Path("/srv/eom/image-training-workspaces") / run,
        f"eom-image-sdxl-publication-comparison@{run}.service",
        "sha256:" + "a" * 64,
    )
    calls = []

    def submit(args, **kwargs):
        calls.append((args, kwargs))
        if fault == "timeout":
            raise handoff.subprocess.TimeoutExpired(args, 30)

    monkeypatch.setattr(handoff.subprocess, "run", submit)
    if fault == "unit":
        staged = replace(staged, systemd_unit="eom-image-sdxl-lineart-probe@" + run + ".service")
    elif fault == "workspace":
        staged = replace(staged, workspace=tmp_path / run)
    elif fault == "hash":
        staged = replace(staged, command_sha256="invalid")
    if fault:
        with pytest.raises(handoff.SdxlProbeHandoffError):
            handoff.dispatch_sdxl_publication_comparison(staged)
    else:
        handoff.dispatch_sdxl_publication_comparison(staged)
    assert len(calls) == (1 if fault in {None, "timeout"} else 0)
    if calls:
        assert calls[0][0] == ["systemctl", "start", "--no-block", staged.systemd_unit]
