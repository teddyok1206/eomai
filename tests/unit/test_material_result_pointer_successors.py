"""Explicit receipt/lineage version dispatch; no source, workflow or DB writes."""

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts.material_item_lineage import (
    MATERIAL_ITEM_LINEAGE_REF,
    MATERIAL_ITEM_LINEAGE_V2_REF,
    MaterialItemLineage,
    MaterialItemLineageV2,
    parse_material_item_lineage,
)
from eom_catalog_contracts.material_learning import MaterialLearningRoleReceipt
from eom_catalog_contracts.material_learning_role_receipt import (
    MaterialLearningRoleReceiptV2,
    parse_material_learning_role_receipt,
)
from eom_catalog_contracts.validation import load_schema, validate_contract
from eom_identifiers import canonical_json_bytes, content_sha256
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
INPUT = "sha256:" + "a" * 64


def receipt(version=1, *, task_kind="EXTRACT_ITEM"):
    return dict(
        schema_version=f"material-learning-role-receipt/{version}.0",
        result_schema=f"material-learning-result@{version}.0",
        task_kind=task_kind,
        input_sha256=INPUT,
        result_sha256="sha256:" + "b" * 64,
    )


def lineage(version=1):
    value = dict(
        schema_version=f"material-learning-item-lineage/{version}.0",
        material_id="material_" + "1" * 32,
        material_revision_id="materialrev_" + "2" * 32,
        task_id="materialtask_" + "3" * 32,
        unit_key="materialunit_" + "4" * 32,
        selection=dict(
            schema_version="material-learning-authorization-request/1.0",
            operation="AUTHORIZE_MATERIAL_LEARNING_INPUT",
            workflow_id="workflow_" + "5" * 32,
            step_run_id="steprun_" + "6" * 32,
            plan_id="execplan_" + "7" * 32,
            plan_sha256="sha256:" + "8" * 64,
            input_sha256=INPUT,
        ),
        work_input=dict(
            artifact_id="artifact_" + "9" * 32,
            artifact_revision_id="rev_" + "a" * 32,
            member_path="material/work.json",
            schema_ref="eom://schemas/material-learning/extraction-work/1.0",
            media_type="application/json",
            sha256="sha256:" + "9" * 64,
            bytes=1024,
        ),
        role_result=dict(
            artifact_id="artifact_" + "b" * 32,
            artifact_revision_id="rev_" + "c" * 32,
            member_path="result.json",
            schema_ref=f"material-learning-result@{version}.0",
            media_type="application/json",
            sha256="sha256:" + "d" * 64,
        ),
        input_sha256=INPUT,
        result_sha256="sha256:" + "e" * 64,
        proposed_content_sha256="sha256:" + "f" * 64,
        registered_content_sha256="sha256:" + "0" * 64,
        source_answer_mode="EDITORIAL_SOURCE",
        warning_codes=[],
        registration_policy="PRESERVE_SOURCE_WITH_REVIEW_WARNINGS_V1",
        requested_by="operator_" + "1" * 32,
        created_at="2026-11-15T00:00:00Z",
    )
    return {**value, "lineage_sha256": content_sha256(value)}


def rehash(value):
    value["lineage_sha256"] = content_sha256(
        {key: child for key, child in value.items() if key != "lineage_sha256"}
    )
    return value


@pytest.mark.parametrize(
    "version,model", [(1, MaterialLearningRoleReceipt), (2, MaterialLearningRoleReceiptV2)]
)
@pytest.mark.parametrize("task_kind", ["DISCOVER", "EXTRACT_ITEM"])
def test_receipt_versions_replay_with_the_same_five_small_identity_fields(
    version, model, task_kind
):
    value = receipt(version, task_kind=task_kind)
    parsed = parse_material_learning_role_receipt(value)
    assert isinstance(parsed, model)
    assert parsed.model_dump(mode="json") == value
    assert parse_material_learning_role_receipt(parsed) == parsed
    assert len(canonical_json_bytes(parsed.model_dump(mode="json"))) < 512
    assert set(type(parsed).model_fields) == set(MaterialLearningRoleReceipt.model_fields)


