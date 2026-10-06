"""Pure matched-matrix proposal tests; no source dereference, worker or quality admission."""

from __future__ import annotations

import ast
import copy
import hashlib
from pathlib import Path

import pytest
from eom_image_contracts import (
    SDXL_IP_STYLE_PLAN_SCHEMA_REF,
    LocalImageSdxlIpStyleComparisonPlan,
    SdxlIpStyleComparisonBudget,
    SdxlIpStyleModelPointer,
    SdxlIpStyleRouting,
    content_json_bytes,
    content_sha256,
    parse_sdxl_ip_style_comparison_plan,
    sdxl_ip_style_model_pointer,
    validate_contract,
)
from eom_image_contracts.models import ImageEvaluationArtifactMember
from eom_image_contracts.sdxl_ip_style import LocalImageSdxlIpStyleModelManifest
from eom_image_contracts.validation import SCHEMA_FILES, SCHEMA_SHA256, load_schema
from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_comparison_command import load_sdxl_comparison_command
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.test_sdxl_ip_style_manifest import _value as _model_value


def _seal(value):
    value = copy.deepcopy(value)
    value.pop("plan_id", None)
    value.pop("plan_sha256", None)
    value["plan_id"] = "imgsdxlipstyleplan_" + content_sha256(value)[7:39]
    value["plan_sha256"] = content_sha256(value)
    return value


def _pin(index, family):
    return dict(
        artifact_id="artifact_" + f"{index:032x}",
        artifact_revision_id="rev_" + f"{index:032x}",
        member_path="manifests/" + family.split("/")[0] + ".json",
        schema_ref="eom://schemas/image-provider/local-image-" + family,
        media_type="application/json",
        sha256="sha256:" + f"{index:064x}",
    )


def _value():
    return _seal(
        dict(
            schema_version="local-image-sdxl-ip-style-comparison-plan/1.0",
            source_commit="a" * 40,
            created_at="2026-10-06T15:00:00Z",
            purpose="EVALUATION_ONLY_MATCHED_STYLE_REFERENCE",
            dispatch_policy="PREPARATION_ONLY_NOT_A_WORKER_COMMAND",
            activation_policy="FORBIDDEN",
            comparison_policy="ONLY_IP_SCALE_0_VS_1_SAME_LORA_AND_STRUCTURE",
            photo_command=_pin(1, "sdxl-photo-style-command/1.5"),
            photo_result=_pin(2, "sdxl-photo-style-result/1.5"),
            style_training_command=_pin(3, "sdxl-native-lora-command/1.3"),
            style_model=sdxl_ip_style_model_pointer(
                LocalImageSdxlIpStyleModelManifest.model_validate(_model_value())
            ).model_dump(mode="json"),
            routing=SdxlIpStyleRouting().model_dump(mode="json"),
            cases=[
                dict(
                    case_id="imgsdxlcase_" + f"{i:032x}",
                    conditioning_sha256="sha256:" + f"{i:064x}",
                    initialization_rgb_sha256="sha256:" + "4" * 64,
                    style_sample_id="imgsourcecrop_" + f"{i:032x}",
                    style_rgb_sha256="sha256:" + f"{i + 3:064x}",
                )
                for i in (1, 2)
            ],
            budget=SdxlIpStyleComparisonBudget(
                maximum_duration_ms=120000, maximum_peak_gpu_memory_bytes=16 * 1024**3
            ).model_dump(mode="json"),
        )
    )


def _validate(value):
    validate_contract("sdxl-ip-style-comparison-plan", value)
    return LocalImageSdxlIpStyleComparisonPlan.model_validate(value)


def _document(raw):
    return ImageEvaluationArtifactMember(
        **dict(
            artifact_id="artifact_" + "f" * 32,
            artifact_revision_id="rev_" + "f" * 32,
            member_path="manifests/sdxl-ip-style-comparison-plan.json",
            schema_ref=SDXL_IP_STYLE_PLAN_SCHEMA_REF,
            media_type="application/json",
            sha256="sha256:" + hashlib.sha256(raw).hexdigest(),
        )
    )


