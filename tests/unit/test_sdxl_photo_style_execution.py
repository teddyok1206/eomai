"""Simulated paired execution and authority boundaries, never image-quality acceptance."""

from __future__ import annotations

import copy
import io
import os
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from eom_image_contracts.models import (
    ImageEvaluationArtifactMember,
    content_json_bytes,
    content_sha256,
)
from eom_image_contracts.sdxl_photo_style import photo_style_artifact_pointer
from eom_image_contracts.sdxl_photo_style_execution import (
    parse_photo_style_command,
    parse_photo_style_plan,
    parse_photo_style_result,
    validate_photo_style_result,
)
from eom_image_contracts.validation import SCHEMA_FILES, SCHEMA_SHA256
from eom_image_provider import sdxl_pair_inference as pair
from eom_image_provider import sdxl_photo_style as worker
from eom_image_provider import sdxl_reference_pixels as pixels
from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_canny_pixels import canny_conditioning_canvas_png
from eom_image_provider.sdxl_comparison_command import load_sdxl_comparison_command
from eom_orchestrator import sdxl_photo_style_inputs as admission
from eom_orchestrator import sdxl_probe_workspace as handoff
from eom_orchestrator import sdxl_validation_inputs as reserved
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from jsonschema import ValidationError as SchemaError
from PIL import Image
from pydantic import ValidationError

from tests.unit.test_local_image_training_control_artifacts import _Publisher
from tests.unit.test_sdxl_learned_comparison import _Backend
from tests.unit.test_sdxl_micro_runner import _write
from tests.unit.test_sdxl_native_validation import _native_fixture
from tests.unit.test_sdxl_photo_style import _native_plan, _sha, _source
from tests.unit.test_sdxl_probe_workspace import _operator


def _seal(value):
    value = copy.deepcopy(value)
    value.pop("run_id", None)
    value.pop("command_sha256", None)
    value["run_id"] = "imgsdxlvalcmprun_" + content_sha256(value)[7:39]
    value["command_sha256"] = content_sha256(value)
    return value


def _fixture(tmp_path, monkeypatch):
    old, reader, events = _native_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        admission,
        "resolve_sdxl_canny_reference_metadata",
        reserved.resolve_sdxl_canny_reference_metadata,
    )
    encoded = io.BytesIO()
    Image.new("RGB", (800, 504), (160, 190, 215)).save(encoded, format="PNG")
    photo = encoded.getvalue()
    source, bundle, intent = _source(normalized_bytes=photo)
    plan = _native_plan(source, old)
    plan_raw = content_json_bytes(plan.model_dump(mode="json"))
    pin = ImageEvaluationArtifactMember(
        artifact_id="artifact_" + "f" * 32,
        artifact_revision_id="rev_" + "f" * 32,
        member_path="manifests/sdxl-photo-style-plan.json",
        schema_ref="eom://schemas/image-provider/local-image-sdxl-photo-style-plan/1.0",
        media_type="application/json",
        sha256=_sha(plan_raw),
    )
    reader.records.update(
        {
            pin: plan_raw,
            photo_style_artifact_pointer(source.reference.bundle_manifest): bundle,
            photo_style_artifact_pointer(source.bundle.intent): intent,
            photo_style_artifact_pointer(source.reference.reference_member): photo,
        }
    )
    monkeypatch.setattr(admission, "resolve_control_artifact_member", reader)
    monkeypatch.setattr(
        admission,
        "resolve_control_artifact_members",
        lambda engine, reads: tuple(
            reader(engine, r.pointer, maximum_bytes=r.maximum_bytes) for r in reads
        ),
    )
    command = parse_photo_style_command(
        _seal(
            dict(
                schema_version="local-image-sdxl-photo-style-command/1.0",
                source_commit="d" * 40,
                created_at=(plan.created_at + timedelta(seconds=1))
                .isoformat()
                .replace("+00:00", "Z"),
                purpose="EVALUATION_ONLY_PHOTO_TO_EXAM_STYLE",
                activation_policy="FORBIDDEN",
                plan=pin.model_dump(mode="json"),
                plan_id=plan.plan_id,
                plan_sha256=plan.plan_sha256,
            )
        )
    )
    return command, reader, events


