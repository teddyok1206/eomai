"""Declared region handoff preserves input pixels, not a scientific/style quality guarantee."""

from __future__ import annotations

import copy
import hashlib
import io
import os
from datetime import timedelta
from pathlib import Path

import pytest
from eom_image_contracts.models import (
    ImageEvaluationArtifactMember,
    content_json_bytes,
    content_sha256,
)
from eom_image_contracts.sdxl_canny_comparison import SdxlCannyControlParameters
from eom_image_contracts.sdxl_canny_conditioning import SdxlCannyPolicy
from eom_image_contracts.sdxl_photo_region_review import (
    SdxlPhotoSourceRegionBox,
    photo_source_box_to_canvas,
)
from eom_image_contracts.sdxl_photo_style import (
    LocalImageSdxlPhotoStyleRetainedRegionPlan,
    parse_photo_style_plan_value,
    photo_style_control_parameters,
    photo_style_region_reviews_sha256,
    validate_photo_style_region_evidence,
)
from eom_image_contracts.sdxl_photo_style_execution import (
    LocalImageSdxlPhotoStyleRetainedRegionCommand,
    LocalImageSdxlPhotoStyleRetainedRegionResult,
    parse_photo_style_command,
    parse_photo_style_plan,
    parse_photo_style_result,
    validate_photo_style_result,
)
from eom_image_contracts.validation import SCHEMA_FILES, SCHEMA_SHA256
from eom_image_provider import sdxl_photo_style as worker
from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_comparison_command import load_sdxl_comparison_command
from eom_image_provider.sdxl_photo_conditioning import photo_style_conditioner
from eom_orchestrator import sdxl_photo_style_inputs as admission
from eom_orchestrator.control_artifact_resolution import ControlArtifactResolutionError
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from jsonschema import ValidationError as SchemaError
from PIL import Image, ImageDraw, ImageOps
from pydantic import ValidationError

from tests.unit import test_sdxl_photo_style_execution as legacy
from tests.unit import test_sdxl_photo_style_full_denoising as full
from tests.unit import test_sdxl_photo_style_white_initializer as white
from tests.unit.test_local_image_training_control_artifacts import _Publisher
from tests.unit.test_sdxl_learned_comparison import _Backend