def test_exact_proposal_is_small_frozen_and_does_not_claim_execution_authority():
    plan = _validate(_value())
    raw = content_json_bytes(plan.model_dump(mode="json"))
    assert len(raw) < 4096
    assert parse_sdxl_ip_style_comparison_plan(_document(raw), raw) == plan
    assert plan.dispatch_policy == "PREPARATION_ONLY_NOT_A_WORKER_COMMAND"
    assert plan.budget.maximum_outputs == 2 * len(plan.cases) == 4
    assert (plan.routing.off_scale, plan.routing.on_scale) == (0.0, 1.0)
    assert plan.plan_id != plan.style_model.model_id
    assert isinstance(plan.cases, tuple)
    with pytest.raises(ValueError):
        plan.routing.on_scale = 0.5


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "local-image-sdxl-ip-style-comparison-plan/2.0"),
        ("created_at", "2026-10-06T15:00:00"),
        ("created_at", "2026-10-07T00:00:00+09:00"),
        ("source_commit", "main"),
        ("purpose", "PRODUCTION"),
        ("dispatch_policy", "WORKER_COMMAND"),
        ("activation_policy", "ALLOWED"),
        ("comparison_policy", "BASE_VS_LORA"),
        ("seed", 42),
        ("prompt_en", "changed prompt"),
        ("lora_strength", 0.2),
        ("initialization", "CONSTANT_WHITE"),
        ("control", "NEW_MASK"),
        ("authorization", "APPROVED"),
        ("quality", "PASS"),
    ],
)
def test_proposal_cannot_override_source_factors_or_invent_acceptance(field, value):
    data = _value()
    data[field] = value
    with pytest.raises((ValueError, SchemaError)):
        _validate(_seal(data))


@pytest.mark.parametrize(
    "field,value",
    [
        ("off_scale", 0.1),
        ("on_scale", 0.9),
        ("other_ip_scales", 1.0),
        ("policy", "ALL_ATTENTION_BLOCKS"),
        ("feature_subtraction", True),
        ("self_attention_policy", "REPLACE"),
        ("embedding_reuse", "SEPARATE_BY_ARM"),
    ],
)
def test_only_style_route_and_scale_recipe_is_accepted(field, value):
    data = _value()
    data["routing"][field] = value
    with pytest.raises((ValueError, SchemaError)):
        _validate(_seal(data))


@pytest.mark.parametrize(
    "field,value",
    [
        ("maximum_outputs", 5),
        ("maximum_dispatches", 2),
        ("automatic_retry", True),
        ("maximum_duration_ms", 0),
        ("maximum_duration_ms", 600001),
        ("maximum_peak_gpu_memory_bytes", 16 * 1024**3 + 1),
        ("maximum_duration_ms", True),
    ],
)
def test_proposed_budget_is_closed_not_an_approval_or_sweep(field, value):
    data = _value()
    data["budget"][field] = value
    with pytest.raises((ValueError, SchemaError)):
        _validate(_seal(data))


@pytest.mark.parametrize("field", ["photo_command", "photo_result", "style_training_command"])
@pytest.mark.parametrize("fault", ["version", "media", "member", "unsafe", "revision"])
def test_exact_parent_family_and_pointer_shape_required(field, fault):
    data = _value()
    pointer = data[field]
    if fault == "version":
        pointer["schema_ref"] = pointer["schema_ref"].rsplit("/", 1)[0] + "/1.7"
    elif fault == "media":
        pointer["media_type"] = "text/plain"
    elif fault == "member":
        pointer["member_path"] = "manifests/another.json"
    elif fault == "unsafe":
        pointer["member_path"] = "../secret"
    else:
        pointer["artifact_revision_id"] = "latest"
    with pytest.raises((ValueError, SchemaError)):
        _validate(_seal(data))


@pytest.mark.parametrize(
    "fault", ["one", "three", "duplicate", "order", "bad-id", "style-conflict"]
)
def test_exact_ordered_two_case_matrix(fault):
    data = _value()
    if fault == "one":
        data["cases"].pop()
    elif fault == "three":
        data["cases"].append(copy.deepcopy(data["cases"][0]))
    elif fault == "duplicate":
        data["cases"][1] = copy.deepcopy(data["cases"][0])
    elif fault == "order":
        data["cases"].reverse()
    elif fault == "bad-id":
        data["cases"][0]["style_sample_id"] = "unknown"
    else:
        data["cases"][1]["style_sample_id"] = data["cases"][0]["style_sample_id"]
    with pytest.raises((ValueError, SchemaError)):
        _validate(_seal(data))