def _stage(tmp_path, monkeypatch):
    command, _, _ = _fixture(tmp_path, monkeypatch)
    prepared = admission.prepare_sdxl_photo_style_inputs(object(), command)
    root = tmp_path / "photo"
    root.mkdir(mode=0o700)
    for file in prepared.files:
        _write(root / file.member_path, file.payload)
    leases = []

    class Clock:
        @staticmethod
        def now(_zone):
            return command.created_at + timedelta(seconds=2)

    @contextmanager
    def lease(_path):
        leases.append("ENTER")
        try:
            yield
        finally:
            leases.append("EXIT")

    def canny(canvas, *, policy):
        return canny_conditioning_canvas_png(
            canvas,
            policy=policy,
            extractor=lambda gray, **kwargs: b"\xff" + b"\x00" * (len(gray) - 1),
        )

    monkeypatch.setattr(worker, "datetime", Clock)
    monkeypatch.setattr(pair, "acquire_gpu_lease", lease)
    monkeypatch.setattr(worker, "resolve_sdxl_stack", lambda *a, **k: object())
    monkeypatch.setattr(worker, "resolve_sdxl_canny_controller", lambda *a, **k: object())
    monkeypatch.setattr(
        worker,
        "read_canny_runtime",
        lambda: prepared.metadata.sources.configuration_sources.spatial_sources.preparation.runtime,
    )
    monkeypatch.setattr(worker, "canny_conditioning_canvas_png", canny)
    monkeypatch.setattr(worker.metadata, "version", lambda name: "11.3.0")
    return prepared, root, leases


def _run(prepared, root, backend):
    return worker.run_sdxl_photo_style(
        command=prepared.command,
        workspace=root,
        model_store_root=root / "models",
        gpu_lock=root / "gpu.lock",
        backend_factory=lambda *args: backend,
    )


def test_schema_resources_command_publication_and_registered_plan(tmp_path, monkeypatch):
    command, reader, _ = _fixture(tmp_path, monkeypatch)
    assert parse_photo_style_plan(command, reader.records[command.plan]).plan_id == command.plan_id
    for family in ("command", "result"):
        key = "sdxl-photo-style-" + family
        name = SCHEMA_FILES[key]
        root = Path(__file__).resolve().parents[2]
        raw = (root / "schemas/image-provider" / name).read_bytes()
        assert (
            raw
            == (root / "packages/image_contracts/eom_image_contracts/schemas" / name).read_bytes()
        )
        assert _sha(raw) == SCHEMA_SHA256[key]
    pub = LocalImageTrainingControlArtifactPublisher(
        _Publisher(), source_commit=command.source_commit
    )
    pointer = pub.commit_sdxl_photo_style_command(command)
    assert pointer.member_path == "manifests/sdxl-photo-style-command.json"
    assert pointer.sha256 == _sha(content_json_bytes(command.model_dump(mode="json")))
    with pytest.raises(ValueError, match="source commit"):
        LocalImageTrainingControlArtifactPublisher(
            _Publisher(), source_commit="e" * 40
        ).commit_sdxl_photo_style_command(command)


@pytest.mark.parametrize(
    "field,value",
    [
        ("activation_policy", "ALLOWED"),
        ("plan_sha256", "sha256:" + "0" * 64),
        ("plan_id", "imgsdxlphotoplan_" + "0" * 32),
        ("unexpected", True),
    ],
)
def test_command_scope_and_identity_are_closed(tmp_path, monkeypatch, field, value):
    command, reader, _ = _fixture(tmp_path, monkeypatch)
    body = command.model_dump(mode="json")
    body[field] = value
    with pytest.raises((ValueError, ValidationError, SchemaError)):
        parsed = parse_photo_style_command(_seal(body))
        parse_photo_style_plan(parsed, reader.records[command.plan])


def test_metadata_first_selected_native_weights_and_bounded_existing_handoff(tmp_path, monkeypatch):
    command, reader, _ = _fixture(tmp_path, monkeypatch)
    metadata = admission.resolve_sdxl_photo_style_execution_metadata(object(), command)
    assert all(p.media_type == "application/json" for p in reader.calls)
    reader.calls.clear()
    prepared = admission.prepare_sdxl_photo_style_inputs(object(), command)
    binary = [p for p in reader.calls if p.media_type != "application/json"]
    assert [p.member_path for p in binary] == [
        "references/primary.png",
        "adapter/adapter_model.safetensors",
    ]
    assert prepared.metadata.sources == metadata.sources
    expected = admission.sdxl_photo_style_input_hashes(prepared)
    assert {f.member_path: f.sha256 for f in prepared.files} == expected
    parent, owner, _ = _operator(monkeypatch, tmp_path)
    staged = handoff.stage_sdxl_photo_style_inputs(prepared, workspace_parent=parent, worker=owner)
    assert staged.systemd_unit == "eom-image-sdxl-learned-comparison@" + command.run_id + ".service"
    with pytest.raises(handoff.SdxlProbeHandoffError, match="WORKSPACE_EXISTS"):
        handoff.stage_sdxl_photo_style_inputs(prepared, workspace_parent=parent, worker=owner)


