"""Synthetic metadata closure is not installed-worker, pixel or quality acceptance."""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from eom_image_contracts.models import (
    ImageEvaluationArtifactMember,
    content_json_bytes,
    content_sha256,
    text_sha256,
)
from eom_image_contracts.photo_object_support import PhotoObjectSupportReview
from eom_image_contracts.sdxl_canny_comparison import SdxlCannyControlParameters
from eom_image_contracts.sdxl_photo_object_support_lineage import (
    PhotoObjectSupportParentDocuments,
    validate_photo_object_support_lineage,
)
from eom_image_contracts.sdxl_photo_object_support_plan import (
    PLAN_SCHEMA,
    LocalImageSdxlPhotoObjectSupportPlan,
    parse_photo_object_support_plan,
)
from eom_image_contracts.sdxl_photo_style import (
    LocalImageSdxlPhotoStyleBalancedExposurePlan,
    LocalImageSdxlPhotoStyleRetainedRegionPlan,
    parse_photo_style_plan_value,
    photo_style_region_reviews_sha256,
)
from eom_image_contracts.sdxl_photo_style_execution import (
    is_photo_style_command_schema,
    parse_photo_style_command,
    parse_photo_style_result,
)
from eom_image_contracts.validation import SCHEMA_FILES, SCHEMA_SHA256, validate_contract
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit import test_photo_object_support_review as reviews
from tests.unit import test_sdxl_photo_style as photos


def _raw(value):
    return content_json_bytes(value)


def _sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _pin(character, family, raw, version="1.5"):
    return ImageEvaluationArtifactMember(
        artifact_id="artifact_" + character * 32,
        artifact_revision_id="rev_" + character * 32,
        member_path="manifests/" + family + ".json",
        schema_ref="eom://schemas/image-provider/local-image-" + family + "/" + version,
        media_type="application/json",
        sha256=_sha(raw),
    )


def _result(plan):
    traces, outputs = [], []
    for entry in plan.cases:
        case = entry.case
        traces.append(
            dict(
                case_id=case.case_id,
                source_sha256=case.reference_image.sha256,
                conditioning_sha256="sha256:" + "2" * 64,
                initialization_rgb_sha256=(
                    "sha256:2a1305062f642d1db1cc642ac56bd73710d20fa355a02cd84f31a90d23d4e106"
                ),
                width_px=832,
                height_px=512,
            )
        )
        for arm in ("BASE", "LORA"):
            filename = f"{case.case_id}-{plan.seed:010d}.png"
            outputs.append(
                dict(
                    arm=arm,
                    case_id=case.case_id,
                    seed=plan.seed,
                    reference_sha256=case.reference_image.sha256,
                    conditioning_sha256=traces[-1]["conditioning_sha256"],
                    member_path=f"outputs/{arm.lower()}/final/{filename}",
                    raw_member_path=f"outputs/{arm.lower()}/raw/{filename}",
                    sha256="sha256:" + "4" * 64,
                    raw_sha256="sha256:" + "5" * 64,
                    size_bytes=1,
                    raw_size_bytes=1,
                    width_px=800,
                    height_px=500,
                    duration_ms=100,
                    peak_gpu_memory_bytes=1000,
                )
            )
    value = dict(
        schema_version="local-image-sdxl-photo-style-result/1.5",
        run_id="imgsdxlvalcmprun_" + "a" * 32,
        command_sha256="sha256:" + "b" * 64,
        plan_sha256=plan.plan_sha256,
        configuration_command_sha256="sha256:" + "c" * 64,
        native_evaluation_command_sha256="sha256:" + "d" * 64,
        native_adapter_manifest_sha256="sha256:" + "e" * 64,
        case_relation="LICENSED_PHOTO_REFERENCES_NOT_CORPUS_HOLDOUT",
        native_fit_policy="NATIVE_FIT_800X500_CENTER_832X512_OPENCV_CANNY/1.0",
        initialization=plan.initialization.model_dump(mode="json"),
        control=plan.control.model_dump(mode="json"),
        region_reviews_sha256=photo_style_region_reviews_sha256(plan),
        quality_acceptance="NOT_REVIEWED",
        activation_policy="FORBIDDEN",
        training_steps=0,
        holdout_binary_reads=0,
        status="SUCCEEDED",
        error_code=None,
        runtime=dict(
            provider_version="eom-local-image-provider/1.0",
            python_version="synthetic",
            torch_version="synthetic",
            diffusers_version="synthetic",
            transformers_version="synthetic",
            cuda_version="synthetic",
            gpu_name="synthetic-not-a-runtime-probe",
            compute_capability="12.0",
            peak_gpu_memory_bytes=1000,
        ),
        inputs=traces,
        outputs=sorted(outputs, key=lambda row: (row["arm"], row["case_id"], row["seed"])),
        started_at="2026-10-05T18:01:00Z",
        completed_at="2026-10-05T18:02:00Z",
        duration_ms=60000,
    )
    return parse_photo_style_result({**value, "result_sha256": content_sha256(value)})