def test_two_objects_may_share_one_identical_pinned_style_input():
    data = _value()
    for field in ("style_sample_id", "style_rgb_sha256"):
        data["cases"][1][field] = data["cases"][0][field]
    assert len(_validate(_seal(data)).cases) == 2


@pytest.mark.parametrize("field", ["plan_id", "plan_sha256"])
def test_identity_and_content_hash_mismatch_rejected(field):
    data = _value()
    data[field] = "imgsdxlipstyleplan_" + "0" * 32 if field == "plan_id" else "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        _validate(data)


@pytest.mark.parametrize(
    "field", ["photo_command", "photo_result", "style_training_command", "style_model"]
)
def test_changed_pinned_input_is_a_new_plan_not_a_latest_lookup(field):
    first = _validate(_value())
    data = first.model_dump(mode="json")
    data[field]["manifest_sha256" if field == "style_model" else "sha256"] = "sha256:" + "0" * 64
    second = _validate(_seal(data))
    assert first.plan_id != second.plan_id and first.plan_sha256 != second.plan_sha256
    assert second.dispatch_policy == "PREPARATION_ONLY_NOT_A_WORKER_COMMAND"


@pytest.mark.parametrize(
    "fault", ["hash", "noncanonical", "member", "schema", "media", "bound", "unsafe"]
)
def test_document_resolution_rejects_unpinned_or_noncanonical_value(fault):
    raw = content_json_bytes(_validate(_value()).model_dump(mode="json"))
    pointer = _document(raw)
    if fault == "hash":
        pointer = pointer.model_copy(update={"sha256": "sha256:" + "0" * 64})
    elif fault == "noncanonical":
        raw += b"\n"
        pointer = _document(raw)
    elif fault == "bound":
        raw += b" " * 65536
        pointer = _document(raw)
    else:
        key, value = {
            "member": ("member_path", "other.json"),
            "schema": ("schema_ref", "unknown/1.0"),
            "media": ("media_type", "text/plain"),
            "unsafe": ("member_path", "../../escape"),
        }[fault]
        pointer = pointer.model_copy(update={key: value})
    with pytest.raises(ValueError):
        parse_sdxl_ip_style_comparison_plan(pointer, raw)


def test_preparation_plan_is_not_admitted_by_existing_worker_loader(tmp_path):
    (tmp_path / "command.json").write_bytes(content_json_bytes(_value()))
    (tmp_path / "command.json").chmod(0o600)
    with pytest.raises(ProviderError) as error:
        load_sdxl_comparison_command(tmp_path, tmp_path / "command.json")
    assert error.value.code == "SDXL_PROBE_INPUT_INVALID"


def test_schema_source_package_and_generated_model_parity():
    schema = load_schema("sdxl-ip-style-comparison-plan")
    generated = LocalImageSdxlIpStyleComparisonPlan.model_json_schema()
    generated.update(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": SDXL_IP_STYLE_PLAN_SCHEMA_REF,
        }
    )
    assert schema == generated
    Draft202012Validator.check_schema(schema)
    name = SCHEMA_FILES["sdxl-ip-style-comparison-plan"]
    source = Path("schemas/image-provider") / name
    package = Path("packages/image_contracts/eom_image_contracts/schemas") / name
    assert source.read_bytes() == package.read_bytes()
    assert (
        "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
        == SCHEMA_SHA256["sdxl-ip-style-comparison-plan"]
    )


def test_module_keeps_contract_dependency_direction_and_python311_syntax():
    import eom_image_contracts.sdxl_ip_style_comparison as module

    tree = ast.parse(Path(module.__file__).read_text(), feature_version=(3, 11))
    modules = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        a.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for a in node.names
    }
    assert not modules.intersection(
        {
            "torch",
            "diffusers",
            "eom_image_provider",
            "eom_orchestrator",
            "sqlalchemy",
            "PIL",
            "subprocess",
        }
    )
    assert SdxlIpStyleModelPointer.__module__ == "eom_image_contracts.sdxl_ip_style"