@pytest.mark.parametrize("version,model", [(1, MaterialItemLineage), (2, MaterialItemLineageV2)])
def test_lineage_versions_preserve_all_old_values_and_typed_pointer_identity(version, model):
    value = lineage(version)
    parsed = parse_material_item_lineage(value)
    assert isinstance(parsed, model)
    assert parsed.model_dump(mode="json") == value
    assert parse_material_item_lineage(parsed) == parsed
    assert len(canonical_json_bytes(parsed.model_dump(mode="json"))) < 8000
    assert set(type(parsed).model_fields) == set(MaterialItemLineage.model_fields)
    # These hashes have distinct meanings: Work/role Artifact bytes vs inner data.
    assert parsed.work_input.sha256 != parsed.input_sha256
    assert parsed.role_result.sha256 != parsed.result_sha256


@pytest.mark.parametrize(
    "parser,factory",
    [(parse_material_learning_role_receipt, receipt), (parse_material_item_lineage, lineage)],
)
@pytest.mark.parametrize("version", [None, "", "3.0", "latest"])
def test_missing_or_unknown_schema_never_falls_back_to_a_historical_family(
    parser, factory, version
):
    value = factory()
    if version is None:
        value.pop("schema_version")
    else:
        value["schema_version"] = version
    with pytest.raises(ValueError, match="SCHEMA_UNSUPPORTED"):
        parser(value)


@pytest.mark.parametrize(
    "parser", [parse_material_learning_role_receipt, parse_material_item_lineage]
)
@pytest.mark.parametrize("value", [None, [], b"{}", "{}"])
def test_dispatch_requires_decoded_json_object_not_an_implicit_format_fallback(parser, value):
    with pytest.raises(ValueError, match="DOCUMENT_INVALID"):
        parser(value)


@pytest.mark.parametrize("version", [1, 2])
def test_declared_receipt_version_with_the_other_result_schema_is_invalid(version):
    value = receipt(version)
    value["result_schema"] = f"material-learning-result@{3 - version}.0"
    with pytest.raises(ValidationError):
        parse_material_learning_role_receipt(value)
    with pytest.raises(SchemaError):
        validate_contract(f"material-learning-role-receipt-v{version}", value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_ref", "material-learning-result@1.0"),
        ("member_path", "other.json"),
        ("media_type", "text/plain"),
    ],
)
def test_lineage2_requires_exact_new_role_result_reference_in_model_and_schema(field, value):
    changed = lineage(2)
    changed["role_result"][field] = value
    rehash(changed)
    with pytest.raises((ValidationError, SchemaError)):
        parse_material_item_lineage(changed)
    with pytest.raises(SchemaError):
        validate_contract("material-learning-item-lineage-v2", changed)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_ref", "eom://schemas/material-learning/discovery-work/1.0"),
        ("member_path", "work.json"),
        ("media_type", "application/pdf"),
    ],
)
def test_lineage2_keeps_the_exact_historical_extraction_work_pointer(field, value):
    changed = lineage(2)
    changed["work_input"][field] = value
    rehash(changed)
    with pytest.raises((ValidationError, SchemaError)):
        parse_material_item_lineage(changed)


def test_old_lineage_does_not_accept_a_result2_pointer_and_new_does_not_accept_old_header():
    old = lineage()
    old["role_result"]["schema_ref"] = "material-learning-result@2.0"
    with pytest.raises(ValueError, match="LINEAGE_INVALID"):
        parse_material_item_lineage(rehash(old))
    with pytest.raises((ValidationError, SchemaError)):
        MaterialItemLineageV2.model_validate(lineage())
    with pytest.raises(ValidationError):
        MaterialLearningRoleReceipt.model_validate(receipt(2))


