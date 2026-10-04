"""CPU source/recipe/replay invariants; synthetic edges do not certify image quality."""

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
from types import SimpleNamespace

import pytest
from eom_image_contracts.models import (
    ImageEvaluationArtifactMember,
    content_json_bytes,
    content_sha256,
)
from eom_image_contracts.sdxl_canny_conditioning import (
    LocalImageSdxlCannyConditioningCommand,
    LocalImageSdxlCannyConditioningResult,
    SdxlCannyPolicy,
    SdxlCannyRuntime,
    parse_sdxl_canny_parent,
    validate_sdxl_canny_result,
)
from eom_image_contracts.validation import SCHEMA_FILES, SCHEMA_SHA256, validate_contract
from eom_image_provider import sdxl_canny_conditioning as worker
from eom_image_provider import sdxl_canny_pixels as pixels
from eom_image_provider.provider import ProviderError
from eom_orchestrator import sdxl_canny_inputs as admission
from eom_orchestrator import sdxl_probe_workspace as handoff
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from eom_orchestrator.sdxl_target_comparison_inputs import ResolvedSdxlTargetComparisonMetadata
from jsonschema import ValidationError as SchemaError
from PIL import Image

from tests.unit.test_local_image_training_control_artifacts import _Publisher
from tests.unit.test_sdxl_micro_runner import _write
from tests.unit.test_sdxl_probe_workspace import _operator
from tests.unit.test_sdxl_target_comparison import _prepare as _target_fixture


def _sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _seal(value):
    value = copy.deepcopy(value)
    value.pop("run_id", None)
    value.pop("command_sha256", None)
    value["run_id"] = "imgsdxlcannyrun_" + content_sha256(value)[7:39]
    value["command_sha256"] = content_sha256(value)
    return value


