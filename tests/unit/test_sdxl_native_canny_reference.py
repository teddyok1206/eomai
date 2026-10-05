"""Native adapter substitution preserves frozen references and metadata-first admission."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_image_contracts.models import (
    ImageEvaluationArtifactMember,
    content_json_bytes,
    content_sha256,
)
from eom_image_contracts.sdxl_canny_comparison import LocalImageSdxlCannyComparisonCommand
from eom_image_contracts.sdxl_native_canny_reference import (
    LocalImageSdxlNativeCannyReferenceCommand,
    SdxlNativeCannyReferenceSources,
    parse_reference_command,
    parse_reference_result,
    validate_reference_result,
)
from eom_image_contracts.sdxl_native_evaluation import LocalImageSdxlNativeEvaluationCommand
from eom_image_contracts.validation import SCHEMA_FILES, SCHEMA_SHA256, validate_contract
from eom_image_provider import sdxl_canny_reference as worker
from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_comparison_command import load_sdxl_comparison_command
from eom_orchestrator import sdxl_canny_reference_inputs as admission
from eom_orchestrator import sdxl_probe_workspace as handoff
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from jsonschema import ValidationError as SchemaError

from tests.unit.test_local_image_training_control_artifacts import _Publisher
from tests.unit.test_sdxl_canny_reference import _fixture as _reference_fixture
from tests.unit.test_sdxl_canny_reference import _run, _seal, _sha
from tests.unit.test_sdxl_learned_comparison import _Backend as FakeBackend
from tests.unit.test_sdxl_lora_evaluation_contracts import _seal as _seal_evaluation
from tests.unit.test_sdxl_micro_runner import _write
from tests.unit.test_sdxl_native_evaluation import _fixture as _native_fixture
from tests.unit.test_sdxl_probe_workspace import _operator


def _fixture(tmp_path, monkeypatch, *, lineage_fault=None):
    old, reader, trace, leases = _reference_fixture(tmp_path, monkeypatch)
    native, records = _native_fixture()
    native_value = native.model_dump(mode="json")
    for field in ("training_result", "adapter_manifest"):
        original = ImageEvaluationArtifactMember.model_validate(native_value["evaluation"][field])
        revised = original.model_copy(
            update={
                "artifact_id": "artifact_" + "e" * 32,
                "artifact_revision_id": "rev_" + "e" * 32,
            }
        )
        records[revised] = records[original]
        native_value["evaluation"][field] = revised.model_dump(mode="json")
    for pointer, payload in tuple(records.items()):
        if pointer.member_path.startswith("adapter/"):
            records[
                pointer.model_copy(
                    update={
                        "artifact_id": "artifact_" + "e" * 32,
                        "artifact_revision_id": "rev_" + "e" * 32,
                    }
                )
            ] = payload
    native = LocalImageSdxlNativeEvaluationCommand.model_validate(_seal_evaluation(native_value))
    reader.records.update(records)
    raw = content_json_bytes(native.model_dump(mode="json"))
    pin = ImageEvaluationArtifactMember(
        artifact_id="artifact_" + "9" * 32,
        artifact_revision_id="rev_" + "9" * 32,
        member_path="manifests/sdxl-lora-evaluation-command.json",
        schema_ref="eom://schemas/image-provider/local-image-sdxl-lora-evaluation-command/1.2",
        media_type="application/json",
        sha256=_sha(raw),
    )
    reader.records[pin] = raw
    value = old.model_dump(mode="json")
    value.update(
        schema_version="local-image-sdxl-canny-reference-command/1.1",
        native_evaluation_command=pin.model_dump(mode="json"),
        case_relation="REVIEWED_TRAIN_REFERENCE_NOT_HOLDOUT",
    )
    command = LocalImageSdxlNativeCannyReferenceCommand.model_validate(_seal(value))
    inherited = admission.resolve_sdxl_canny_comparison_metadata(
        object(),
        LocalImageSdxlCannyComparisonCommand.model_validate_json(
            reader.records[old.spatial_command]
        ),
    )
    trace.clear()
    source_review = json.loads(
        next(f.payload for f in inherited.files if f.member_path == "inputs/source-review.json")
    )
    basis = ImageEvaluationArtifactMember.model_validate(source_review["basis_crop_set"])

    def lineage(engine, training):
        assert "PIXELS" not in trace
        trace.append("NATIVE_LINEAGE")
        if lineage_fault == "missing":
            raise ValueError("native source missing")
        actual = (
            basis.model_copy(update={"sha256": "sha256:" + "0" * 64})
            if lineage_fault == "basis"
            else basis
        )
        return SimpleNamespace(
            sources=SimpleNamespace(
                batches=(
                    SimpleNamespace(
                        sources=SimpleNamespace(review=SimpleNamespace(basis_crop_set=actual))
                    ),
                )
            )
        )

    monkeypatch.setattr(admission, "resolve_sdxl_native_lora_sources", lineage)
    reader.calls.clear()
    return command, reader, trace, leases


def _stage(tmp_path, monkeypatch):
    command, reader, trace, leases = _fixture(tmp_path, monkeypatch)
    prepared = admission.prepare_sdxl_canny_reference_inputs(object(), command)
    assert trace == ["LINEAGE", "NATIVE_LINEAGE", "PIXELS", "PIXELS"]
    root = tmp_path / "native-reference"
    root.mkdir(mode=0o700)
    for file in prepared.files:
        _write(root / file.member_path, file.payload)
    monkeypatch.setattr(worker, "resolve_sdxl_stack", lambda *a, **k: object())
    monkeypatch.setattr(worker, "resolve_sdxl_canny_controller", lambda *a, **k: object())
    monkeypatch.setattr(worker.metadata, "version", lambda name: "11.3.0")
    return prepared, root, reader, leases


@pytest.mark.parametrize("fault", [None, "second", "oom", "unexpected"])
def test_native_pair_and_terminal_replay_keep_exact_adapter_and_inputs(
    tmp_path, monkeypatch, fault
):
    prepared, root, reader, leases = _stage(tmp_path, monkeypatch)
    assert isinstance(prepared.sources, SdxlNativeCannyReferenceSources)
    loaded = []
    original_loader = worker.load_sdxl_lora_material

    def load_material(root, manifest, *, strength):
        loaded.append((manifest, strength))
        return original_loader(root, manifest, strength=strength)

    monkeypatch.setattr(worker, "load_sdxl_lora_material", load_material)
    result = _run(prepared, root, FakeBackend(fault))
    assert result.status == ("SUCCEEDED" if fault is None else "FAILED")
    validate_reference_result(prepared.command, prepared.sources, result)
    assert result.native_adapter_manifest_sha256 == prepared.sources.native.manifest.manifest_sha256
    assert loaded == [
        (prepared.sources.native.manifest, prepared.sources.evaluation.evaluation.adapter_strength)
    ]
    assert load_sdxl_comparison_command(root, root / "command.json") == prepared.command
    assert admission.sdxl_canny_reference_input_hashes(prepared) == {
        f.member_path: f.sha256 for f in prepared.files
    }
    adapter_reads = [p for p in reader.calls if p.member_path.startswith("adapter/")]
    assert len(adapter_reads) == 2
    assert all(
        p.artifact_revision_id
        == prepared.sources.evaluation.evaluation.training_result.artifact_revision_id
        for p in adapter_reads
    )
    assert not any(
        f.member_path.startswith(("inputs/targets/", "inputs/metadata/")) for f in prepared.files
    )
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()}
    for name in (
        "resolve_sdxl_stack",
        "resolve_sdxl_canny_controller",
        "load_sdxl_lora_material",
        "sdxl_canny_source_canvas",
        "create_sdxl_pair_directories",
        "write_staged_member",
    ):
        monkeypatch.setattr(worker, name, lambda *a, **k: pytest.fail("replay side effect"))
    assert _run(prepared, root, FakeBackend()) == result
    assert leases == ["ENTER", "EXIT"]
    assert before == {
        p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize("fault", ["missing", "basis"])
def test_full_native_lineage_failure_precedes_all_media(tmp_path, monkeypatch, fault):
    command, _, trace, _ = _fixture(tmp_path, monkeypatch, lineage_fault=fault)
    with pytest.raises(ValueError):
        admission.prepare_sdxl_canny_reference_inputs(object(), command)
    assert "PIXELS" not in trace


@pytest.mark.parametrize(
    "fault", ["missing", "hash", "noncanonical", "stale", "old_family", "holdout"]
)
def test_native_pin_errors_never_fall_back_to_old_weights(tmp_path, monkeypatch, fault):
    command, reader, trace, _ = _fixture(tmp_path, monkeypatch)
    value = command.model_dump(mode="json")
    pin = command.native_evaluation_command
    if fault == "missing":
        del reader.records[pin]
    elif fault == "hash":
        reader.records[pin] += b" "
    elif fault == "noncanonical":
        raw = json.dumps(json.loads(reader.records[pin]), indent=2).encode()
        new_pin = pin.model_copy(update={"sha256": _sha(raw)})
        reader.records[new_pin] = raw
        value["native_evaluation_command"] = new_pin.model_dump(mode="json")
    elif fault == "stale":
        value["native_evaluation_command"]["artifact_revision_id"] = "rev_" + "0" * 32
    elif fault == "old_family":
        value["native_evaluation_command"]["schema_ref"] = pin.schema_ref.replace("/1.2", "/1.1")
    else:
        value["case_relation"] = "HOLDOUT_PASS"
    with pytest.raises((ValueError, KeyError, RuntimeError, SchemaError)):
        command = parse_reference_command(_seal(value))
        admission.prepare_sdxl_canny_reference_inputs(object(), command)
    assert "PIXELS" not in trace


def test_native_handoff_publication_and_schema_bytes(tmp_path, monkeypatch):
    prepared, _, _, _ = _stage(tmp_path, monkeypatch)
    parent, owner, _ = _operator(monkeypatch, tmp_path)
    staged = handoff.stage_sdxl_canny_reference_inputs(
        prepared, workspace_parent=parent, worker=owner
    )
    assert staged.systemd_unit.startswith("eom-image-sdxl-learned-comparison@")
    with pytest.raises(handoff.SdxlProbeHandoffError, match="WORKSPACE_EXISTS"):
        handoff.stage_sdxl_canny_reference_inputs(prepared, workspace_parent=parent, worker=owner)
    pub = LocalImageTrainingControlArtifactPublisher(
        _Publisher(), source_commit=prepared.command.source_commit
    )
    assert pub.commit_sdxl_canny_reference_command(prepared.command).schema_ref.endswith("/1.1")
    with pytest.raises(SchemaError):
        validate_contract("sdxl-canny-reference-command", prepared.command.model_dump(mode="json"))
    repo = Path(__file__).resolve().parents[2]
    for name in ("sdxl-canny-reference-command-v2", "sdxl-canny-reference-result-v2"):
        raw = (repo / "schemas/image-provider" / SCHEMA_FILES[name]).read_bytes()
        assert (
            raw
            == (
                repo / "packages/image_contracts/eom_image_contracts/schemas" / SCHEMA_FILES[name]
            ).read_bytes()
        )
        assert "sha256:" + hashlib.sha256(raw).hexdigest() == SCHEMA_SHA256[name]
    assert SCHEMA_SHA256["sdxl-canny-reference-command"] == (
        "sha256:7f9e33c0e91e614b781227bae3b086e5cf9f64e4987c1b8415f9d0dc4ce8cda4"
    )
    assert SCHEMA_SHA256["sdxl-canny-reference-result"] == (
        "sha256:7f66e5633422784dbd1f0d717713b3d12134405c263b2fcc5852ccec6cd82e5e"
    )


@pytest.mark.parametrize(
    "field", ["native_evaluation_command_sha256", "native_adapter_manifest_sha256"]
)
def test_result_cannot_claim_a_different_native_adapter(tmp_path, monkeypatch, field):
    prepared, root, _, _ = _stage(tmp_path, monkeypatch)
    value = _run(prepared, root, FakeBackend()).model_dump(mode="json")
    value[field] = "sha256:" + "0" * 64
    value["result_sha256"] = content_sha256(
        {k: v for k, v in value.items() if k != "result_sha256"}
    )
    with pytest.raises(ValueError, match="adapter identity"):
        validate_reference_result(prepared.command, prepared.sources, parse_reference_result(value))


def test_native_metadata_tamper_after_staging_stops_before_model(tmp_path, monkeypatch):
    prepared, root, _, _ = _stage(tmp_path, monkeypatch)
    (root / "inputs/native-adapter-manifest.json").write_bytes(b"{}")
    monkeypatch.setattr(
        worker, "resolve_sdxl_stack", lambda *a, **k: pytest.fail("tamper reached model")
    )
    with pytest.raises(ProviderError):
        _run(prepared, root, FakeBackend())


@pytest.mark.parametrize("value", [None, [], {"schema_version": []}, {"schema_version": "unknown"}])
def test_unknown_family_has_no_latest_fallback(value):
    for parser in (parse_reference_command, parse_reference_result):
        with pytest.raises(ValueError, match="FAMILY_INVALID"):
            parser(value)


def test_native_result_cannot_be_relabelled_as_legacy(tmp_path, monkeypatch):
    prepared, root, _, _ = _stage(tmp_path, monkeypatch)
    value = _run(prepared, root, FakeBackend()).model_dump(mode="json")
    for field in (
        "native_evaluation_command_sha256",
        "native_adapter_manifest_sha256",
        "case_relation",
    ):
        del value[field]
    value["schema_version"] = "local-image-sdxl-canny-reference-result/1.0"
    value["result_sha256"] = content_sha256(
        {k: v for k, v in value.items() if k != "result_sha256"}
    )
    with pytest.raises(ValueError, match="adapter identity"):
        validate_reference_result(prepared.command, prepared.sources, parse_reference_result(value))