def _fixture(*, multiple=False):
    sources = tuple(photos._source(i)[0] for i in range(1, 3 if multiple else 2))
    value = photos._plan(sources).model_dump(mode="json")
    value.update(
        schema_version="local-image-sdxl-photo-style-plan/1.5",
        initialization=dict(
            policy="CONSTANT_WHITE_RGB_832X512_FULL_DENOISE/1.0",
            denoising_strength=1.0,
            scheduler_steps=30,
            effective_denoising_steps=30,
            pillow_version="11.3.0",
        ),
        control=SdxlCannyControlParameters().model_dump(mode="json"),
        region_review_evidence=dict(
            artifact_id="artifact_" + "a" * 32,
            artifact_revision_id="rev_" + "b" * 32,
            schema_ref="eom://schemas/operations/plain-text-log/1.0",
            member_path="reports/own-review.md",
            media_type="text/plain",
            sha256="sha256:" + "c" * 64,
        ),
    )
    value["configuration_anchor"]["schema_ref"] = (
        "eom://schemas/image-provider/local-image-sdxl-canny-reference-command/1.3"
    )
    value["region_reviews"] = [
        dict(
            case_id=entry["case"]["case_id"],
            reference_sha256=entry["case"]["reference_image"]["sha256"],
            coordinate_system="NORMALIZED_PHOTO_SOURCE_PIXELS_800X504/1.0",
            source_width_px=800,
            source_height_px=504,
            retained_box=dict(left=100, top=50, right=700, bottom=450),
            protected_boxes=[dict(left=150, top=100, right=650, bottom=400)],
            context_policy="SUBJECT_MORPHOLOGY_ONLY_IRRELEVANT_BACKDROP",
            reviewed_at="2026-10-05T17:59:00Z",
            reviewed_by="synthetic-own-input",
            observation="Synthetic reviewed region is not an actual pixel or quality assertion.",
        )
        for entry in value["cases"]
    ]
    parent = LocalImageSdxlPhotoStyleBalancedExposurePlan.model_validate(photos._seal_plan(value))
    result = _result(parent)
    plan_raw, result_raw = (
        _raw(parent.model_dump(mode="json")),
        _raw(result.model_dump(mode="json")),
    )
    result_pin = _pin("8", "sdxl-photo-style-result", result_raw)
    review_value = reviews._value()
    entry = parent.cases[0]
    review_value["source"] = entry.case.reference_image.model_dump(mode="json")
    review_value["prior_control"].update(
        artifact_id=result_pin.artifact_id,
        artifact_revision_id=result_pin.artifact_revision_id,
        member_path="conditionings/" + entry.case.case_id + ".png",
    )
    review_raw = _raw(reviews._seal(review_value))
    parents = dict(
        review=reviews._pointer(review_raw).model_dump(mode="json"),
        prior_plan=_pin("7", "sdxl-photo-style-plan", plan_raw).model_dump(mode="json"),
        prior_result=result_pin.model_dump(mode="json"),
        baseline_plan=_pin("7", "sdxl-photo-style-plan", plan_raw).model_dump(mode="json"),
        baseline_result=result_pin.model_dump(mode="json"),
    )
    value = parent.model_dump(mode="json", exclude={"region_reviews", "region_review_evidence"})
    value.update(
        schema_version="local-image-sdxl-photo-style-plan/1.6",
        created_at="2026-10-06T08:00:00Z",
        cases=[entry.model_dump(mode="json")],
        support_parents=parents,
        comparison_policy="CHANGE_OBJECT_SUPPORT_ONLY_REUSE_PINNED_BASELINE",
    )
    value["budget"]["maximum_outputs"] = 2
    plan = LocalImageSdxlPhotoObjectSupportPlan.model_validate(photos._seal_plan(value))
    return plan, PhotoObjectSupportParentDocuments(
        review_raw, plan_raw, result_raw, plan_raw, result_raw
    )