@pytest.mark.parametrize("change", ["role-revision", "inner-result", "content", "lineage"])
def test_lineage2_hash_binds_each_exact_pointer_and_inner_hash_without_reinterpreting_old(change):
    value = lineage(2)
    if change == "role-revision":
        value["role_result"]["artifact_revision_id"] = "rev_" + "f" * 32
    elif change == "inner-result":
        value["result_sha256"] = "sha256:" + "0" * 64
    elif change == "content":
        value["registered_content_sha256"] = "sha256:" + "f" * 64
    else:
        value["lineage_sha256"] = "sha256:" + "a" * 64
    with pytest.raises(ValueError, match="LINEAGE_INVALID"):
        parse_material_item_lineage(value)


def test_lineage2_matches_authorized_input_and_preserves_sorted_unique_warnings():
    value = lineage(2)
    value["selection"]["input_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(ValueError, match="LINEAGE_INVALID"):
        parse_material_item_lineage(rehash(value))
    for warnings in (["Z", "A"], ["A", "A"]):
        value = lineage(2)
        value["warning_codes"] = warnings
        with pytest.raises(ValueError, match="LINEAGE_INVALID"):
            parse_material_item_lineage(rehash(value))


def test_v2_full_role_result_hash_covers_coverage_without_adding_it_to_database_values():
    root_result = dict(
        output=dict(
            learning_result={"input_sha256": INPUT}, native_visual_coverage={"dispositions": []}
        )
    )
    value = receipt(2)
    value["result_sha256"] = content_sha256(root_result)
    parsed = parse_material_learning_role_receipt(value)
    changed = deepcopy(root_result)
    changed["output"]["native_visual_coverage"]["dispositions"] = ["changed"]
    assert content_sha256(changed) != parsed.result_sha256
    assert not {
        "output",
        "native_visual_coverage",
        "proposal",
        "body",
        "coverage_sha256",
    }.intersection(parsed.model_dump())
    value = lineage(2)
    assert not {
        "output",
        "native_visual_coverage",
        "proposal",
        "body",
        "coverage_sha256",
    }.intersection(value)


def test_new_schema_resources_are_canonical_and_leave_the_v1_schema_bytes_unchanged():
    import hashlib

    for key, filename, uri in (
        (
            "material-learning-role-receipt-v2",
            "material-learning-role-receipt-v2.schema.json",
            "eom://schemas/material-learning/role-receipt/2.0",
        ),
        (
            "material-learning-item-lineage-v2",
            "item-lineage-v2.schema.json",
            MATERIAL_ITEM_LINEAGE_V2_REF,
        ),
    ):
        canonical = ROOT / "schemas/material-learning" / filename
        resource = (
            ROOT
            / "packages/catalog_contracts/eom_catalog_contracts/resources/material-learning"
            / filename
        )
        assert canonical.read_bytes() == resource.read_bytes()
        assert load_schema(key)["$id"] == uri
    assert load_schema("material-learning-item-lineage-v1")["$id"] == MATERIAL_ITEM_LINEAGE_REF
    assert (
        hashlib.sha256(
            (
                ROOT / "schemas/material-learning/material-learning-role-receipt-v1.schema.json"
            ).read_bytes()
        ).hexdigest()
        == "627dcc7b6e21e82ca6b6e212577e7c391b60f765306d0c53dd603f33a45ca044"
    )


def test_new_values_are_immutable_and_reject_embedded_result_or_coverage_payloads():
    parsed = parse_material_learning_role_receipt(receipt(2))
    with pytest.raises(ValidationError, match="frozen_instance"):
        parsed.result_sha256 = INPUT
    for parser, value in (
        (parse_material_learning_role_receipt, receipt(2)),
        (parse_material_item_lineage, lineage(2)),
    ):
        with pytest.raises((ValidationError, SchemaError)):
            parser(dict(value, native_visual_coverage={}))
