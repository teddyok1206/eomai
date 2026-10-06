"""CPU mock lifecycle/admission tests; no GPU, real model or visual-quality claim."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from eom_image_contracts.models import (
    ImageEvaluationArtifactMember,
    content_json_bytes,
    content_sha256,
)
from eom_image_contracts.sdxl_canny_conditioning import SdxlCannyPolicy
from eom_image_contracts.sdxl_native_lora_sources import (
    parse_sdxl_native_lora_sources,
    sdxl_native_lora_metadata_member_path,
)
from eom_image_contracts.sdxl_photo_style import parse_photo_style_plan_value
from eom_image_contracts.sdxl_photo_style_execution import (
    LocalImageSdxlPhotoObjectSupportCommand,
    LocalImageSdxlPhotoObjectSupportResult,
    parse_photo_style_command,
    parse_photo_style_plan,
    parse_photo_style_result,
    validate_photo_style_execution_sources,
    validate_photo_style_result,
)
from eom_image_contracts.source_page_crops import (
    LocalImageScienceSourcePageCropReview,
    source_page_crop_selection_id,
)
from eom_image_contracts.validation import SCHEMA_FILES, SCHEMA_SHA256
from eom_image_provider import sdxl_photo_style as worker
from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_comparison_command import load_sdxl_comparison_command
from eom_image_provider.sdxl_photo_conditioning import photo_style_conditioner
from eom_orchestrator import sdxl_canny_reference_inputs as reference_admission
from eom_orchestrator import sdxl_photo_style_inputs as admission
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from eom_orchestrator.sdxl_native_lora_inputs import AdmittedSdxlNativeLoraSources
from eom_orchestrator.sdxl_probe_inputs import SdxlProbeInputMember
from PIL import Image, ImageChops, ImageDraw

from tests.unit import test_photo_object_support_review as review_tests
from tests.unit import test_sdxl_photo_object_support_plan as preparation
from tests.unit import test_sdxl_photo_style_execution as legacy
from tests.unit import test_sdxl_photo_style_retained_region as retained
from tests.unit.test_local_image_training_control_artifacts import _Publisher
from tests.unit.test_science_source_page_crops import _fixture_review, _seal_review
from tests.unit.test_sdxl_learned_comparison import _Backend
from tests.unit.test_sdxl_native_lora_sources import _fixture as native_fixture
from tests.unit.test_sdxl_native_lora_sources import _staged_metadata
from tests.unit.test_style_exposure_consumers import _balanced_reference


def _sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _png(image):
    output = io.BytesIO()
    image.save(output, format="PNG", compress_level=9)
    return output.getvalue()


def _fixture(tmp_path, monkeypatch):
    old, reader, events, _ = retained._fixture(tmp_path, monkeypatch)
    prior = parse_photo_style_plan(old, reader.records[old.plan])
    ref_root = tmp_path / "reference-fixture"
    ref_root.mkdir(mode=0o700)
    # Synthetic canonical-store adapter: a complete 100-target metadata closure,
    # not a claim of real frozen-corpus/source-permission or image-quality acceptance.
    review_template, basis, corpus_reader = _fixture_review(monkeypatch, count=1)
    review_value = review_template.model_dump(mode="json")
    selections = []
    for index in range(100):
        region = copy.deepcopy(review_value["selections"][0])
        identity = f"{index + 1000:032x}"
        region.update(
            document_id="sciencedoc_" + identity,
            candidate_id="imgsciviscandidate_" + identity,
            exam_group_sha256=_sha(f"synthetic group {index}".encode()),
        )
        region["source_document"].update(
            artifact_id="artifact_" + identity,
            artifact_revision_id="rev_" + identity,
            sha256=_sha(f"synthetic pdf {index}".encode()),
        )
        region["source_page"].update(
            member_path=f"pages/{region['document_id']}/page-{region['physical_page']}.png",
            sha256=_sha(f"synthetic page {index}".encode()),
        )
        region["selection_id"] = source_page_crop_selection_id(region)
        selections.append(region)
    review_value["selections"] = selections
    synthetic_review = LocalImageScienceSourcePageCropReview.model_validate(
        _seal_review(review_value)
    )
    training_fixture = native_fixture(
        monkeypatch, exterior_batch=True, review_fixture=(synthetic_review, basis, corpus_reader)
    )
    reference, reference_reader, geometry_sources, *_ = _balanced_reference(
        ref_root, monkeypatch, training_fixture
    )
    reference_reader.records.update(reader.records)
    reader.records.update(reference_reader.records)
    native_metadata = _staged_metadata(training_fixture[1])
    native_sources = parse_sdxl_native_lora_sources(
        geometry_sources.training_command, native_metadata
    )
    admitted_native = AdmittedSdxlNativeLoraSources(
        geometry_sources.training_command,
        native_sources,
        tuple(
            SdxlProbeInputMember(
                sdxl_native_lora_metadata_member_path(p), p.sha256, reader.records[p]
            )
            for p in native_sources.metadata_pointers
        ),
    )

    def native_admission(engine, training):
        assert training == geometry_sources.training_command
        return admitted_native

    monkeypatch.setattr(reference_admission, "resolve_sdxl_native_lora_sources", native_admission)
    monkeypatch.setattr(
        admission,
        "resolve_sdxl_canny_reference_metadata",
        reference_admission.resolve_sdxl_canny_reference_metadata,
    )
    raw = content_json_bytes(reference.model_dump(mode="json"))
    anchor = prior.configuration_anchor.model_copy(
        update={
            "schema_ref": "eom://schemas/image-provider/" + reference.schema_version,
            "artifact_revision_id": "rev_" + "d" * 32,
            "sha256": _sha(raw),
        }
    )
    reader.records[anchor] = raw
    reference_reader.records[anchor] = raw
    body = prior.model_dump(mode="json")
    body.update(
        schema_version="local-image-sdxl-photo-style-plan/1.5",
        configuration_anchor=anchor.model_dump(mode="json"),
        created_at=max(prior.created_at, reference.created_at).isoformat().replace("+00:00", "Z"),
    )
    prior = parse_photo_style_plan_value(preparation.photos._seal_plan(body))
    case = prior.cases[0].case
    control = photo_style_conditioner(prior, canny=retained._canny)(
        case, Image.new("RGB", (832, 512), "white"), policy=SdxlCannyPolicy()
    )
    mask_image = Image.new("L", (832, 512), 0)
    ImageDraw.Draw(mask_image).rectangle((0, 0, 399, 511), fill=255)
    with Image.open(io.BytesIO(control)) as control_image:
        prior_image = control_image.copy()
    candidate_image = ImageChops.multiply(prior_image, mask_image.convert("RGB"))
    mask, candidate = _png(mask_image), _png(candidate_image)
    prior_raw = content_json_bytes(prior.model_dump(mode="json"))
    prior_pin = preparation._pin("7", "sdxl-photo-style-plan", prior_raw)
    result = preparation._result(prior).model_dump(mode="json", exclude={"result_sha256"})
    result.update(
        configuration_command_sha256=reference.command_sha256,
        native_evaluation_command_sha256=json.loads(
            reader.records[reference.native_evaluation_command]
        )["command_sha256"],
        native_adapter_manifest_sha256=geometry_sources.manifest.manifest_sha256,
    )
    result["started_at"] = (
        (prior.created_at + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    )
    result["completed_at"] = (
        (prior.created_at + timedelta(seconds=2)).isoformat().replace("+00:00", "Z")
    )
    result["inputs"][0]["conditioning_sha256"] = _sha(control)
    for output in result["outputs"]:
        output["conditioning_sha256"] = _sha(control)
    result_raw = content_json_bytes({**result, "result_sha256": content_sha256(result)})
    result_pin = preparation._pin("8", "sdxl-photo-style-result", result_raw)
    review = review_tests._value()
    review["reviewed_at"] = (
        (prior.created_at + timedelta(seconds=3)).isoformat().replace("+00:00", "Z")
    )
    review["created_at"] = (
        (prior.created_at + timedelta(seconds=4)).isoformat().replace("+00:00", "Z")
    )
    review["source"] = case.reference_image.model_dump(mode="json")
    review["prior_control"].update(
        artifact_id=result_pin.artifact_id,
        artifact_revision_id=result_pin.artifact_revision_id,
        member_path="conditionings/" + case.case_id + ".png",
        sha256=_sha(control),
    )
    review["support_mask"]["sha256"] = _sha(mask)
    review["candidate_control"]["sha256"] = _sha(candidate)
    original_edges = prior_image.getchannel("R").histogram()[255]
    retained_edges = candidate_image.getchannel("R").histogram()[255]
    review["pixel_observation"].update(
        support_area_pixels=mask_image.histogram()[255],
        original_edges=original_edges,
        retained_edges=retained_edges,
        deleted_edges=original_edges - retained_edges,
    )
    review_raw = content_json_bytes(review_tests._seal(review))
    review_pin = review_tests._pointer(review_raw)
    body = prior.model_dump(mode="json", exclude={"region_reviews", "region_review_evidence"})
    body.update(
        schema_version="local-image-sdxl-photo-style-plan/1.6",
        created_at=(prior.created_at + timedelta(seconds=5)).isoformat().replace("+00:00", "Z"),
        support_parents=dict(
            review=review_pin.model_dump(mode="json"),
            prior_plan=prior_pin.model_dump(mode="json"),
            prior_result=result_pin.model_dump(mode="json"),
            baseline_plan=prior_pin.model_dump(mode="json"),
            baseline_result=result_pin.model_dump(mode="json"),
        ),
        comparison_policy="CHANGE_OBJECT_SUPPORT_ONLY_REUSE_PINNED_BASELINE",
    )
    body["budget"]["maximum_outputs"] = 2
    plan = parse_photo_style_plan_value(preparation.photos._seal_plan(body))
    plan_raw = content_json_bytes(plan.model_dump(mode="json"))
    plan_pin = preparation._pin("9", "sdxl-photo-style-plan", plan_raw, "1.6")
    command_value = old.model_dump(mode="json")
    command_value.update(
        schema_version="local-image-sdxl-photo-style-command/1.6",
        created_at=(plan.created_at + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        plan=plan_pin.model_dump(mode="json"),
        plan_id=plan.plan_id,
        plan_sha256=plan.plan_sha256,
    )
    command = parse_photo_style_command(legacy._seal(command_value))
    reader.records.update(
        {
            plan_pin: plan_raw,
            prior_pin: prior_raw,
            result_pin: result_raw,
            review_pin: review_raw,
            ImageEvaluationArtifactMember.model_validate(review["prior_control"]): control,
            ImageEvaluationArtifactMember.model_validate(review["support_mask"]): mask,
            ImageEvaluationArtifactMember.model_validate(review["candidate_control"]): candidate,
        }
    )
    reference_reader.records.update(reader.records)
    return command, reader, events


def _stage(tmp_path, monkeypatch):
    command, reader, events = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(legacy, "_fixture", lambda *args: (command, reader, events))
    prepared, root, leases = legacy._stage(tmp_path, monkeypatch)
    monkeypatch.setattr(worker, "canny_conditioning_canvas_png", retained._canny)
    return prepared, root, leases


@pytest.mark.parametrize("fault", [None, "second", "oom", "unexpected"])
def test_source_owner_staging_worker_pair_and_terminal_replay(tmp_path, monkeypatch, fault):
    prepared, root, leases = _stage(tmp_path, monkeypatch)
    assert isinstance(prepared.command, LocalImageSdxlPhotoObjectSupportCommand)
    assert load_sdxl_comparison_command(root, root / "command.json") == prepared.command
    hashes = admission.sdxl_photo_style_input_hashes(prepared)
    assert len({f.member_path for f in prepared.files}) == len(prepared.files)
    assert {f.member_path: f.sha256 for f in prepared.files} == hashes
    backend = _Backend(fault)
    result = legacy._run(prepared, root, backend)
    assert isinstance(result, LocalImageSdxlPhotoObjectSupportResult)
    assert result.status == ("SUCCEEDED" if fault is None else "FAILED")
    assert len(result.outputs) == (2 if fault is None else 1 if fault == "second" else 0)
    assert leases == ["ENTER", "EXIT"]
    assert result.object_support.pixel_observation.added_edges == 0
    assert result.inputs[0].conditioning_sha256 == result.object_support.candidate_control_sha256
    validate_photo_style_result(prepared.command, prepared.metadata.sources, result)
    monkeypatch.setattr(
        worker,
        "canny_conditioning_canvas_png",
        lambda *a, **k: pytest.fail("terminal replay transformed"),
    )
    monkeypatch.setattr(
        worker, "resolve_sdxl_stack", lambda *a, **k: pytest.fail("terminal replay loaded model")
    )
    before = backend.calls
    files_before = {
        p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()
    }
    assert legacy._run(prepared, root, backend) == result
    assert backend.calls == before and leases == ["ENTER", "EXIT"]
    assert files_before == {
        p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()
    }


def test_transform_reproduction_and_registered_output_validation(tmp_path, monkeypatch):
    prepared, root, _ = _stage(tmp_path, monkeypatch)
    result = legacy._run(prepared, root, _Backend())
    assert worker.verify_sdxl_photo_style_transforms(root) == result
    assert (
        worker.validate_sdxl_photo_style_workspace_result(
            command=prepared.command,
            sources=prepared.metadata.sources,
            workspace=root,
            expected_owner_uid=os.geteuid(),
        )
        == result
    )
    # The source was already staged at its original path, not copied into support.
    assert not (root / "inputs/object-support/source.png").exists()


@pytest.mark.parametrize(
    "field",
    [
        "prior-control.png",
        "mask.png",
        "candidate-control.png",
        "review.json",
        "prior-plan.json",
        "baseline-result.json",
    ],
)
def test_tampered_staged_input_never_loads_model_or_claims_gpu(tmp_path, monkeypatch, field):
    prepared, root, leases = _stage(tmp_path, monkeypatch)
    path = root / "inputs/object-support" / field
    path.write_bytes(path.read_bytes() + b" ")
    monkeypatch.setattr(
        worker, "resolve_sdxl_stack", lambda *a, **k: pytest.fail("invalid input loaded model")
    )
    code = "SDXL_PROBE_HASH_MISMATCH" if field.endswith(".json") else "SDXL_PROBE_INPUT_INVALID"
    with pytest.raises(ProviderError, match=code):
        legacy._run(prepared, root, _Backend())
    assert leases == [] and not (root / "outputs").exists()


def test_wrong_reproduced_control_refused_before_model(tmp_path, monkeypatch):
    prepared, root, leases = _stage(tmp_path, monkeypatch)
    different = Image.new("RGB", (832, 512), "black")
    ImageDraw.Draw(different).rectangle((300, 200, 400, 300), outline="white", width=2)
    monkeypatch.setattr(
        worker,
        "canny_conditioning_canvas_png",
        lambda *a, **k: _png(different),
    )
    monkeypatch.setattr(
        worker, "resolve_sdxl_stack", lambda *a, **k: pytest.fail("mismatch loaded model")
    )
    with pytest.raises(ProviderError, match="SDXL_PROBE_INPUT_INVALID"):
        legacy._run(prepared, root, _Backend())
    assert leases == []


def test_source_metadata_cannot_be_omitted_or_substituted(tmp_path, monkeypatch):
    prepared, _, _ = _stage(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="METADATA_MISSING"):
        validate_photo_style_execution_sources(
            prepared.command, replace(prepared.metadata.sources, object_support=None)
        )
    assert prepared.metadata.sources.object_support is not None
    invalid = replace(prepared.metadata.sources.object_support, review=b"{}")
    with pytest.raises(ValueError, match="BOUND_HASH"):
        validate_photo_style_execution_sources(
            prepared.command, replace(prepared.metadata.sources, object_support=invalid)
        )


@pytest.mark.parametrize(
    "field",
    [
        "configuration_command_sha256",
        "native_evaluation_command_sha256",
        "native_adapter_manifest_sha256",
    ],
)
def test_matching_parent_results_must_also_match_current_native_configuration(
    tmp_path, monkeypatch, field
):
    prepared, _, _ = _stage(tmp_path, monkeypatch)
    sources = prepared.metadata.sources
    documents = sources.object_support
    assert documents is not None
    value = json.loads(documents.prior_result)
    value[field] = "sha256:" + "0" * 64
    value["result_sha256"] = content_sha256(
        {k: v for k, v in value.items() if k != "result_sha256"}
    )
    raw = content_json_bytes(value)
    body = sources.plan.model_dump(mode="json")
    for name in ("prior_result", "baseline_result"):
        body["support_parents"][name]["sha256"] = _sha(raw)
    plan = parse_photo_style_plan_value(preparation.photos._seal_plan(body))
    command_value = prepared.command.model_dump(mode="json")
    command_value.update(plan_id=plan.plan_id, plan_sha256=plan.plan_sha256)
    command_value["plan"]["sha256"] = _sha(content_json_bytes(plan.model_dump(mode="json")))
    command = parse_photo_style_command(legacy._seal(command_value))
    changed = replace(
        sources, plan=plan, object_support=replace(documents, prior_result=raw, baseline_result=raw)
    )
    with pytest.raises(ValueError, match="NATIVE_PARENT_MISMATCH"):
        validate_photo_style_execution_sources(command, changed)


@pytest.mark.parametrize(
    "field",
    [
        "review_sha256",
        "support_mask_sha256",
        "prior_control_sha256",
        "candidate_control_sha256",
        "pixel_observation",
    ],
)
def test_resealed_result_cannot_lie_about_support(tmp_path, monkeypatch, field):
    prepared, root, _ = _stage(tmp_path, monkeypatch)
    result = legacy._run(prepared, root, _Backend())
    value = result.model_dump(mode="json", exclude={"result_sha256"})
    if field == "pixel_observation":
        value["object_support"][field]["support_area_pixels"] += 1
    else:
        value["object_support"][field] = "sha256:" + "f" * 64
    bad = parse_photo_style_result({**value, "result_sha256": content_sha256(value)})
    with pytest.raises(ValueError, match=r"support|SUPPORT"):
        validate_photo_style_result(prepared.command, prepared.metadata.sources, bad)


def test_new_schema_resources_and_public_contract_publication(tmp_path, monkeypatch):
    command, reader, _ = _fixture(tmp_path, monkeypatch)
    publisher = LocalImageTrainingControlArtifactPublisher(
        _Publisher(), source_commit=command.source_commit
    )
    plan = parse_photo_style_plan(command, reader.records[command.plan])
    assert publisher.commit_sdxl_photo_style_plan(plan).schema_ref.endswith("/1.6")
    assert publisher.commit_sdxl_photo_style_command(command).schema_ref.endswith("/1.6")
    repo = Path(__file__).resolve().parents[2]
    for family in ("plan", "command", "result"):
        key = "sdxl-photo-style-" + family + "-v7"
        filename = SCHEMA_FILES[key]
        raw = (repo / "schemas/image-provider" / filename).read_bytes()
        assert (
            raw
            == (
                repo / "packages/image_contracts/eom_image_contracts/schemas" / filename
            ).read_bytes()
        )
        assert _sha(raw) == SCHEMA_SHA256[key]
        for directory in ("image_provider", "image_trainer"):
            assert filename in (repo / "scripts" / directory / "build_release.sh").read_text()


@pytest.mark.parametrize("fault", [None, "pointer", "transform", "staged-input"])
def test_publication_references_existing_candidate_instead_of_duplicating_it(
    tmp_path, monkeypatch, fault
):
    from scripts.image_trainer import sdxl_validation_publication as publication

    prepared, root, _ = _stage(tmp_path, monkeypatch)
    result = legacy._run(prepared, root, _Backend())
    raw = content_json_bytes(prepared.command.model_dump(mode="json"))
    pin = prepared.command.plan.model_copy(
        update={
            "member_path": "manifests/sdxl-photo-style-command.json",
            "schema_ref": "eom://schemas/image-provider/local-image-sdxl-photo-style-command/"
            + ("1.5" if fault == "pointer" else "1.6"),
            "sha256": _sha(raw),
        }
    )
    monkeypatch.setattr(publication, "resolve_control_artifact_member", lambda *a, **k: raw)
    monkeypatch.setattr(publication, "prepare_sdxl_photo_style_inputs", lambda *a: prepared)
    events = []

    def verify(workspace, expected):
        events.append("CPU")
        if fault == "transform":
            raise ValueError("invalid support transform")
        assert (
            content_json_bytes(
                worker.verify_sdxl_photo_style_transforms(workspace).model_dump(mode="json")
            )
            == expected
        )

    class Publisher:
        def __init__(self, engine):
            pass

        def publish(self, **kwargs):
            events.append("COMMIT")
            assert kwargs["manifest_version"] == "sdxl-photo-style-result-artifact/1.6"
            members = kwargs["members"]
            assert len(members) == 6
            assert not any(m.file_name.startswith(("conditionings/", "inputs/")) for m in members)
            assert (
                result.object_support.candidate_control_sha256
                == result.inputs[0].conditioning_sha256
            )
            return kwargs

    monkeypatch.setattr(publication, "verify_reserved_transforms_cpu", verify)
    monkeypatch.setattr(publication, "ControlFileSetPublisher", Publisher)
    if fault == "staged-input":
        path = root / "inputs/object-support/mask.png"
        path.write_bytes(path.read_bytes() + b" ")

    def call():
        return publication.publish_sdxl_photo_style_comparison(
            object(),
            prepared.command,
            command_pointer=pin,
            workspace=root,
            worker_uid=os.getuid(),
            source_commit=prepared.command.source_commit,
            created_at=result.completed_at + timedelta(seconds=1),
        )

    if fault is None:
        call()
        assert events == ["CPU", "COMMIT"]
    else:
        with pytest.raises((ValueError, ProviderError)):
            call()
        assert "COMMIT" not in events