def _plan_pointer(plan):
    return _pin("9", "sdxl-photo-style-plan", _raw(plan.model_dump(mode="json")), "1.6")


def test_preparation_roundtrip_boundaries_and_selected_existing_pair():
    plan, docs = _fixture(multiple=True)
    raw = _raw(plan.model_dump(mode="json"))
    validate_contract("sdxl-photo-style-plan-v7", plan.model_dump(mode="json"))
    assert parse_photo_object_support_plan(_plan_pointer(plan), raw) == plan
    closure = validate_photo_object_support_lineage(plan, docs)
    assert len(closure.baseline_plan.cases) == 2
    assert tuple(row.arm for row in closure.baseline_outputs) == ("BASE", "LORA")
    assert all(row.case_id == plan.cases[0].case.case_id for row in closure.baseline_outputs)
    assert not isinstance(plan, LocalImageSdxlPhotoStyleRetainedRegionPlan)
    assert plan.budget.maximum_outputs == 2 and not plan.budget.automatic_retry
    assert isinstance(closure.review, PhotoObjectSupportReview)
    assert "region_reviews" not in plan.model_dump()


@pytest.mark.parametrize("family", ["plan", "command", "result"])
def test_execution_codecs_never_guess_undeclared_successor(family):
    plan, _ = _fixture()
    assert not is_photo_style_command_schema("local-image-sdxl-photo-style-command/1.7")
    parser = {
        "plan": parse_photo_style_plan_value,
        "command": parse_photo_style_command,
        "result": parse_photo_style_result,
    }[family]
    value = plan.model_dump(mode="json")
    value["schema_version"] = "local-image-sdxl-photo-style-" + family + "/1.7"
    with pytest.raises(ValueError, match="unsupported photo"):
        parser(value)


@pytest.mark.parametrize(
    "path,replacement",
    [
        (("budget", "maximum_outputs"), 12),
        (("budget", "maximum_dispatches"), 2),
        (("budget", "automatic_retry"), True),
        (("support_parents", "review", "media_type"), "text/plain"),
        (("support_parents", "prior_plan", "schema_ref"), PLAN_SCHEMA),
        (("support_parents", "baseline_result", "member_path"), "manifests/latest.json"),
        (("support_parents", "baseline_result", "sha256"), "sha256:" + "f" * 64),
        (("configuration_anchor", "schema_ref"), "eom://schemas/image-provider/wrong/1.3"),
        (("control", "guidance_end"), 0.5),
        (("comparison_policy",), "CHANGE_PROMPT_AND_CONTROL"),
        (("activation_policy",), "ALLOWED"),
        (("region_reviews",), []),
    ],
)
def test_invalid_preparation_refused_after_reseal(path, replacement):
    plan, _ = _fixture()
    value = plan.model_dump(mode="json")
    target = value
    for name in path[:-1]:
        target = target[name]
    target[path[-1]] = replacement
    value = photos._seal_plan(value)
    raw = _raw(value)
    with pytest.raises((SchemaError, ValidationError)):
        parse_photo_object_support_plan(_pin("9", "sdxl-photo-style-plan", raw, "1.6"), raw)


@pytest.mark.parametrize(
    "field", ["review", "prior_plan", "prior_result", "baseline_plan", "baseline_result"]
)
def test_parent_bytes_changed_missing_or_stale_refused(field):
    plan, docs = _fixture()
    for replacement in (b"", b"{}", getattr(docs, field) + b" ", b"x" * (256 * 1024 + 1)):
        with pytest.raises(ValueError, match="BOUND_HASH"):
            validate_photo_object_support_lineage(plan, replace(docs, **{field: replacement}))


