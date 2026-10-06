"""Source-join and owner orchestration tests, not pixels, real dispatch or quality acceptance."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest
from eom_image_contracts import content_json_bytes, content_sha256
from eom_image_contracts.models import ImageEvaluationArtifactMember
from eom_image_contracts.sdxl_canny_reference import SdxlCannyReferenceTrace
from eom_image_contracts.sdxl_ip_style_comparison import (
    LocalImageSdxlIpStyleComparisonPlan,
    select_sdxl_ip_style_sources,
)
from eom_image_contracts.sdxl_native_lora import LocalImageSdxlNativeLoraCommandV4
from eom_image_contracts.sdxl_native_lora_sources import parse_sdxl_native_lora_sources
from eom_image_contracts.sdxl_photo_style import SDXL_PHOTO_WHITE_INITIALIZER_RGB_SHA256
from eom_image_contracts.sdxl_photo_style_execution import (
    parse_photo_style_command,
    parse_photo_style_result,
)
from eom_image_contracts.source_page_crops import (
    ScienceSourcePageCropRegion,
    ScienceSourcePageRegionSelection,
)
from eom_orchestrator import sdxl_ip_style_inputs as owner

from tests.unit.test_native_contour_loss_contracts import _weighted_value
from tests.unit.test_sdxl_ip_style_comparison_plan import _pin, _seal, _value
from tests.unit.test_sdxl_native_lora_sources import _fixture, _staged_metadata
from tests.unit.test_sdxl_photo_style import _plan, _source
from tests.unit.test_sdxl_photo_style_execution import _seal as _seal_photo


@pytest.fixture(scope="module")
def source_values():
    with pytest.MonkeyPatch.context() as patch:
        native, records, *_ = _fixture(patch)
        sources = parse_sdxl_native_lora_sources(native, _staged_metadata(records))
    photos = _plan((_source(1)[0], _source(2)[0])).cases
    traces = tuple(
        SdxlCannyReferenceTrace(
            case_id=p.case.case_id,
            source_sha256=p.case.reference_image.sha256,
            conditioning_sha256="sha256:" + f"{i + 1:064x}",
            initialization_rgb_sha256=SDXL_PHOTO_WHITE_INITIALIZER_RGB_SHA256,
        )
        for i, p in enumerate(photos)
    )
    value = _value()
    value["cases"] = [
        dict(
            case_id=p.case.case_id,
            conditioning_sha256=t.conditioning_sha256,
            initialization_rgb_sha256=t.initialization_rgb_sha256,
            style_sample_id=s.sample_id,
            style_rgb_sha256="sha256:" + f"{i + 3:064x}",
        )
        for i, (p, t, s) in enumerate(zip(photos, traces, native.training_samples[:2], strict=True))
    ]
    plan = LocalImageSdxlIpStyleComparisonPlan.model_validate(_seal(value))
    return plan, dict(
        photo_cases=photos,
        photo_traces=traces,
        style_samples=native.training_samples,
        style_regions=sources.regions,
    )


def test_pure_join_is_frozen_ordered_and_keeps_original_pointers(source_values):
    plan, values = source_values
    selected = select_sdxl_ip_style_sources(plan, **values)
    assert tuple(r.selection for r in selected) == plan.cases
    assert all(r.style_region.partition == "TRAIN" for r in selected)
    assert all(
        r.style_sample.source_image in tuple(s.source_image for s in values["style_samples"])
        for r in selected
    )
    with pytest.raises(FrozenInstanceError):
        selected[0].selection = plan.cases[1]
    # Source join cannot prove the224px RGB hash; this belongs to later pinned pixel preparation.
    value = plan.model_dump(mode="json")
    value["cases"][0]["style_rgb_sha256"] = "sha256:" + "f" * 64
    changed = LocalImageSdxlIpStyleComparisonPlan.model_validate(_seal(value))
    assert select_sdxl_ip_style_sources(changed, **values)[0].selection == changed.cases[0]


@pytest.mark.parametrize(
    "region_model", [ScienceSourcePageCropRegion, ScienceSourcePageRegionSelection]
)
def test_supported_region_shapes_preserve_identity_and_extra_provenance(
    source_values, region_model
):
    plan, values = source_values
    regions = []
    for region in values["style_regions"]:
        raw = region.model_dump(mode="json", exclude={"candidate_id", "parent_candidate_sha256"})
        if region_model is ScienceSourcePageRegionSelection:
            raw["source_anchor"] = "REVIEWED_ORIGINAL_PAGE"
        regions.append(region_model.model_validate(raw))
    rows = select_sdxl_ip_style_sources(plan, **{**values, "style_regions": tuple(regions)})
    assert all(type(row.style_region) is region_model for row in rows)


def test_unknown_region_subclass_is_not_an_authorization_extension(source_values):
    plan, values = source_values

    class UnknownRegion(ScienceSourcePageCropRegion):
        invented_permission: str

    region = values["style_regions"][0]
    raw = region.model_dump(mode="json", exclude={"candidate_id", "parent_candidate_sha256"})
    raw["invented_permission"] = "ANY_CORPUS"
    regions = (UnknownRegion.model_validate(raw), *values["style_regions"][1:])
    with pytest.raises(ValueError, match="REGION_FAMILY_INVALID"):
        select_sdxl_ip_style_sources(plan, **{**values, "style_regions": regions})


@pytest.mark.parametrize("key", ["photo_cases", "photo_traces", "style_samples", "style_regions"])
def test_missing_or_duplicate_metadata_closure_fails(source_values, key):
    plan, original = source_values
    for changed in (original[key][1:], (*original[key], original[key][0])):
        values = {**original, key: changed}
        with pytest.raises(ValueError, match="DUPLICATE_OR_CLOSURE"):
            select_sdxl_ip_style_sources(plan, **values)


@pytest.mark.parametrize("field", ["conditioning_sha256", "initialization_rgb_sha256"])
def test_resealed_plan_cannot_change_selected_photo_trace(source_values, field):
    plan, values = source_values
    value = plan.model_dump(mode="json")
    value["cases"][0][field] = "sha256:" + "f" * 64
    changed = LocalImageSdxlIpStyleComparisonPlan.model_validate(_seal(value))
    with pytest.raises(ValueError, match="PHOTO_TRACE_MISMATCH"):
        select_sdxl_ip_style_sources(changed, **values)


@pytest.mark.parametrize("field", ["case_id", "style_sample_id"])
def test_resealed_missing_selected_identity_is_not_latest_fallback(source_values, field):
    plan, values = source_values
    value = plan.model_dump(mode="json")
    value["cases"][0][field] = (
        "imgsdxlcase_" if field == "case_id" else "imgsourcecrop_"
    ) + "f" * 32
    value["cases"].sort(key=lambda row: row["case_id"])
    changed = LocalImageSdxlIpStyleComparisonPlan.model_validate(_seal(value))
    with pytest.raises(ValueError, match="SELECTED_SOURCE_MISSING"):
        select_sdxl_ip_style_sources(changed, **values)


@pytest.mark.parametrize("field", ["source_document_id", "exam_group_sha256"])
def test_style_source_document_and_group_must_match_canonical_region(source_values, field):
    plan, values = source_values
    samples = list(values["style_samples"])
    samples[0] = samples[0].model_copy(
        update={
            field: "sciencedoc_" + "f" * 32
            if field == "source_document_id"
            else "sha256:" + "f" * 64
        }
    )
    with pytest.raises(ValueError, match="TRAIN_LINEAGE_MISMATCH"):
        select_sdxl_ip_style_sources(plan, **{**values, "style_samples": tuple(samples)})


@pytest.mark.parametrize("fault", ["partition", "media", "case", "trace-source", "plan-copy"])
def test_untrusted_model_copy_bypasses_are_revalidated(source_values, fault):
    plan, values = source_values
    values = dict(values)
    if fault == "partition":
        rows = list(values["style_regions"])
        rows[0] = rows[0].model_copy(update={"partition": "HOLDOUT"})
        values["style_regions"] = tuple(rows)
    elif fault == "media":
        rows = list(values["style_samples"])
        rows[0] = rows[0].model_copy(
            update={
                "source_image": rows[0].source_image.model_copy(
                    update={"media_type": "application/pdf"}
                )
            }
        )
        values["style_samples"] = tuple(rows)
    elif fault == "case":
        rows = list(values["photo_cases"])
        rows[0] = rows[0].model_copy(
            update={
                "case": rows[0].case.model_copy(
                    update={"prompt_en": "an unsealed replacement prompt"}
                )
            }
        )
        values["photo_cases"] = tuple(rows)
    elif fault == "trace-source":
        rows = list(values["photo_traces"])
        rows[0] = rows[0].model_copy(update={"source_sha256": "sha256:" + "f" * 64})
        values["photo_traces"] = tuple(rows)
    else:
        plan = plan.model_copy(update={"activation_policy": "ALLOWED"})
    with pytest.raises(ValueError):
        select_sdxl_ip_style_sources(plan, **values)


def _owner_fixture(monkeypatch):
    # Parent source owners/selector are stubs here. Concrete pure joins are tested above;
    # existing owner regression and a separate canonical metadata probe cover real lineage.
    value = _value()
    photo = parse_photo_style_command(
        _seal_photo(
            dict(
                schema_version="local-image-sdxl-photo-style-command/1.5",
                source_commit="a" * 40,
                created_at="2026-10-04T00:00:00Z",
                purpose="EVALUATION_ONLY_PHOTO_TO_EXAM_STYLE",
                activation_policy="FORBIDDEN",
                plan=_pin(5, "sdxl-photo-style-plan/1.5"),
                plan_id="imgsdxlphotoplan_" + "5" * 32,
                plan_sha256="sha256:" + "5" * 64,
            )
        )
    )
    result_value = dict(
        schema_version="local-image-sdxl-photo-style-result/1.5",
        run_id=photo.run_id,
        command_sha256=photo.command_sha256,
        plan_sha256=photo.plan_sha256,
        configuration_command_sha256="sha256:" + "1" * 64,
        native_evaluation_command_sha256="sha256:" + "2" * 64,
        native_adapter_manifest_sha256="sha256:" + "3" * 64,
        case_relation="LICENSED_PHOTO_REFERENCES_NOT_CORPUS_HOLDOUT",
        native_fit_policy="NATIVE_FIT_800X500_CENTER_832X512_OPENCV_CANNY/1.0",
        initialization=dict(
            policy="CONSTANT_WHITE_RGB_832X512_FULL_DENOISE/1.0",
            denoising_strength=1.0,
            scheduler_steps=30,
            effective_denoising_steps=30,
            pillow_version="11.3.0",
        ),
        quality_acceptance="NOT_REVIEWED",
        activation_policy="FORBIDDEN",
        training_steps=0,
        holdout_binary_reads=0,
        status="SUCCEEDED",
        error_code=None,
        runtime=None,
        inputs=[
            dict(
                case_id="imgsdxlcase_" + "1" * 32,
                source_sha256="sha256:" + "1" * 64,
                conditioning_sha256="sha256:" + "2" * 64,
                initialization_rgb_sha256=SDXL_PHOTO_WHITE_INITIALIZER_RGB_SHA256,
                width_px=832,
                height_px=512,
            )
        ],
        outputs=[],
        started_at="2026-10-04T00:00:01Z",
        completed_at="2026-10-04T00:00:02Z",
        duration_ms=1000,
        control=dict(
            policy_version="CONTROL_0_7_CFG_5_5/1.0", control_scale=0.7, guidance_scale=5.5
        ),
        region_reviews_sha256="sha256:" + "a" * 64,
    )
    # Use the actual existing control value contract, not an invented policy.
    from eom_image_contracts.sdxl_canny_comparison import SdxlCannyControlParameters

    result_value["control"] = SdxlCannyControlParameters().model_dump(mode="json")
    result_value["result_sha256"] = content_sha256(result_value)
    result = parse_photo_style_result(result_value)
    style = LocalImageSdxlNativeLoraCommandV4.model_validate(_weighted_value())
    records = {}
    for field, model in (
        ("photo_command", photo),
        ("photo_result", result),
        ("style_training_command", style),
    ):
        raw = content_json_bytes(model.model_dump(mode="json"))
        value[field]["sha256"] = content_sha256(model.model_dump(mode="json"))
        pointer = ImageEvaluationArtifactMember.model_validate(value[field])
        records[pointer] = raw
    plan = LocalImageSdxlIpStyleComparisonPlan.model_validate(_seal(value))
    events = []
    photo_metadata = SimpleNamespace(
        command=photo, sources=SimpleNamespace(plan=SimpleNamespace(cases=()))
    )
    style_metadata = SimpleNamespace(command=style, sources=SimpleNamespace(regions=()))

    def read(engine, reads):
        events.append("PARENTS")
        assert len(reads) == 3 and all(r.maximum_bytes == 256 * 1024 for r in reads)
        assert all(r.pointer.media_type == "application/json" for r in reads)
        return tuple(records[r.pointer] for r in reads)

    monkeypatch.setattr(owner, "resolve_control_artifact_members", read)
    monkeypatch.setattr(
        owner,
        "resolve_sdxl_photo_style_execution_metadata",
        lambda *_: (events.append("PHOTO_OWNER"), photo_metadata)[1],
    )
    monkeypatch.setattr(
        owner, "validate_photo_style_result", lambda *_: events.append("RESULT_VALIDATOR")
    )
    monkeypatch.setattr(
        owner,
        "resolve_sdxl_native_lora_sources",
        lambda *_: (events.append("TRAIN_OWNER"), style_metadata)[1],
    )
    monkeypatch.setattr(
        owner, "select_sdxl_ip_style_sources", lambda *_a, **_k: (events.append("SELECTOR"), ())[1]
    )
    return plan, records, events, photo_metadata, style_metadata


def test_metadata_bridge_calls_existing_owners_in_order_without_pixel_or_model_ops(monkeypatch):
    plan, _, events, photo, style = _owner_fixture(monkeypatch)
    resolved = owner.resolve_sdxl_ip_style_selection_metadata(object(), plan)
    assert events == ["PARENTS", "PHOTO_OWNER", "RESULT_VALIDATOR", "TRAIN_OWNER", "SELECTOR"]
    assert resolved.plan == plan and resolved.photo is photo and resolved.style is style
    assert resolved.cases == ()  # Selector is intentionally stubbed for this orchestration unit.
    with pytest.raises(FrozenInstanceError):
        resolved.plan = plan


@pytest.mark.parametrize("field", ["photo_command", "photo_result", "style_training_command"])
def test_missing_parent_stops_before_source_owners(monkeypatch, field):
    plan, records, events, *_ = _owner_fixture(monkeypatch)
    del records[getattr(plan, field)]
    with pytest.raises(KeyError):
        owner.resolve_sdxl_ip_style_selection_metadata(object(), plan)
    assert events == ["PARENTS"]


@pytest.mark.parametrize("field", ["photo_command", "photo_result", "style_training_command"])
def test_noncanonical_parent_stops_before_source_owners(monkeypatch, field):
    plan, records, events, *_ = _owner_fixture(monkeypatch)
    pin = getattr(plan, field)
    records[pin] += b"\n"
    with pytest.raises(ValueError, match="CANONICAL_BYTES"):
        owner.resolve_sdxl_ip_style_selection_metadata(object(), plan)
    assert events == ["PARENTS"]


def test_future_parent_is_rejected_before_source_reads(monkeypatch):
    plan, _, events, *_ = _owner_fixture(monkeypatch)
    value = plan.model_dump(mode="json")
    value["created_at"] = "2026-10-01T00:00:00Z"
    changed = LocalImageSdxlIpStyleComparisonPlan.model_validate(_seal(value))
    with pytest.raises(ValueError, match="CHRONOLOGY"):
        owner.resolve_sdxl_ip_style_selection_metadata(object(), changed)
    assert events == ["PARENTS"]


def test_failed_parent_is_preserved_and_cannot_supply_comparison_authority(monkeypatch):
    plan, records, events, *_ = _owner_fixture(monkeypatch)
    result = parse_photo_style_result(json.loads(records[plan.photo_result]))
    value = result.model_dump(mode="json", exclude={"result_sha256"})
    value.update(status="FAILED", error_code="SDXL_PROBE_INPUT_INVALID")
    changed = parse_photo_style_result({**value, "result_sha256": content_sha256(value)})
    raw = content_json_bytes(changed.model_dump(mode="json"))
    new_pointer = plan.photo_result.model_copy(
        update={"sha256": content_sha256(changed.model_dump(mode="json"))}
    )
    records[new_pointer] = raw
    value = plan.model_dump(mode="json")
    value["photo_result"] = new_pointer.model_dump(mode="json")
    changed_plan = LocalImageSdxlIpStyleComparisonPlan.model_validate(_seal(value))
    with pytest.raises(ValueError, match="STATUS_OR_CHRONOLOGY"):
        owner.resolve_sdxl_ip_style_selection_metadata(object(), changed_plan)
    assert events == ["PARENTS"]


@pytest.mark.parametrize("owner_name", ["photo", "style"])
def test_source_owner_cannot_return_another_command(monkeypatch, owner_name):
    plan, _, events, photo, style = _owner_fixture(monkeypatch)
    metadata = photo if owner_name == "photo" else style
    metadata.command = metadata.command.model_copy(update={"source_commit": "f" * 40})
    with pytest.raises(ValueError, match="OWNER_COMMAND_MISMATCH"):
        owner.resolve_sdxl_ip_style_selection_metadata(object(), plan)
    assert events[-1] == "TRAIN_OWNER"


@pytest.mark.parametrize("boundary", ["result", "train", "selector"])
def test_supported_owner_failures_propagate_no_retry(monkeypatch, boundary):
    plan, _, events, *_ = _owner_fixture(monkeypatch)
    target = {
        "result": "validate_photo_style_result",
        "train": "resolve_sdxl_native_lora_sources",
        "selector": "select_sdxl_ip_style_sources",
    }[boundary]

    def denied(*_a, **_k):
        raise ValueError("existing owner rejected provenance")

    monkeypatch.setattr(owner, target, denied)
    with pytest.raises(ValueError, match="rejected provenance"):
        owner.resolve_sdxl_ip_style_selection_metadata(object(), plan)
    assert events.count("PARENTS") == 1
    assert events[-1] != "SELECTOR"
