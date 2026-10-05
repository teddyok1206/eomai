"""Full synthetic native closure through the reserved consumer; no GPU/quality claim."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from eom_image_contracts.models import (
    ImageEvaluationArtifactMember,
    content_json_bytes,
    content_sha256,
    text_sha256,
)
from eom_image_contracts.sdxl_native_canny_reference import (
    LocalImageSdxlNativeCannyReferenceCommandV2,
    native_reference_metadata_pointers,
    parse_reference_sources,
)
from eom_image_contracts.sdxl_native_geometry import LocalImageSdxlNativeGeometryCommandV2
from eom_image_contracts.sdxl_native_lora import LocalImageSdxlNativeLoraResult
from eom_image_contracts.sdxl_native_lora_sources import parse_sdxl_native_lora_sources
from eom_image_contracts.sdxl_validation_comparison import (
    LocalImageSdxlValidationComparisonCommandV2,
    parse_sdxl_validation_command,
    parse_sdxl_validation_result,
    sdxl_validation_adapter,
    validate_sdxl_validation_result,
    validate_sdxl_validation_sources,
)
from eom_image_provider import sdxl_validation_comparison as worker
from eom_image_provider.provider import ProviderError
from eom_orchestrator import sdxl_canny_reference_inputs as reference_admission
from eom_orchestrator import sdxl_validation_inputs as admission
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from eom_orchestrator.sdxl_native_lora_inputs import AdmittedSdxlNativeLoraSources
from eom_orchestrator.sdxl_probe_inputs import SdxlProbeInputMember

from tests.unit import test_sdxl_validation_worker as lifecycle
from tests.unit.test_local_image_training_control_artifacts import _Publisher
from tests.unit.test_sdxl_canny_reference import _seal as seal_reference
from tests.unit.test_sdxl_learned_comparison import _Backend
from tests.unit.test_sdxl_lora_evaluation_contracts import _seal as seal_evaluation
from tests.unit.test_sdxl_native_geometry_successor import _successor_fixture
from tests.unit.test_sdxl_native_lora_contracts import _result_value, _seal_result
from tests.unit.test_sdxl_native_lora_sources import _fixture as training_fixture
from tests.unit.test_sdxl_native_lora_sources import _staged_metadata
from tests.unit.test_sdxl_validation_comparison import _fixture, _seal, _sha


def _native_fixture(tmp_path, monkeypatch):
    old, reader, events = _fixture(tmp_path, monkeypatch)
    anchor = admission.parse_reference_command(json.loads(reader.records[old.configuration_anchor]))
    inherited = admission.resolve_sdxl_canny_reference_metadata(object(), anchor)
    training, records, _, _, _, _, _ = training_fixture(monkeypatch, exterior_batch=True)
    closure = _staged_metadata(records)
    native_sources = parse_sdxl_native_lora_sources(training, closure)
    template, weights, material_sources = _successor_fixture()
    result_value = _result_value(training)
    result_value["adapter_manifest"]["files"] = material_sources.manifest.model_dump(mode="json")[
        "files"
    ]
    result_value.update(
        started_at=(training.created_at + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        completed_at=(training.created_at + timedelta(seconds=2))
        .isoformat()
        .replace("+00:00", "Z"),
    )
    result_value["adapter_manifest"]["created_at"] = result_value["completed_at"]
    for name in ("adapter_id", "adapter_revision_id", "manifest_sha256"):
        result_value["adapter_manifest"].pop(name, None)
    result = LocalImageSdxlNativeLoraResult.model_validate(_seal_result(result_value))

    def pin(model, family, version, number):
        raw = content_json_bytes(model.model_dump(mode="json"))
        pointer = ImageEvaluationArtifactMember(
            artifact_id="artifact_" + f"{number:032x}",
            artifact_revision_id="rev_" + f"{number:032x}",
            member_path="manifests/" + family + ".json",
            schema_ref="eom://schemas/image-provider/local-image-" + family + "/" + version,
            media_type="application/json",
            sha256=_sha(raw),
        )
        reader.records[pointer] = raw
        return pointer

    value = template.model_dump(mode="json")
    value["created_at"] = anchor.created_at.isoformat().replace("+00:00", "Z")
    evaluation_pin = value["evaluation"]
    for field, model, family, version, number in (
        ("training_command", training, "sdxl-native-lora-command", "1.1", 8001),
        ("training_result", result, "sdxl-native-lora-result", "1.0", 8002),
        (
            "adapter_manifest",
            result.adapter_manifest,
            "sdxl-native-lora-adapter-manifest",
            "1.0",
            8002,
        ),
    ):
        evaluation_pin[field] = pin(model, family, version, number).model_dump(mode="json")
    evaluation_pin.update(
        adapter_id=result.adapter_manifest.adapter_id,
        adapter_revision_id=result.adapter_manifest.adapter_revision_id,
        adapter_manifest_sha256=result.adapter_manifest.manifest_sha256,
    )
    # Geometry metadata remains a declared TRAIN diagnostic, never the reserved case authority.
    value["cases"] = [
        dict(
            sample_id=s.sample_id,
            native_canvas=s.canvas,
            training_caption_sha256=s.training_caption_sha256,
        )
        for s in training.training_samples[:2]
    ]
    baseline = inherited.sources.spatial_sources.targets.lora.baseline
    value["negative_prompt_sha256"] = text_sha256(baseline.cases[0].negative_prompt_en)
    evaluation_pin["baseline_command"] = pin(
        baseline, "sdxl-lineart-probe-command", "1.0", 8003
    ).model_dump(mode="json")
    evaluation = LocalImageSdxlNativeGeometryCommandV2.model_validate(seal_evaluation(value))
    reference_value = anchor.model_dump(mode="json")
    reference_value.update(
        schema_version="local-image-sdxl-canny-reference-command/1.2",
        created_at=(old.created_at + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        native_evaluation_command=pin(
            evaluation, "sdxl-lora-evaluation-command", "1.4", 8004
        ).model_dump(mode="json"),
        case_relation="REVIEWED_TRAIN_REFERENCE_NOT_HOLDOUT",
    )
    reference = LocalImageSdxlNativeCannyReferenceCommandV2.model_validate(
        seal_reference(reference_value)
    )
    metadata = {
        file.member_path: file.payload
        for file in inherited.files
        if file.member_path != "command.json"
    }
    for name, pointer in native_reference_metadata_pointers(reference, evaluation).items():
        metadata[name] = reader.records[pointer]
    native_reference_sources = parse_reference_sources(reference, metadata)
    metadata["command.json"] = content_json_bytes(reference.model_dump(mode="json"))
    files = tuple(
        SdxlProbeInputMember(name, _sha(raw), raw) for name, raw in sorted(metadata.items())
    )
    admitted = AdmittedSdxlNativeLoraSources(
        training,
        native_sources,
        tuple(SdxlProbeInputMember(name, _sha(raw), raw) for name, raw in sorted(closure.items())),
    )
    inherited = replace(
        inherited,
        command=reference,
        sources=native_reference_sources,
        files=files,
        native_admission=admitted,
    )
    monkeypatch.setattr(admission, "resolve_sdxl_canny_reference_metadata", lambda *a: inherited)
    value = old.model_dump(mode="json")
    value.update(
        schema_version="local-image-sdxl-validation-comparison-command/1.1",
        created_at=(old.created_at + timedelta(seconds=2)).isoformat().replace("+00:00", "Z"),
        configuration_anchor=pin(reference, "sdxl-canny-reference-command", "1.2", 8005).model_dump(
            mode="json"
        ),
    )
    command = LocalImageSdxlValidationComparisonCommandV2.model_validate(_seal(value))
    for file in result.adapter_manifest.files:
        previous = next(p for p in weights if p.member_path == "adapter/" + file.relative_path)
        reader.records[
            previous.model_copy(
                update={
                    "artifact_id": "artifact_" + f"{8002:032x}",
                    "artifact_revision_id": "rev_" + f"{8002:032x}",
                }
            )
        ] = weights[previous]
    reader.calls.clear()
    return command, reader, events


def test_native_reserved_full_source_closure_and_selected_adapter(tmp_path, monkeypatch):
    command, reader, events = _native_fixture(tmp_path, monkeypatch)
    prepared = admission.prepare_sdxl_validation_inputs(object(), command)
    configuration = prepared.metadata.sources.configuration
    selected = sdxl_validation_adapter(configuration)
    assert selected.manifest == configuration.sources.native.manifest
    assert selected.manifest != configuration.sources.spatial_sources.targets.lora.manifest
    assert selected.strength == 1.0
    assert (
        prepared.metadata.sources.crop_sources[0].review.created_at
        < configuration.command.created_at
    )
    assert len(configuration.native_training_sources.regions) == 12
    assert events == ["FULL_LINEAGE", "SELECTED_BINARIES"]
    assert parse_sdxl_validation_command(command.model_dump(mode="json")) == command
    assert admission.sdxl_validation_input_hashes(prepared) == {
        file.member_path: file.sha256 for file in prepared.files
    }
    assert not any(file.member_path.startswith("inputs/targets/") for file in prepared.files)
    reads = [pointer for pointer in reader.calls if pointer.member_path.startswith("adapter/")]
    assert len(reads) == 2
    assert {p.artifact_revision_id for p in reads} == {
        selected.training_result.artifact_revision_id
    }


def _stage(tmp_path, monkeypatch):
    monkeypatch.setattr(lifecycle, "_fixture", _native_fixture)
    return lifecycle._stage(tmp_path, monkeypatch)


@pytest.mark.parametrize("fault", [None, "second", "oom", "unexpected"])
def test_native_pair_and_terminal_no_side_effect_replay(tmp_path, monkeypatch, fault):
    prepared, root, leases = _stage(tmp_path, monkeypatch)
    loaded = []
    original_loader = worker.load_sdxl_lora_material

    def load(root, manifest, *, strength):
        loaded.append((manifest, strength))
        return original_loader(root, manifest, strength=strength)

    monkeypatch.setattr(worker, "load_sdxl_lora_material", load)
    result = lifecycle._run(prepared, root, _Backend(fault))
    assert result.status == ("SUCCEEDED" if fault is None else "FAILED")
    native = prepared.metadata.sources.configuration.sources
    assert loaded == [(native.native.manifest, native.evaluation.evaluation.adapter_strength)]
    assert result.native_evaluation_command_sha256 == native.evaluation.command_sha256
    assert result.native_adapter_manifest_sha256 == native.native.manifest.manifest_sha256
    assert parse_sdxl_validation_result(result.model_dump(mode="json")) == result
    assert worker.load_sdxl_comparison_command(root, root / "command.json") == prepared.command
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()}

    def forbidden(*args, **kwargs):
        pytest.fail("terminal replay repeated a transform, model, GPU or write")

    for name in (
        "resolve_sdxl_stack",
        "resolve_sdxl_canny_controller",
        "read_canny_runtime",
        "load_sdxl_lora_material",
        "sdxl_canny_native_source_canvas",
        "canny_conditioning_canvas_png",
        "run_sdxl_pair_inference",
        "write_staged_member",
        "create_sdxl_pair_directories",
    ):
        monkeypatch.setattr(worker, name, forbidden)
    assert lifecycle._run(prepared, root, _Backend()) == result
    assert before == {
        p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()
    }
    assert leases == ["ENTER", "EXIT"]


@pytest.mark.parametrize("collision", ["document_id", "source_document", "exam_group_sha256"])
def test_native_only_training_leakage_is_rejected(tmp_path, monkeypatch, collision):
    command, _, _ = _native_fixture(tmp_path, monkeypatch)
    admitted = admission.resolve_sdxl_validation_metadata(object(), command)
    configuration = admitted.sources.configuration
    reserved = admitted.sources.crop_sources[0].review.selections[0]
    assert all(
        getattr(row, collision) != getattr(reserved, collision)
        for row in configuration.training_review.selections
    )
    native = configuration.native_training_sources
    changed = native.regions[0].model_copy(update={collision: getattr(reserved, collision)})
    sources = replace(
        admitted.sources,
        configuration=replace(
            configuration,
            native_training_sources=replace(native, regions=(changed, *native.regions[1:])),
        ),
    )
    with pytest.raises(ValueError, match="partition/leakage"):
        validate_sdxl_validation_sources(command, sources)


@pytest.mark.parametrize("fault", ["missing", "hash", "foreign"])
def test_native_metadata_closure_failure_precedes_binary(tmp_path, monkeypatch, fault):
    command, reader, events = _native_fixture(tmp_path, monkeypatch)
    reference = admission.parse_reference_command(
        json.loads(reader.records[command.configuration_anchor])
    )
    inherited = admission.resolve_sdxl_canny_reference_metadata(object(), reference)
    files = list(inherited.native_admission.metadata)
    first = files.pop(0)
    if fault == "hash":
        files.append(replace(first, payload=b"{}"))
    elif fault == "foreign":
        files.append(replace(first, member_path="inputs/metadata/" + "f" * 64 + ".json"))
    inherited = replace(
        inherited, native_admission=replace(inherited.native_admission, metadata=tuple(files))
    )
    monkeypatch.setattr(admission, "resolve_sdxl_canny_reference_metadata", lambda *a: inherited)
    with pytest.raises(ValueError):
        admission.prepare_sdxl_validation_inputs(object(), command)
    assert not events
    assert not any(p.media_type != "application/json" for p in reader.calls)


@pytest.mark.parametrize("fault", ["native-metadata", "native-training", "native-manifest"])
def test_staged_native_tamper_precedes_gpu(tmp_path, monkeypatch, fault):
    prepared, root, leases = _stage(tmp_path, monkeypatch)
    if fault == "native-metadata":
        target = next((root / "inputs/metadata").iterdir())
    else:
        target = root / (
            "inputs/native-training-command.json"
            if fault == "native-training"
            else "inputs/native-adapter-manifest.json"
        )
    target.write_bytes(b"{}")
    backend = _Backend()
    with pytest.raises(ProviderError):
        lifecycle._run(prepared, root, backend)
    assert not leases and not backend.calls and not (root / "outputs").exists()


@pytest.mark.parametrize(
    "field", ["native_evaluation_command_sha256", "native_adapter_manifest_sha256"]
)
def test_rehashed_native_lineage_mismatch_fails(tmp_path, monkeypatch, field):
    prepared, root, _ = _stage(tmp_path, monkeypatch)
    result = lifecycle._run(prepared, root, _Backend())
    value = result.model_dump(mode="json")
    value[field] = "sha256:" + "f" * 64
    value["result_sha256"] = content_sha256(
        {k: v for k, v in value.items() if k != "result_sha256"}
    )
    with pytest.raises(ValueError, match="NATIVE_RESULT_LINEAGE_MISMATCH"):
        validate_sdxl_validation_result(
            prepared.command, prepared.metadata.sources, parse_sdxl_validation_result(value)
        )


def test_publisher_and_release_resources_select_successor(tmp_path, monkeypatch):
    command, _, _ = _native_fixture(tmp_path, monkeypatch)
    publisher = LocalImageTrainingControlArtifactPublisher(
        _Publisher(), source_commit=command.source_commit
    )
    pin = publisher.commit_sdxl_validation_comparison_command(command)
    assert pin.schema_ref.endswith("sdxl-validation-comparison-command/1.1")
    assert pin == publisher.commit_sdxl_validation_comparison_command(command)
    repo = Path(__file__).resolve().parents[2]
    for component in ("image_provider", "image_trainer"):
        script = (repo / "scripts" / component / "build_release.sh").read_text()
        for family in ("command", "result"):
            assert "local-image-sdxl-validation-comparison-" + family + "-v2.schema.json" in script


def test_reference_owner_retains_canonical_native_admission_once(tmp_path, monkeypatch):
    command, reader, _ = _native_fixture(tmp_path, monkeypatch)
    reference = admission.parse_reference_command(
        json.loads(reader.records[command.configuration_anchor])
    )
    inherited = admission.resolve_sdxl_canny_reference_metadata(object(), reference)
    seen = []

    def resolve(engine, training):
        seen.append(training)
        return inherited.native_admission

    monkeypatch.setattr(reference_admission, "resolve_sdxl_native_lora_sources", resolve)
    actual = reference_admission.resolve_sdxl_canny_reference_metadata(object(), reference)
    assert actual.native_admission is inherited.native_admission
    assert seen == [inherited.sources.native.training_command]
    assert not any(p.media_type != "application/json" for p in reader.calls)


def test_native_publication_preserves_family_and_no_source_duplication(tmp_path, monkeypatch):
    prepared, root, _ = _stage(tmp_path, monkeypatch)
    result = lifecycle._run(prepared, root, _Backend())
    raw = content_json_bytes(prepared.command.model_dump(mode="json"))
    pointer = prepared.command.configuration_anchor.model_copy(
        update={
            "member_path": "manifests/sdxl-validation-comparison-command.json",
            "schema_ref": "eom://schemas/image-provider/" + prepared.command.schema_version,
            "sha256": _sha(raw),
        }
    )
    publication = lifecycle.publication
    monkeypatch.setattr(publication, "resolve_control_artifact_member", lambda *a, **k: raw)
    monkeypatch.setattr(publication, "prepare_sdxl_validation_inputs", lambda *a: prepared)
    checks = []

    def verify(workspace, expected):
        actual = worker.verify_sdxl_validation_transforms(workspace)
        assert content_json_bytes(actual.model_dump(mode="json")) == expected
        checks.append("TRANSFORMS")

    class Publisher:
        def __init__(self, engine):
            pass

        def publish(self, **kwargs):
            assert checks == ["TRANSFORMS"]
            return kwargs

    monkeypatch.setattr(publication, "verify_reserved_transforms_cpu", verify)
    monkeypatch.setattr(publication, "ControlFileSetPublisher", Publisher)
    published = publication.publish_sdxl_validation_comparison(
        object(),
        prepared.command,
        command_pointer=pointer,
        workspace=root,
        worker_uid=lifecycle.os.geteuid(),
        source_commit="a" * 40,
        created_at=result.completed_at + timedelta(seconds=1),
    )
    assert published["manifest_version"] == "sdxl-validation-comparison-result-artifact/1.1"
    members = published["members"]
    assert len(members) == 73
    assert not any(member.file_name.startswith(("inputs/", "adapter/")) for member in members)
    primary = next(member for member in members if member.file_name == published["primary_file"])
    assert primary.schema_ref.endswith("sdxl-validation-comparison-result/1.1")


@pytest.mark.parametrize("fault", ["missing", "stale", "permission", "hash"])
def test_canonical_native_configuration_failure_never_reads_binary(tmp_path, monkeypatch, fault):
    command, reader, events = _native_fixture(tmp_path, monkeypatch)
    original = admission.resolve_control_artifact_member

    def fail(engine, pointer, **kwargs):
        if pointer == command.configuration_anchor:
            if fault == "hash":
                return b"{}"
            raise ValueError("CANONICAL_POINTER_" + fault.upper())
        return original(engine, pointer, **kwargs)

    monkeypatch.setattr(admission, "resolve_control_artifact_member", fail)
    with pytest.raises((ValueError, lifecycle.worker.SchemaError)):
        admission.prepare_sdxl_validation_inputs(object(), command)
    assert not events
    assert not any(pointer.media_type != "application/json" for pointer in reader.calls)


def test_rehashed_legacy_result_cannot_cross_native_family(tmp_path, monkeypatch):
    prepared, root, _ = _stage(tmp_path, monkeypatch)
    result = lifecycle._run(prepared, root, _Backend())
    value = result.model_dump(mode="json")
    value["schema_version"] = "local-image-sdxl-validation-comparison-result/1.0"
    value.pop("native_evaluation_command_sha256")
    value.pop("native_adapter_manifest_sha256")
    value["result_sha256"] = content_sha256(
        {k: v for k, v in value.items() if k != "result_sha256"}
    )
    with pytest.raises(ValueError, match="RESULT_FAMILY_INVALID"):
        validate_sdxl_validation_result(
            prepared.command, prepared.metadata.sources, parse_sdxl_validation_result(value)
        )