@pytest.mark.parametrize(
    "field,path,replacement",
    [
        ("review", ("source", "artifact_revision_id"), "rev_" + "f" * 32),
        ("review", ("prior_control", "artifact_revision_id"), "rev_" + "f" * 32),
        ("review", ("prior_control", "sha256"), "sha256:" + "f" * 64),
        (
            "review",
            ("prior_control", "member_path"),
            "conditionings/imgsdxlcase_" + "f" * 32 + ".png",
        ),
        ("prior_result", ("native_adapter_manifest_sha256",), "sha256:" + "f" * 64),
        ("prior_result", ("native_evaluation_command_sha256",), "sha256:" + "f" * 64),
        ("prior_result", ("configuration_command_sha256",), "sha256:" + "f" * 64),
        ("prior_result", ("plan_sha256",), "sha256:" + "f" * 64),
        ("prior_result", ("region_reviews_sha256",), "sha256:" + "f" * 64),
        ("baseline_result", ("outputs",), []),
        ("baseline_result", ("duration_ms",), 600001),
        ("baseline_result", ("completed_at",), "2026-10-07T08:00:00Z"),
        ("prior_result", ("completed_at",), "2026-10-07T08:00:00Z"),
    ],
)
def test_resealed_but_crossed_parent_lineage_refused(field, path, replacement):
    plan, docs = _fixture()
    value = json.loads(getattr(docs, field))
    target = value
    for name in path[:-1]:
        target = target[name]
    target[path[-1]] = replacement
    if field == "review":
        value = reviews._seal(value)
    else:
        value.pop("result_sha256")
        value["result_sha256"] = content_sha256(value)
    raw = _raw(value)
    body = plan.model_dump(mode="json")
    body["support_parents"][field]["sha256"] = _sha(raw)
    body["support_parents"][field]["artifact_revision_id"] = "rev_" + "d" * 32
    changed = LocalImageSdxlPhotoObjectSupportPlan.model_validate(photos._seal_plan(body))
    with pytest.raises(ValueError, match="OBJECT_SUPPORT"):
        validate_photo_object_support_lineage(changed, replace(docs, **{field: raw}))