def _fixture(tmp_path, monkeypatch):
    parent, _ = _target_fixture(tmp_path, monkeypatch)
    raw = content_json_bytes(parent.command.model_dump(mode="json"))
    pin = ImageEvaluationArtifactMember(
        artifact_id="artifact_" + "5" * 32,
        artifact_revision_id="rev_" + "5" * 32,
        member_path="manifests/sdxl-target-comparison-command.json",
        schema_ref="eom://schemas/image-provider/local-image-sdxl-target-comparison-command/1.0",
        media_type="application/json",
        sha256=_sha(raw),
    )
    policy = SdxlCannyPolicy()
    runtime = SdxlCannyRuntime(pillow_version=metadata.version("Pillow"), numpy_version="2.4.6")
    command = LocalImageSdxlCannyConditioningCommand.model_validate(
        _seal(
            dict(
                schema_version="local-image-sdxl-canny-conditioning-command/1.0",
                source_commit="a" * 40,
                created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                purpose="EVALUATION_ONLY_CANNY_INPUT_PREPARATION",
                activation_policy="FORBIDDEN",
                case_relation="REVIEWED_TRAIN_TARGET_NOT_HOLDOUT",
                source_command=pin.model_dump(mode="json"),
                policy=policy.model_dump(mode="json"),
                policy_sha256=content_sha256(policy.model_dump(mode="json")),
                runtime=runtime.model_dump(mode="json"),
                budget=dict(
                    maximum_duration_ms=30000,
                    maximum_outputs=3,
                    maximum_input_png_bytes=16_777_216,
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
    files = {file.member_path: file for file in parent.files}
    records = {
        pin: raw,
        **{
            entry.case.reference_image: files[entry.case.staged_member_path].payload
            for entry in parent.command.cases
        },
    }
    trace = []

    def parent_read(engine, pointer, *, maximum_bytes):
        trace.append("PARENT_METADATA")
        assert pointer == pin
        assert len(records[pointer]) <= maximum_bytes
        return records[pointer]

    def lineage(engine, checked):
        assert checked == parent.command
        trace.append("FULL_LINEAGE")
        return source_metadata

    def batch(engine, reads):
        assert trace[-1] == "FULL_LINEAGE"
        assert all(read.pointer.media_type == "image/png" for read in reads)
        trace.append("ONLY_SOURCE_PNG")
        return tuple(records[read.pointer] for read in reads)

    monkeypatch.setattr(admission, "resolve_control_artifact_member", parent_read)
    monkeypatch.setattr(admission, "resolve_sdxl_target_comparison_metadata", lineage)
    monkeypatch.setattr(admission, "resolve_control_artifact_members", batch)
    monkeypatch.setattr(worker, "read_canny_runtime", lambda: runtime)
    return command, source_metadata, records, trace


def _prepared(tmp_path, monkeypatch):
    command, source_metadata, records, trace = _fixture(tmp_path, monkeypatch)
    prepared = admission.prepare_sdxl_canny_inputs(object(), command)
    assert trace == ["PARENT_METADATA", "FULL_LINEAGE", "ONLY_SOURCE_PNG"]
    return prepared, source_metadata, records


def _worker(tmp_path, monkeypatch):
    prepared, _, _ = _prepared(tmp_path, monkeypatch)
    root = tmp_path / "canny-worker"
    root.mkdir(mode=0o700)
    for file in prepared.files:
        _write(root / file.member_path, file.payload)
    return prepared, root


def _fake_edges(gray, *, width, height, policy):
    assert (width, height) == (832, 512)
    assert (
        policy.threshold_low,
        policy.threshold_high,
        policy.aperture_size,
        policy.l2_gradient,
    ) == (100, 200, 3, False)
    assert len(gray) == width * height
    # Deliberately synthetic: a byte-exact call/receipt test, not an OpenCV quality substitute.
    return bytes([255 if value < 128 else 0 for value in gray])


def _run(prepared, root, extractor=_fake_edges):
    return worker.run_sdxl_canny_conditioning(
        command=prepared.command, workspace=root, extractor=extractor
    )


def test_closed_contract_metadata_first_and_no_weight_materialization(tmp_path, monkeypatch):
    prepared, source_metadata, _ = _prepared(tmp_path, monkeypatch)
    validate_contract("sdxl-canny-conditioning-command", prepared.command.model_dump(mode="json"))
    assert sum(file.member_path.endswith(".png") for file in prepared.files) == len(
        source_metadata.command.cases
    )
    assert not any(
        file.member_path.startswith("inputs/adapter/") or file.member_path.endswith(".safetensors")
        for file in prepared.files
    )
    assert set(admission.sdxl_canny_input_hashes(prepared)) == {
        file.member_path for file in prepared.files
    }
    publisher = _Publisher()
    pointer = LocalImageTrainingControlArtifactPublisher(
        publisher, source_commit=prepared.command.source_commit
    ).commit_sdxl_canny_conditioning_command(prepared.command)
    assert pointer.sha256 == _sha(content_json_bytes(prepared.command.model_dump(mode="json")))
    assert pointer.member_path == "manifests/sdxl-canny-conditioning-command.json"


@pytest.mark.parametrize(
    "field,value",
    [
        ("activation_policy", "ALLOWED"),
        ("case_relation", "HOLDOUT"),
        ("command_sha256", "sha256:" + "0" * 64),
        ("gpu_lock", "/tmp/lock"),
    ],
)
def test_closed_command_rejects_scope_and_hash_changes(tmp_path, monkeypatch, field, value):
    command, _, _, _ = _fixture(tmp_path, monkeypatch)
    changed = command.model_dump(mode="json")
    changed[field] = value
    if field != "command_sha256":
        changed = _seal(changed)
    with pytest.raises((ValueError, SchemaError)):
        validate_contract("sdxl-canny-conditioning-command", changed)
        LocalImageSdxlCannyConditioningCommand.model_validate(changed)


@pytest.mark.parametrize("fault", ["hash", "stale", "canonical", "time"])
def test_parent_source_is_pinned_and_canonical_before_pixels(tmp_path, monkeypatch, fault):
    command, source_metadata, _, trace = _fixture(tmp_path, monkeypatch)
    raw = content_json_bytes(source_metadata.command.model_dump(mode="json"))
    if fault == "hash":
        raw += b" "
    elif fault == "canonical":
        raw = json.dumps(source_metadata.command.model_dump(mode="json"), indent=2).encode()
        changed = command.model_dump(mode="json")
        changed["source_command"]["sha256"] = _sha(raw)
        command = LocalImageSdxlCannyConditioningCommand.model_validate(_seal(changed))
    else:
        changed = command.model_dump(mode="json")
        if fault == "stale":
            changed["source_command"]["sha256"] = "sha256:" + "0" * 64
        else:
            changed["created_at"] = (
                (source_metadata.command.created_at - timedelta(seconds=1))
                .isoformat()
                .replace("+00:00", "Z")
            )
        command = LocalImageSdxlCannyConditioningCommand.model_validate(_seal(changed))
    with pytest.raises(ValueError):
        parse_sdxl_canny_parent(command, raw)
    assert "ONLY_SOURCE_PNG" not in trace


def test_full_lineage_failure_never_reads_source_pixels(tmp_path, monkeypatch):
    command, _, _, trace = _fixture(tmp_path, monkeypatch)

    def denied(*args):
        raise ValueError("unaccepted source revision")

    monkeypatch.setattr(admission, "resolve_sdxl_target_comparison_metadata", denied)
    with pytest.raises(ValueError, match="unaccepted source revision"):
        admission.prepare_sdxl_canny_inputs(object(), command)
    assert trace == ["PARENT_METADATA"]


def test_success_and_byte_preserving_transform_free_replay(tmp_path, monkeypatch):
    prepared, root = _worker(tmp_path, monkeypatch)
    snapshot = {file.member_path: (root / file.member_path).read_bytes() for file in prepared.files}
    calls = []

    def extractor(*args, **kwargs):
        calls.append(True)
        return _fake_edges(*args, **kwargs)

    result = _run(prepared, root, extractor)
    assert result.status == "SUCCEEDED" and result.error_code is None
    assert len(calls) == len(prepared.source_metadata.command.cases) == len(result.outputs)
    assert result.model_executions == result.training_steps == 0
    assert result.preparation_state == "UNREVIEWED_CANNY_INPUTS"
    assert result.activation_policy == "FORBIDDEN"
    for output in result.outputs:
        raw = (root / output.member_path).read_bytes()
        assert _sha(raw) == output.sha256 and len(raw) == output.size_bytes
        assert pixels.canny_png_edge_count(raw) == output.edge_pixels
    before = {
        path: (path.stat().st_mtime_ns, path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    }

    def denied(*args, **kwargs):
        pytest.fail("terminal replay entered Canny")

    assert _run(prepared, root, denied) == result
    assert before == {
        path: (path.stat().st_mtime_ns, path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    }
    assert snapshot == {
        file.member_path: (root / file.member_path).read_bytes() for file in prepared.files
    }


@pytest.mark.parametrize("fault", ["missing", "hash", "extra", "orphan"])
def test_replay_rejects_unreceipted_or_changed_outputs(tmp_path, monkeypatch, fault):
    prepared, root = _worker(tmp_path, monkeypatch)
    result = _run(prepared, root)
    first = root / result.outputs[0].member_path
    if fault == "missing":
        first.rename(root / "removed.png")
    elif fault == "hash":
        first.write_bytes(b"changed")
    elif fault == "extra":
        _write(root / "outputs/conditioning/unreceipted.png", b"extra")
    else:
        (root / "result.json").rename(root / "old-result.json")

    def denied(*args, **kwargs):
        pytest.fail("invalid replay entered Canny")

    with pytest.raises(ProviderError, match="OUTPUT_INVALID"):
        _run(prepared, root, denied)


@pytest.mark.parametrize("fault", ["before", "after", "unexpected", "second"])
def test_terminal_failed_prefix_budget_and_no_automatic_retry(tmp_path, monkeypatch, fault):
    prepared, root = _worker(tmp_path, monkeypatch)
    calls = []
    if fault in {"before", "after"}:
        clock = iter([0.0, 31.0] if fault == "before" else [0.0, 0.0, 31.0])
        monkeypatch.setattr(worker.time, "monotonic", lambda: next(clock, 31.0))

    def extractor(*args, **kwargs):
        calls.append(True)
        if fault == "unexpected":
            raise RuntimeError("private details must not enter receipt")
        if fault == "second" and len(calls) == 2:
            raise ProviderError("SDXL_CANNY_EDGE_INVALID")
        return _fake_edges(*args, **kwargs)

    result = _run(prepared, root, extractor)
    assert result.status == "FAILED"
    assert len(result.outputs) == (1 if fault == "second" else 0)
    assert (
        result.error_code
        == {
            "before": "SDXL_CANNY_BUDGET_EXCEEDED",
            "after": "SDXL_CANNY_BUDGET_EXCEEDED",
            "unexpected": "SDXL_CANNY_EXEC_FAILED",
            "second": "SDXL_CANNY_EDGE_INVALID",
        }[fault]
    )
    count = len(calls)
    assert _run(prepared, root, extractor) == result and len(calls) == count
    assert "private details" not in (root / "result.json").read_text()


@pytest.mark.parametrize(
    "fault",
    ["symlink", "hardlink", "group_writable", "workspace_writable", "source_hash", "runtime"],
)
def test_unsafe_source_and_runtime_fail_before_transform(tmp_path, monkeypatch, fault):
    prepared, root = _worker(tmp_path, monkeypatch)
    member = next(file for file in prepared.files if file.member_path.endswith(".png"))
    target = root / member.member_path
    if fault == "symlink":
        other = tmp_path / "other.png"
        target.rename(other)
        target.symlink_to(other)
    elif fault == "hardlink":
        os.link(target, tmp_path / "other.png")
    elif fault == "group_writable":
        target.chmod(0o660)
    elif fault == "workspace_writable":
        root.chmod(0o770)
    elif fault == "source_hash":
        target.write_bytes(b"wrong")
    else:
        monkeypatch.setattr(
            worker,
            "read_canny_runtime",
            lambda: prepared.command.runtime.model_copy(update={"numpy_version": "0.0.0"}),
        )

    def denied(*args, **kwargs):
        pytest.fail("invalid source/runtime entered Canny")

    with pytest.raises(
        ProviderError, match="RUNTIME_INVALID" if fault == "runtime" else "INPUT_INVALID"
    ):
        _run(prepared, root, denied)
    assert not (root / "outputs").exists()


def test_exact_geometry_and_parameters_are_passed_to_extractor():
    source = Image.new("L", (768, 512), 255)
    source.paste(0, (100, 100, 200, 200))
    raw = io.BytesIO()
    source.save(raw, format="PNG")
    seen = []

    def extractor(gray, *, width, height, policy):
        seen.append(gray)
        assert len(gray) == 832 * 512
        assert set(gray[:832]) == {255}
        assert gray[256 * 832] == gray[256 * 832 + 831] == 255
        return _fake_edges(gray, width=width, height=height, policy=policy)

    rendered = pixels.canny_conditioning_png(
        raw.getvalue(), policy=SdxlCannyPolicy(), extractor=extractor
    )
    assert len(seen) == 1
    assert pixels.canny_png_edge_count(rendered) > 0


@pytest.mark.parametrize("fault", ["mode", "dimensions", "empty_edges", "edge_size", "edge_gray"])
def test_bad_source_or_nonbinary_extractor_output_is_rejected(fault):
    source = Image.new("L", (768, 512), 255)
    source.paste(0, (100, 100, 200, 200))
    if fault == "mode":
        source = source.convert("RGBA")
    elif fault == "dimensions":
        source = source.resize((769, 512))
    raw = io.BytesIO()
    source.save(raw, format="PNG")

    def extractor(gray, **kwargs):
        if fault == "empty_edges":
            return b"\0" * (832 * 512)
        if fault == "edge_size":
            return b"\0"
        if fault == "edge_gray":
            return b"\x60" * (832 * 512)
        return _fake_edges(gray, **kwargs)

    with pytest.raises(ProviderError):
        pixels.canny_conditioning_png(raw.getvalue(), policy=SdxlCannyPolicy(), extractor=extractor)


@pytest.mark.parametrize("fault", ["mode", "dimensions", "color", "gray", "empty"])
def test_media_verifier_rejects_nonbinary_or_nonmatching_conditioning(fault):
    image = Image.new("RGB", (832, 512), (0, 0, 0))
    image.putpixel((400, 200), (255, 255, 255))
    if fault == "mode":
        image = image.convert("L")
    elif fault == "dimensions":
        image = image.resize((833, 512))
    elif fault == "color":
        image.putpixel((400, 200), (255, 0, 0))
    elif fault == "gray":
        image.putpixel((400, 200), (96, 96, 96))
    else:
        image.paste((0, 0, 0), (0, 0, 832, 512))
    raw = io.BytesIO()
    image.save(raw, format="PNG")
    with pytest.raises(ProviderError, match="EDGE_INVALID"):
        pixels.canny_png_edge_count(raw.getvalue())


@pytest.mark.parametrize(
    "fault", ["hash", "source", "order", "quality", "model_count", "runtime", "incomplete"]
)
def test_result_cannot_claim_other_sources_quality_or_execution(tmp_path, monkeypatch, fault):
    prepared, root = _worker(tmp_path, monkeypatch)
    value = _run(prepared, root).model_dump(mode="json")
    if fault == "source":
        value["outputs"][0]["source"]["artifact_revision_id"] = "rev_" + "0" * 32
    elif fault == "order":
        value["outputs"].reverse()
    elif fault == "quality":
        value["preparation_state"] = "ACCEPTED"
    elif fault == "model_count":
        value["model_executions"] = 1
    elif fault == "runtime":
        value["runtime"]["numpy_version"] = "0.0.0"
    elif fault == "incomplete":
        value["outputs"].pop()
    if fault == "hash":
        value["result_sha256"] = "sha256:" + "0" * 64
    else:
        value["result_sha256"] = content_sha256(
            {key: item for key, item in value.items() if key != "result_sha256"}
        )
    with pytest.raises((ValueError, SchemaError)):
        validate_contract("sdxl-canny-conditioning-result", value)
        changed = LocalImageSdxlCannyConditioningResult.model_validate(value)
        validate_sdxl_canny_result(
            prepared.command,
            prepared.source_metadata.command,
            prepared.source_metadata.sources,
            changed,
        )


@pytest.mark.parametrize("fault", [None, "missing", "extra", "duplicate", "hash"])
def test_exclusive_handoff_exact_members_and_collision(tmp_path, monkeypatch, fault):
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
            handoff.stage_sdxl_canny_inputs(
                replace(prepared, files=tuple(files)), workspace_parent=parent, worker=owner
            )
        assert not list(parent.iterdir())
    else:
        staged = handoff.stage_sdxl_canny_inputs(prepared, workspace_parent=parent, worker=owner)
        assert (
            staged.systemd_unit
            == f"eom-image-sdxl-canny-conditioning@{prepared.command.run_id}.service"
        )
        with pytest.raises(handoff.SdxlProbeHandoffError, match="EXISTS"):
            handoff.stage_sdxl_canny_inputs(prepared, workspace_parent=parent, worker=owner)


@pytest.mark.parametrize("fault", [None, "unit", "workspace", "hash", "timeout"])
def test_fixed_cpu_dispatch_no_second_identity(tmp_path, monkeypatch, fault):
    monkeypatch.setattr(handoff.os, "geteuid", lambda: 0)
    run = "imgsdxlcannyrun_" + "a" * 32
    staged = handoff.StagedSdxlProbe(
        Path("/srv/eom/image-training-workspaces") / run,
        f"eom-image-sdxl-canny-conditioning@{run}.service",
        "sha256:" + "a" * 64,
    )
    calls = []

    def submit(args, **kwargs):
        calls.append(args)
        if fault == "timeout":
            raise handoff.subprocess.TimeoutExpired(args, 30)

    monkeypatch.setattr(handoff.subprocess, "run", submit)
    if fault == "unit":
        staged = replace(staged, systemd_unit=f"eom-image-sdxl-lineart-probe@{run}.service")
    elif fault == "workspace":
        staged = replace(staged, workspace=tmp_path / run)
    elif fault == "hash":
        staged = replace(staged, command_sha256="invalid")
    if fault:
        with pytest.raises(handoff.SdxlProbeHandoffError):
            handoff.dispatch_sdxl_canny_conditioning(staged)
    else:
        handoff.dispatch_sdxl_canny_conditioning(staged)
    assert len(calls) == (1 if fault in {None, "timeout"} else 0)


def test_schema_resources_optional_dependency_and_cpu_unit():
    root = Path(__file__).resolve().parents[2]
    for kind in ("command", "result"):
        key = "sdxl-canny-conditioning-" + kind
        name = SCHEMA_FILES[key]
        raw = (root / "schemas/image-provider" / name).read_bytes()
        assert (
            raw
            == (root / "packages/image_contracts/eom_image_contracts/schemas" / name).read_bytes()
        )
        assert _sha(raw) == SCHEMA_SHA256[key]
        assert json.loads(raw)["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    unit = (root / "infra/systemd/eom-image-sdxl-canny-conditioning@.service").read_text()
    assert all(
        entry in unit
        for entry in (
            "PrivateDevices=true",
            "PrivateNetwork=true",
            "User=eom-image",
            "Restart=no",
            "InaccessiblePaths=/mnt/nas",
            "InaccessiblePaths=/srv/eom/models/image",
            "InaccessiblePaths=/home/eom/EOM",
            "CPUQuota=200%",
            "OPENBLAS_NUM_THREADS=1",
        )
    )
    assert "gpu-lock" not in unit and "model-store-root" not in unit
    project = (root / "services/image_provider/pyproject.toml").read_text()
    assert 'sdxl-canny = ["opencv-python-headless==4.11.0.86"]' in project


def test_runtime_rejects_ambiguous_cv2_without_model_import(monkeypatch):
    monkeypatch.setitem(sys.modules, "cv2", SimpleNamespace(__version__="4.11.0"))
    versions = {
        "opencv-python-headless": "4.11.0.86",
        "opencv-python": "4.11.0.86",
        "numpy": "2.4.6",
        "Pillow": "11.3.0",
    }

    def version(name):
        if name not in versions:
            raise metadata.PackageNotFoundError(name)
        return versions[name]

    monkeypatch.setattr(pixels.metadata, "version", version)
    with pytest.raises(ProviderError, match="RUNTIME_INVALID"):
        pixels.read_canny_runtime()
    versions.pop("opencv-python")
    assert pixels.read_canny_runtime() == SdxlCannyRuntime(
        pillow_version="11.3.0", numpy_version="2.4.6"
    )


@pytest.mark.parametrize("fault", [None, "shape", "dtype"])
def test_opencv_adapter_receives_exact_cpu_parameters(monkeypatch, fault):
    import numpy as np

    calls = []

    def canny(source, low, high, **kwargs):
        calls.append((source.shape, low, high, kwargs))
        assert source.dtype == np.uint8
        assert (source.shape, low, high, kwargs) == (
            (512, 832),
            100,
            200,
            {"apertureSize": 3, "L2gradient": False},
        )
        shape = (512, 831) if fault == "shape" else (512, 832)
        dtype = np.float32 if fault == "dtype" else np.uint8
        result = np.zeros(shape, dtype=dtype)
        result[100, 100] = 255
        return result

    settings = []
    monkeypatch.setitem(
        sys.modules,
        "cv2",
        SimpleNamespace(
            Canny=canny,
            setNumThreads=lambda value: settings.append(("threads", value)),
            ocl=SimpleNamespace(setUseOpenCL=lambda value: settings.append(("opencl", value))),
        ),
    )
    if fault:
        with pytest.raises(ProviderError, match="EDGE_INVALID"):
            pixels.opencv_canny_pixels(
                bytes(832 * 512), width=832, height=512, policy=SdxlCannyPolicy()
            )
    else:
        edges = pixels.opencv_canny_pixels(
            bytes(832 * 512), width=832, height=512, policy=SdxlCannyPolicy()
        )
        assert len(edges) == 832 * 512 and set(edges) == {0, 255}
    assert len(calls) == 1
    assert settings == [("threads", 1), ("opencl", False)]