@pytest.mark.parametrize("fault", [None, "second", "oom", "unexpected"])
def test_paired_execution_exact_native_lineage_and_no_side_effect_replay(
    tmp_path, monkeypatch, fault
):
    prepared, root, leases = _stage(tmp_path, monkeypatch)
    backend = _Backend(fault)
    result = _run(prepared, root, backend)
    assert result.status == ("SUCCEEDED" if fault is None else "FAILED")
    assert len(result.outputs) == {None: 2, "second": 1, "oom": 0, "unexpected": 0}[fault]
    assert result.initialization.denoising_strength == 0.7
    assert (
        result.native_adapter_manifest_sha256
        == prepared.metadata.sources.configuration_sources.native.manifest.manifest_sha256
    )
    assert parse_photo_style_result(result.model_dump(mode="json")) == result
    assert load_sdxl_comparison_command(root, root / "command.json") == prepared.command
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()}

    def forbidden(*a, **k):
        pytest.fail("replay repeated transforms/model/GPU/writes")

    for name in (
        "resolve_sdxl_stack",
        "resolve_sdxl_canny_controller",
        "read_canny_runtime",
        "load_sdxl_lora_material",
        "prepare_sdxl_reference_pixels",
        "run_sdxl_pair_inference",
        "write_staged_member",
        "create_sdxl_pair_directories",
    ):
        monkeypatch.setattr(worker, name, forbidden)
    monkeypatch.setattr(pixels, "sdxl_canny_native_source_canvas", forbidden)
    assert _run(prepared, root, _Backend()) == result
    assert before == {
        p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()
    }
    assert leases == ["ENTER", "EXIT"]


@pytest.mark.parametrize("fault", ["plan", "bundle", "native", "photo", "weight"])
def test_staged_tamper_never_acquires_gpu(tmp_path, monkeypatch, fault):
    prepared, root, leases = _stage(tmp_path, monkeypatch)
    paths = {
        "plan": "plan.json",
        "bundle": next(
            f.member_path for f in prepared.files if f.member_path.endswith("/bundle.json")
        ),
        "native": "inputs/native-training-command.json",
        "photo": prepared.metadata.sources.plan.cases[0].case.staged_member_path,
        "weight": "inputs/adapter/adapter_model.safetensors",
    }
    path = root / paths[fault]
    if fault == "native":
        path = root / next(
            f.member_path
            for f in prepared.files
            if f.member_path.startswith("inputs/metadata/") and f.member_path.endswith(".json")
        )
    path.write_bytes(b"broken")
    if fault == "weight":
        result = _run(prepared, root, _Backend())
        assert result.status == "FAILED"
        assert result.outputs == ()
    else:
        with pytest.raises(ProviderError):
            _run(prepared, root, _Backend())
    assert leases == []
    assert (root / "result.json").exists() == (fault == "weight")


def test_handoff_source_replacement_is_not_trusted(tmp_path, monkeypatch):
    command, _, _ = _fixture(tmp_path, monkeypatch)
    prepared = admission.prepare_sdxl_photo_style_inputs(object(), command)
    broken = replace(prepared.metadata.sources.native_training_sources, targets=())
    changed = replace(
        prepared,
        metadata=replace(
            prepared.metadata,
            sources=replace(prepared.metadata.sources, native_training_sources=broken),
        ),
    )
    with pytest.raises(ValueError, match="HANDOFF"):
        admission.sdxl_photo_style_input_hashes(changed)


@pytest.mark.parametrize("fault", ["trace", "plan", "adapter", "prefix", "activation"])
def test_rehashed_results_cannot_change_evidence(tmp_path, monkeypatch, fault):
    prepared, root, _ = _stage(tmp_path, monkeypatch)
    result = _run(prepared, root, _Backend())
    value = result.model_dump(mode="json", exclude={"result_sha256"})
    if fault == "trace":
        value["inputs"][0]["source_sha256"] = "sha256:" + "0" * 64
    if fault == "plan":
        value["plan_sha256"] = "sha256:" + "0" * 64
    if fault == "adapter":
        value["native_adapter_manifest_sha256"] = "sha256:" + "0" * 64
    if fault == "prefix":
        value["outputs"] = value["outputs"][1:]
    if fault == "activation":
        value["activation_policy"] = "ALLOWED"
    with pytest.raises((ValueError, ValidationError, SchemaError)):
        changed = parse_photo_style_result({**value, "result_sha256": content_sha256(value)})
        validate_photo_style_result(prepared.command, prepared.metadata.sources, changed)