def _fixture(tmp_path, monkeypatch):
    command, reader, events, _ = full._fixture(tmp_path, monkeypatch)
    prior = parse_photo_style_plan(command, reader.records[command.plan])
    evidence_raw = b"Own reviewed morphology: preserve subject placement; irrelevant backdrop only."
    evidence = ImageEvaluationArtifactMember(
        artifact_id="artifact_" + "a" * 32,
        artifact_revision_id="rev_" + "a" * 32,
        member_path="reports/own-review.md",
        schema_ref="eom://schemas/operations/plain-text-log/1.0",
        media_type="text/plain",
        sha256="sha256:" + hashlib.sha256(evidence_raw).hexdigest(),
    )
    review = dict(
        case_id=prior.cases[0].case.case_id,
        reference_sha256=prior.cases[0].case.reference_image.sha256,
        coordinate_system="NORMALIZED_PHOTO_SOURCE_PIXELS_800X504/1.0",
        source_width_px=800,
        source_height_px=504,
        retained_box=dict(left=100, top=50, right=700, bottom=450),
        protected_boxes=[dict(left=150, top=100, right=650, bottom=400)],
        context_policy="SUBJECT_MORPHOLOGY_ONLY_IRRELEVANT_BACKDROP",
        reviewed_at=prior.created_at.isoformat().replace("+00:00", "Z"),
        reviewed_by="root-codex",
        observation="Keep subject and fine internal marks; no scene-dependent background deletion.",
    )
    value = prior.model_dump(mode="json")
    value.update(
        schema_version="local-image-sdxl-photo-style-plan/1.4",
        control=SdxlCannyControlParameters().model_dump(mode="json"),
        region_reviews=[review],
        region_review_evidence=evidence.model_dump(mode="json"),
    )
    plan = parse_photo_style_plan_value(white._plan_seal(value))
    raw = content_json_bytes(plan.model_dump(mode="json"))
    pin = command.plan.model_copy(
        update={
            "artifact_revision_id": "rev_" + "4" * 32,
            "schema_ref": "eom://schemas/image-provider/" + plan.schema_version,
            "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        }
    )
    reader.records.update({pin: raw, evidence: evidence_raw})
    body = command.model_dump(mode="json")
    body.update(
        schema_version="local-image-sdxl-photo-style-command/1.4",
        plan=pin.model_dump(mode="json"),
        plan_id=plan.plan_id,
        plan_sha256=plan.plan_sha256,
    )
    return parse_photo_style_command(legacy._seal(body)), reader, events, prior


def _canny(canvas, *, policy):
    image = Image.new("RGB", (832, 512), "black")
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((200, 140, 600, 320), outline="white")
    drawing.line((20, 20, 810, 20), fill="white")
    stream = io.BytesIO()
    image.save(stream, format="PNG", compress_level=9)
    return stream.getvalue()


def _stage(tmp_path, monkeypatch):
    def fixture(path, patch):
        command, reader, events, _ = _fixture(path, patch)
        return command, reader, events

    monkeypatch.setattr(legacy, "_fixture", fixture)
    prepared, root, leases = legacy._stage(tmp_path, monkeypatch)
    monkeypatch.setattr(worker, "canny_conditioning_canvas_png", _canny)
    return prepared, root, leases


def test_schema_resources_old_families_and_exact_pins(tmp_path, monkeypatch):
    command, reader, _, prior = _fixture(tmp_path, monkeypatch)
    plan = parse_photo_style_plan(command, reader.records[command.plan])
    assert isinstance(command, LocalImageSdxlPhotoStyleRetainedRegionCommand)
    assert isinstance(plan, LocalImageSdxlPhotoStyleRetainedRegionPlan)
    assert plan.cases == prior.cases and plan.configuration_anchor == prior.configuration_anchor
    assert plan.initialization == prior.initialization and plan.seed == prior.seed
    assert photo_style_control_parameters(plan, SdxlCannyControlParameters()) is plan.control
    root = Path(__file__).resolve().parents[2]
    for family in ("plan", "command", "result"):
        for suffix in ("", "-v2", "-v3", "-v4", "-v5"):
            key = "sdxl-photo-style-" + family + suffix
            name = SCHEMA_FILES[key]
            raw = (root / "schemas/image-provider" / name).read_bytes()
            assert (
                raw
                == (
                    root / "packages/image_contracts/eom_image_contracts/schemas" / name
                ).read_bytes()
            )
            assert "sha256:" + hashlib.sha256(raw).hexdigest() == SCHEMA_SHA256[key]
    publisher = LocalImageTrainingControlArtifactPublisher(
        _Publisher(), source_commit=command.source_commit
    )
    assert publisher.commit_sdxl_photo_style_plan(plan).schema_ref.endswith("/1.4")
    assert publisher.commit_sdxl_photo_style_command(command).schema_ref.endswith("/1.4")
    assert (
        SCHEMA_SHA256["sdxl-photo-style-plan-v4"]
        == "sha256:6d6ad158baf242fe9592abdf26284c33638c3cd30e0f6ac310052f845caf8f75"
    )


@pytest.mark.parametrize(
    "fault",
    [
        "missing-region",
        "missing-evidence",
        "missing-control",
        "missing-control-field",
        "source",
        "case",
        "duplicate",
        "future",
        "out-of-bounds",
        "bool",
        "string",
        "protection-empty",
        "protection-outside",
        "protection-duplicate",
        "context",
        "coordinate-system",
        "window",
        "evidence-media",
        "evidence-schema",
        "evidence-member",
        "legacy",
        "initializer",
        "extra",
    ],
)
def test_invalid_or_undeclared_region_plan_rejected(tmp_path, monkeypatch, fault):
    command, reader, _, _ = _fixture(tmp_path, monkeypatch)
    value = copy.deepcopy(
        parse_photo_style_plan(command, reader.records[command.plan]).model_dump(mode="json")
    )
    review = value["region_reviews"][0]
    if fault == "missing-region":
        del value["region_reviews"]
    elif fault == "missing-evidence":
        del value["region_review_evidence"]
    elif fault == "missing-control":
        del value["control"]
    elif fault == "missing-control-field":
        del value["control"]["guidance_end"]
    elif fault == "source":
        review["reference_sha256"] = "sha256:" + "0" * 64
    elif fault == "case":
        review["case_id"] = "imgsdxlcase_" + "0" * 32
    elif fault == "duplicate":
        value["region_reviews"] *= 2
    elif fault == "future":
        review["reviewed_at"] = (
            (command.created_at + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        )
    elif fault == "out-of-bounds":
        review["retained_box"]["right"] = 801
    elif fault == "bool":
        review["retained_box"]["left"] = True
    elif fault == "string":
        review["retained_box"]["left"] = "100"
    elif fault == "protection-empty":
        review["protected_boxes"] = []
    elif fault == "protection-outside":
        review["protected_boxes"][0]["left"] = 99
    elif fault == "protection-duplicate":
        review["protected_boxes"] *= 2
    elif fault == "context":
        review["context_policy"] = "SCENE_CONTEXT_MAY_BE_REMOVED"
    elif fault == "coordinate-system":
        review["coordinate_system"] = "CANVAS_COORDINATES"
    elif fault == "window":
        value["control"]["guidance_end"] = 0.65
    elif fault == "evidence-media":
        value["region_review_evidence"]["media_type"] = "image/png"
    elif fault == "evidence-schema":
        value["region_review_evidence"]["schema_ref"] += "-latest"
    elif fault == "evidence-member":
        value["region_review_evidence"]["member_path"] = "other.md"
    elif fault == "legacy":
        value["schema_version"] = "local-image-sdxl-photo-style-plan/1.2"
    elif fault == "initializer":
        value["initialization"]["denoising_strength"] = 0.7
    else:
        value["region_selection_automatic"] = True
    with pytest.raises((ValueError, SchemaError, ValidationError)):
        parse_photo_style_plan_value(white._plan_seal(value))


@pytest.mark.parametrize(
    "bounds,expected",
    [
        ((285, 145, 507, 387), (301, 149, 523, 390)),
        ((76, 44, 729, 457), (94, 49, 743, 460)),
        ((103, 163, 746, 430), (121, 167, 760, 433)),
        ((0, 0, 800, 504), (19, 6, 813, 506)),
    ],
)
def test_contract_mapping_matches_actual_pillow_fit_without_reframing(bounds, expected):
    fitted = ImageOps.contain(Image.new("RGB", (800, 504)), (800, 500), Image.Resampling.LANCZOS)
    assert fitted.size == (794, 500)
    assert ((832 - fitted.width) // 2, (512 - fitted.height) // 2) == (19, 6)
    box = SdxlPhotoSourceRegionBox.model_validate(
        dict(zip(("left", "top", "right", "bottom"), bounds, strict=True))
    )
    mapped = photo_source_box_to_canvas(box)
    assert (mapped.left, mapped.top, mapped.right, mapped.bottom) == expected
    with pytest.raises(ValidationError):
        box.left = 0


def test_metadata_evidence_is_bounded_staged_once_and_in_closure(tmp_path, monkeypatch):
    command, reader, _, _ = _fixture(tmp_path, monkeypatch)
    prepared = admission.prepare_sdxl_photo_style_inputs(object(), command)
    assert isinstance(prepared.metadata.sources.plan, LocalImageSdxlPhotoStyleRetainedRegionPlan)
    evidence = prepared.metadata.sources.plan.region_review_evidence
    assert reader.calls.count(evidence) == 1
    assert reader.calls.index(evidence) < next(
        i for i, p in enumerate(reader.calls) if p.media_type == "image/png"
    )
    expected = admission.sdxl_photo_style_input_hashes(prepared)
    assert {f.member_path: f.sha256 for f in prepared.files} == expected
    assert expected["inputs/photo-region-review.txt"] == evidence.sha256


def test_same_conditioner_protects_inside_zeros_only_outside_and_legacy_is_identical(
    tmp_path, monkeypatch
):
    command, reader, _, prior = _fixture(tmp_path, monkeypatch)
    plan = parse_photo_style_plan(command, reader.records[command.plan])
    case = plan.cases[0].case
    canvas = Image.new("RGB", (832, 512), "white")
    old = _canny(canvas, policy=SdxlCannyPolicy())
    assert (
        photo_style_conditioner(prior, canny=_canny)(case, canvas, policy=SdxlCannyPolicy()) == old
    )
    new = photo_style_conditioner(plan, canny=_canny)(case, canvas, policy=SdxlCannyPolicy())
    box = photo_source_box_to_canvas(plan.region_reviews[0].retained_box)
    bounds = (box.left, box.top, box.right, box.bottom)
    with Image.open(io.BytesIO(old)) as a, Image.open(io.BytesIO(new)) as b:
        assert a.crop(bounds).tobytes() == b.crop(bounds).tobytes()
        assert b.getpixel((30, 20)) == (0, 0, 0)
        assert b.getpixel((200, 140)) == (255, 255, 255)
    with pytest.raises(KeyError):
        photo_style_conditioner(plan, canny=_canny)(
            case.model_copy(update={"case_id": "imgsdxlcase_" + "0" * 32}),
            canvas,
            policy=SdxlCannyPolicy(),
        )


@pytest.mark.parametrize("fault", [None, "second", "oom", "unexpected"])
def test_pair_gets_exact_retained_pixels_full_control_and_terminal_replay_pure(
    tmp_path, monkeypatch, fault
):
    prepared, root, leases = _stage(tmp_path, monkeypatch)
    observed = []

    def factory(controller, control, initialization, inputs):
        assert control == SdxlCannyControlParameters() and initialization.denoising_strength == 1.0
        assert all(p.canvas_rgb == bytes([255]) * (832 * 512 * 3) for p in inputs.values())
        for p in inputs.values():
            with Image.open(io.BytesIO(p.conditioning_png)) as image:
                assert image.getpixel((30, 20)) == (0, 0, 0) and image.getpixel((200, 140)) == (
                    255,
                    255,
                    255,
                )
        observed.append(inputs)
        return _Backend(fault)

    result = worker.run_sdxl_photo_style(
        command=prepared.command,
        workspace=root,
        model_store_root=root / "models",
        gpu_lock=root / "gpu.lock",
        backend_factory=factory,
    )
    assert isinstance(result, LocalImageSdxlPhotoStyleRetainedRegionResult)
    assert result.status == ("SUCCEEDED" if fault is None else "FAILED")
    assert len(result.outputs) == {None: 2, "second": 1, "oom": 0, "unexpected": 0}[fault]
    assert result.region_reviews_sha256 == photo_style_region_reviews_sha256(
        prepared.metadata.sources.plan
    )
    assert len(observed) == 1 and leases == ["ENTER", "EXIT"]
    assert load_sdxl_comparison_command(root, root / "command.json") == prepared.command
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()}

    def forbidden(*a, **k):
        raise AssertionError("REPLAY_SIDE_EFFECT")

    for name in (
        "resolve_sdxl_stack",
        "resolve_sdxl_canny_controller",
        "load_sdxl_lora_material",
        "prepare_sdxl_reference_pixels",
        "create_sdxl_pair_directories",
        "write_staged_member",
        "photo_style_conditioner",
    ):
        monkeypatch.setattr(worker, name, forbidden)
    assert legacy._run(prepared, root, _Backend()) == result
    assert before == {
        p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize("fault", ["missing", "corrupt"])
def test_review_evidence_never_implicitly_recovers_or_uses_gpu(tmp_path, monkeypatch, fault):
    prepared, root, leases = _stage(tmp_path, monkeypatch)
    path = root / "inputs/photo-region-review.txt"
    if fault == "missing":
        path.unlink()
    else:
        path.write_bytes(b"different review")
    with pytest.raises(ProviderError):
        legacy._run(prepared, root, _Backend())
    assert leases == [] and not (root / "result.json").exists() and not (root / "outputs").exists()


@pytest.mark.parametrize("fault", ["review-hash", "control", "family", "source"])
def test_rehashed_result_does_not_forge_review_control_lineage(tmp_path, monkeypatch, fault):
    prepared, root, _ = _stage(tmp_path, monkeypatch)
    result = legacy._run(prepared, root, _Backend())
    value = copy.deepcopy(result.model_dump(mode="json", exclude={"result_sha256"}))
    if fault == "review-hash":
        value["region_reviews_sha256"] = "sha256:" + "0" * 64
    elif fault == "control":
        value["control"]["guidance_end"] = 0.65
    elif fault == "family":
        value["schema_version"] = "local-image-sdxl-photo-style-result/1.2"
    else:
        value["inputs"][0]["source_sha256"] = "sha256:" + "0" * 64
    with pytest.raises((ValueError, SchemaError, ValidationError)):
        parsed = parse_photo_style_result({**value, "result_sha256": content_sha256(value)})
        validate_photo_style_result(prepared.command, prepared.metadata.sources, parsed)


def test_installed_cpu_verifier_uses_identical_conditioner_and_has_no_writes(tmp_path, monkeypatch):
    prepared, root, _ = _stage(tmp_path, monkeypatch)
    result = legacy._run(prepared, root, _Backend())
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert worker.verify_sdxl_photo_style_transforms(root) == result
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("fault", ["case", "source"])
def test_unknown_or_wrong_case_fails_before_pixel_dereference(tmp_path, monkeypatch, fault):
    command, reader, _, _ = _fixture(tmp_path, monkeypatch)
    plan = parse_photo_style_plan(command, reader.records[command.plan])
    case = plan.cases[0].case
    if fault == "case":
        case = case.model_copy(update={"case_id": "imgsdxlcase_" + "0" * 32})
    else:
        case = case.model_copy(
            update={
                "reference_image": case.reference_image.model_copy(
                    update={"sha256": "sha256:" + "0" * 64}
                )
            }
        )

    def forbidden(*args, **kwargs):
        raise AssertionError("invalid region case must fail before pixel extraction")

    with pytest.raises((KeyError, ValueError)):
        photo_style_conditioner(plan, canny=forbidden)(
            case, Image.new("RGB", (832, 512)), policy=SdxlCannyPolicy()
        )


@pytest.mark.parametrize("raw", [b"", b" ", b"\xff", b"text\x00", b"a" * (64 * 1024 + 1)])
def test_even_correctly_hashed_review_evidence_is_bounded_nonempty_utf8(tmp_path, monkeypatch, raw):
    command, reader, _, _ = _fixture(tmp_path, monkeypatch)
    plan = parse_photo_style_plan(command, reader.records[command.plan])
    plan = plan.model_copy(
        update={
            "region_review_evidence": plan.region_review_evidence.model_copy(
                update={"sha256": "sha256:" + hashlib.sha256(raw).hexdigest()}
            )
        }
    )
    with pytest.raises(ValueError):
        validate_photo_style_region_evidence(plan, raw)


def test_missing_registered_evidence_fails_during_metadata_before_binary_materialization(
    tmp_path, monkeypatch
):
    command, reader, _, _ = _fixture(tmp_path, monkeypatch)
    plan = parse_photo_style_plan(command, reader.records[command.plan])
    del reader.records[plan.region_review_evidence]
    reader.calls.clear()
    with pytest.raises(ControlArtifactResolutionError, match="CONTROL_ARTIFACT_POINTER_INVALID"):
        admission.prepare_sdxl_photo_style_inputs(object(), command)
    assert all(p.media_type in ("application/json", "text/plain") for p in reader.calls)


@pytest.mark.parametrize("fault", [None, "pointer", "transform"])
def test_publication_keeps_existing_single_cpu_validated_commit_owner(tmp_path, monkeypatch, fault):
    from scripts.image_trainer import sdxl_validation_publication as publication

    prepared, root, _ = _stage(tmp_path, monkeypatch)
    result = legacy._run(prepared, root, _Backend())
    raw = content_json_bytes(prepared.command.model_dump(mode="json"))
    pin = prepared.command.plan.model_copy(
        update={
            "member_path": "manifests/sdxl-photo-style-command.json",
            "schema_ref": "eom://schemas/image-provider/local-image-sdxl-photo-style-command/"
            + ("1.3" if fault == "pointer" else "1.4"),
            "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        }
    )
    monkeypatch.setattr(publication, "resolve_control_artifact_member", lambda *a, **k: raw)
    monkeypatch.setattr(publication, "prepare_sdxl_photo_style_inputs", lambda *a: prepared)
    events = []

    def verify(workspace, expected):
        events.append("CPU")
        if fault == "transform":
            raise ValueError("invalid region transforms")
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
            assert kwargs["manifest_version"] == "sdxl-photo-style-result-artifact/1.4"
            assert len(kwargs["members"]) == 7
            return kwargs

    monkeypatch.setattr(publication, "verify_reserved_transforms_cpu", verify)
    monkeypatch.setattr(publication, "ControlFileSetPublisher", Publisher)

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