def test_canonical_schema_copies_pins_and_dependency_direction():
    repo = Path(__file__).resolve().parents[2]
    name = SCHEMA_FILES["sdxl-photo-style-plan-v7"]
    raw = (repo / "schemas/image-provider" / name).read_bytes()
    assert (
        raw == (repo / "packages/image_contracts/eom_image_contracts/schemas" / name).read_bytes()
    )
    assert _sha(raw) == SCHEMA_SHA256["sdxl-photo-style-plan-v7"]
    schema = json.loads(raw)
    assert schema["$id"] == PLAN_SCHEMA and schema["$schema"].endswith("2020-12/schema")
    from eom_image_contracts.sdxl_photo_object_support_plan import (
        LocalImageSdxlPhotoObjectSupportPlan,
    )

    generated = LocalImageSdxlPhotoObjectSupportPlan.model_json_schema()
    generated.update({key: schema[key] for key in ("$id", "$schema")})
    assert generated == schema
    for filename in ("sdxl_photo_object_support_plan.py", "sdxl_photo_object_support_lineage.py"):
        tree = ast.parse(
            (repo / "packages/image_contracts/eom_image_contracts" / filename).read_text()
        )
        imports = {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        } | {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert not imports - {
            "__future__",
            "hashlib",
            "json",
            "dataclasses",
            "collections",
            "typing",
            "pydantic",
            "eom_image_contracts",
        }


def test_plan_bound_hash_kind_noncanonical_and_frozen_guards():
    plan, _ = _fixture()
    raw = _raw(plan.model_dump(mode="json"))
    pin = _plan_pointer(plan)
    for candidate in (b"", raw + b" ", b"x" * (256 * 1024 + 1)):
        with pytest.raises(ValueError, match="BOUND_HASH"):
            parse_photo_object_support_plan(pin, candidate)
    noncanonical = json.dumps(json.loads(raw), indent=2).encode()
    with pytest.raises(ValueError, match="NONCANONICAL"):
        parse_photo_object_support_plan(
            pin.model_copy(update={"sha256": _sha(noncanonical)}), noncanonical
        )
    with pytest.raises(ValueError, match="POINTER_KIND"):
        parse_photo_object_support_plan(pin.model_copy(update={"media_type": "text/plain"}), raw)
    with pytest.raises(ValidationError):
        plan.seed = 2


def _changed_case(case):
    value = dict(case)
    value.pop("case_id")
    value.pop("staged_member_path")
    value["prompt_en"] = "A different style cue used only by the control provenance parent."
    value["prompt_sha256"] = text_sha256(value["prompt_en"])
    value["case_id"] = "imgsdxlcase_" + content_sha256(value)[7:39]
    value["staged_member_path"] = "inputs/" + value["case_id"] + ".png"
    return value


def test_control_provenance_may_have_different_prompt_but_baseline_stays_exact():
    plan, docs = _fixture()
    prior = json.loads(docs.prior_plan)
    prior["cases"][0]["case"] = _changed_case(prior["cases"][0]["case"])
    prior["region_reviews"][0]["case_id"] = prior["cases"][0]["case"]["case_id"]
    parsed = LocalImageSdxlPhotoStyleBalancedExposurePlan.model_validate(photos._seal_plan(prior))
    prior_raw = _raw(parsed.model_dump(mode="json"))
    result_raw = _raw(_result(parsed).model_dump(mode="json"))
    review = json.loads(docs.review)
    review["prior_control"].update(
        artifact_revision_id="rev_" + "d" * 32,
        member_path="conditionings/" + parsed.cases[0].case.case_id + ".png",
    )
    review_raw = _raw(reviews._seal(review))
    body = plan.model_dump(mode="json")
    for key, raw in (
        ("prior_plan", prior_raw),
        ("prior_result", result_raw),
        ("review", review_raw),
    ):
        body["support_parents"][key].update(
            artifact_revision_id="rev_" + "d" * 32,
            sha256=_sha(raw),
        )
    successor = LocalImageSdxlPhotoObjectSupportPlan.model_validate(photos._seal_plan(body))
    closure = validate_photo_object_support_lineage(
        successor, replace(docs, review=review_raw, prior_plan=prior_raw, prior_result=result_raw)
    )
    assert closure.prior_plan.cases[0].case.prompt_en != successor.cases[0].case.prompt_en
    assert closure.baseline_plan.cases[0].case == successor.cases[0].case
    assert (
        closure.prior_result.inputs[0].conditioning_sha256
        == closure.baseline_result.inputs[0].conditioning_sha256
    )


@pytest.mark.parametrize("factor", ["prompt", "seed", "configuration", "source-review", "time"])
def test_successor_cannot_change_second_factor(factor):
    plan, docs = _fixture()
    body = plan.model_dump(mode="json")
    if factor == "prompt":
        body["cases"][0]["case"] = _changed_case(body["cases"][0]["case"])
    elif factor == "seed":
        body["seed"] += 1
        case = body["cases"][0]["case"]
        case.pop("case_id")
        case.pop("staged_member_path")
        case["seeds"] = [body["seed"]]
        case["case_id"] = "imgsdxlcase_" + content_sha256(case)[7:39]
        case["staged_member_path"] = "inputs/" + case["case_id"] + ".png"
    elif factor == "configuration":
        body["configuration_anchor"]["artifact_revision_id"] = "rev_" + "f" * 32
    elif factor == "source-review":
        body["cases"][0]["source_review"]["observation"] = (
            "A second source observation may not replace the pinned baseline entry."
        )
    else:
        body["created_at"] = "2026-10-06T06:00:00Z"
    successor = LocalImageSdxlPhotoObjectSupportPlan.model_validate(photos._seal_plan(body))
    with pytest.raises(ValueError, match="OBJECT_SUPPORT"):
        validate_photo_object_support_lineage(successor, docs)


def test_single_case_identity_and_semantic_hash_guards():
    plan, _ = _fixture()
    for field, replacement in (
        ("cases", plan.model_dump(mode="json")["cases"] * 2),
        ("cases", []),
        ("plan_id", "imgsdxlphotoplan_" + "f" * 32),
        ("plan_sha256", "sha256:" + "f" * 64),
    ):
        value = plan.model_dump(mode="json")
        value[field] = replacement
        raw = _raw(value)
        with pytest.raises((ValidationError, SchemaError)):
            parse_photo_object_support_plan(_pin("9", "sdxl-photo-style-plan", raw, "1.6"), raw)


@pytest.mark.parametrize(
    "field", ["prior_plan", "prior_result", "baseline_plan", "baseline_result"]
)
def test_rehashed_noncanonical_parent_refused(field):
    plan, docs = _fixture()
    raw = json.dumps(json.loads(getattr(docs, field)), indent=2).encode()
    body = plan.model_dump(mode="json")
    body["support_parents"][field].update(artifact_revision_id="rev_" + "d" * 32, sha256=_sha(raw))
    changed = LocalImageSdxlPhotoObjectSupportPlan.model_validate(photos._seal_plan(body))
    with pytest.raises(ValueError, match="CANONICAL"):
        validate_photo_object_support_lineage(changed, replace(docs, **{field: raw}))