def test_transform_verifier_is_read_only_and_checks_declared_pixels(tmp_path, monkeypatch):
    prepared, root, leases = _stage(tmp_path, monkeypatch)
    result = _run(prepared, root, _Backend())
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()}
    assert worker.verify_sdxl_photo_style_transforms(root) == result
    assert before == {
        p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()
    }
    assert leases == ["ENTER", "EXIT"]
    monkeypatch.setattr(
        worker, "sdxl_canny_native_source_canvas", lambda *a, **k: Image.new("L", (832, 512), 0)
    )
    with pytest.raises(ProviderError, match="OUTPUT_INVALID"):
        worker.verify_sdxl_photo_style_transforms(root)


@pytest.mark.parametrize("fault", [None, "canonical", "command", "transform", "input"])
def test_publication_reuses_owner_and_never_copies_sources(tmp_path, monkeypatch, fault):
    from scripts.image_trainer import sdxl_validation_publication as publication

    prepared, root, _ = _stage(tmp_path, monkeypatch)
    result = _run(prepared, root, _Backend())
    events = []
    command_raw = content_json_bytes(prepared.command.model_dump(mode="json"))
    pointer = prepared.command.plan.model_copy(
        update={
            "member_path": "manifests/sdxl-photo-style-command.json",
            "schema_ref": "eom://schemas/image-provider/local-image-sdxl-photo-style-command/1.0",
            "sha256": _sha(command_raw),
        }
    )
    monkeypatch.setattr(
        publication,
        "resolve_control_artifact_member",
        lambda *a, **k: command_raw if fault != "command" else b"broken",
    )

    def readmit(*args):
        events.append("CANONICAL_READMIT")
        if fault == "canonical":
            raise ValueError("canonical source invalid")
        return prepared

    class Publisher:
        def __init__(self, engine):
            pass

        def publish(self, **kwargs):
            events.append("ARTIFACT_COMMIT")
            assert len(kwargs["members"]) == 7  # result +2 pixels +4 paired raw/final
            assert not any(m.file_name.startswith("inputs/") for m in kwargs["members"])
            assert kwargs["primary_file"] == "manifests/sdxl-photo-style-result.json"
            assert (
                kwargs["idempotency_key"]
                == "sdxl-photo-style-result:" + prepared.command.command_sha256[7:]
            )
            return kwargs

    def verify(workspace, expected):
        events.append("CPU_TRANSFORMS")
        if fault == "transform":
            raise ValueError("transform invalid")
        assert (
            content_json_bytes(
                worker.verify_sdxl_photo_style_transforms(workspace).model_dump(mode="json")
            )
            == expected
        )

    monkeypatch.setattr(publication, "prepare_sdxl_photo_style_inputs", readmit)
    monkeypatch.setattr(publication, "ControlFileSetPublisher", Publisher)
    monkeypatch.setattr(publication, "verify_reserved_transforms_cpu", verify)
    if fault == "input":
        (root / prepared.metadata.sources.plan.cases[0].case.staged_member_path).write_bytes(
            b"broken"
        )

    def call():
        return publication.publish_sdxl_photo_style_comparison(
            object(),
            prepared.command,
            command_pointer=pointer,
            workspace=root,
            worker_uid=os.getuid(),
            source_commit=prepared.command.source_commit,
            created_at=result.completed_at + timedelta(seconds=1),
        )

    if fault is None:
        call()
        assert events == ["CANONICAL_READMIT", "CPU_TRANSFORMS", "ARTIFACT_COMMIT"]
    else:
        with pytest.raises((ValueError, ProviderError)):
            call()
        assert "ARTIFACT_COMMIT" not in events


@pytest.mark.parametrize(
    "fault", ["initializer", "control", "raw", "final", "extra", "noncanonical"]
)
def test_terminal_evidence_tamper_is_rejected_without_regeneration(tmp_path, monkeypatch, fault):
    prepared, root, leases = _stage(tmp_path, monkeypatch)
    result = _run(prepared, root, _Backend())
    paths = {
        "initializer": "initializers/" + result.inputs[0].case_id + ".png",
        "control": "conditionings/" + result.inputs[0].case_id + ".png",
        "raw": result.outputs[0].raw_member_path,
        "final": result.outputs[0].member_path,
        "extra": "conditionings/extra.png",
    }
    if fault == "noncanonical":
        (root / "result.json").write_bytes((root / "result.json").read_bytes() + b"\n")
    else:
        (root / paths[fault]).write_bytes(b"broken")
    with pytest.raises(ProviderError, match="OUTPUT_INVALID"):
        _run(prepared, root, _Backend())
    assert leases == ["ENTER", "EXIT"]


def test_partial_workspace_is_not_implicitly_retried(tmp_path, monkeypatch):
    prepared, root, leases = _stage(tmp_path, monkeypatch)
    (root / "outputs").mkdir(mode=0o700)
    with pytest.raises(ProviderError, match="OUTPUT_INVALID"):
        _run(prepared, root, _Backend())
    assert leases == []
