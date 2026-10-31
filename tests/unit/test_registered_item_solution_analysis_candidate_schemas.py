"""Protocol-first candidates; no producer/Workflow activation is asserted here."""

from __future__ import annotations

import copy
import runpy
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.validation import catalog_schema_registry
from eom_identifiers import content_sha256
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError
from referencing import Resource

from tests.unit.test_past_exam_solution_analysis_contracts import (
    _request_value,
    _role_input_value,
    _role_result_value,
)

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "scripts/contracts/generate_registered_item_solution_analysis_v11_schema.py"


@pytest.fixture(scope="module")
def candidate() -> dict[str, Any]:
    functions = runpy.run_path(str(GENERATOR))
    schemas = (
        functions["build_contracts"]()
        | functions["build_role_contracts"]()
        | functions["build_control_contracts"]()
    )
    registry = catalog_schema_registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
    )
    return {"schemas": schemas, "registry": registry}


def validator(candidate: dict[str, Any], name: str) -> Draft202012Validator:
    return Draft202012Validator(
        candidate["schemas"][name],
        registry=candidate["registry"],
        format_checker=FormatChecker(),
    )


def request_value() -> dict[str, Any]:
    value = copy.deepcopy(_request_value())
    original = value["source"]
    source_fields = (
        "source_kind",
        "source_class",
        "item_id",
        "item_revision_id",
        "lifecycle_state",
        "artifact_member",
    )
    value["source"] = {key: original[key] for key in source_fields} | {
        "source_class": "APPROVED_ITEM"
    }
    value["schema_version"] = "knowledge-analysis-request/11.0"
    value["accepted_result_schema_ref"] = "eom://schemas/knowledge/knowledge-analysis-result/11.0"
    base = value["base_analysis"]
    base["accepted_result_artifact"]["schema_ref"] = (
        "eom://schemas/knowledge/knowledge-analysis-result/2.0"
    )
    base["accepted_result_artifact"]["artifact_id"] = "artifact_" + "f" * 32
    base["accepted_result_artifact"]["artifact_revision_id"] = "rev_" + "f" * 32
    base["proposal_receipt"]["schema_ref"] = (
        "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/1.0"
    )
    base["base_members"].pop("page_image_observations")
    base["base_counts"].pop("page_image_observations")
    for field, version in (("nodes", "2.0"), ("edges", "2.0"), ("unresolved_ambiguities", "2.0")):
        descriptor = base["base_members"][field]
        descriptor["schema_ref"] = descriptor["schema_ref"].rsplit("/", 1)[0] + "/" + version
    base["proposal_content_set_sha256"] = content_sha256(
        [
            {
                key: member[key]
                for key in ("member_path", "sha256", "bytes", "schema_ref", "media_type")
            }
            for member in sorted(
                base["base_members"].values(), key=lambda item: item["member_path"]
            )
        ]
    )
    value["request_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "request_sha256"}
    )
    return value


def test_candidates_are_valid_202012_and_canonical_resource_copies_match(candidate):
    for name, schema in candidate["schemas"].items():
        Draft202012Validator.check_schema(schema)
        area = (
            "knowledge"
            if name.startswith("knowledge-analysis-")
            and "input" not in name
            and "proposal-result" not in name
            else "workflow/roles"
        )
        if name.startswith("resolved-execution-plan"):
            area = "workflow/control-plane"
        canonical = ROOT / "schemas" / area / name
        package = (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge" / name
            if area == "knowledge"
            else ROOT
            / "packages/workflow/eom_workflow/resources"
            / area.removeprefix("workflow/")
            / name
        )
        assert canonical.read_bytes() == package.read_bytes()


def test_registered_base_does_not_fabricate_past_exam_occurrences_or_page_observations(candidate):
    value = request_value()
    validator(candidate, "knowledge-analysis-request-v11.schema.json").validate(value)
    assert value["source"]["source_class"] == "APPROVED_ITEM"
    assert "page_inputs" not in value["source"]
    assert "page_image_observations" not in value["base_analysis"]["base_members"]
    assert value["worker_proposal_schema_ref"].endswith("/8.0")
    assert value["requested_outputs"] == ["SOLUTION_REPORT"]


@pytest.mark.parametrize(
    "change",
    [
        "past_source",
        "old_result_pin",
        "old_receipt_pin",
        "extra_page_member",
        "unknown_field",
        "review_output",
    ],
)
def test_registered_request_remains_closed_on_source_pins_and_full_report_output(candidate, change):
    value = request_value()
    if change == "past_source":
        value["source"]["source_class"] = "PAST_EXAM"
    elif change == "old_result_pin":
        value["base_analysis"]["accepted_result_artifact"]["schema_ref"] = (
            "eom://schemas/knowledge/knowledge-analysis-result/9.0"
        )
    elif change == "old_receipt_pin":
        value["base_analysis"]["proposal_receipt"]["schema_ref"] = (
            "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/8.0"
        )
    elif change == "extra_page_member":
        value["base_analysis"]["base_members"]["page_image_observations"] = copy.deepcopy(
            value["base_analysis"]["base_members"]["nodes"]
        )
    elif change == "unknown_field":
        value["authority"] = "ADMIN"
    else:
        value["requested_outputs"] = ["REVIEW_CONCLUSIONS"]
    with pytest.raises(ValidationError):
        validator(candidate, "knowledge-analysis-request-v11.schema.json").validate(value)


def test_worker_candidate_uses_the_same_report_value_but_a_distinct_admitted_protocol(candidate):
    worker_input = copy.deepcopy(_role_input_value())
    worker_input["protocol_version"] = "workflow-role/1.35.0"
    worker_input["request"]["analysis_request"] = request_value()
    validator(candidate, "knowledge-analysis-input-v11.schema.json").validate(worker_input)
    worker_result = copy.deepcopy(_role_result_value())
    worker_result["protocol_version"] = "workflow-role/1.35.0"
    validator(candidate, "knowledge-analysis-proposal-result-v11.schema.json").validate(
        worker_result
    )
    worker_input["protocol_version"] = "workflow-role/1.21.0"
    with pytest.raises(ValidationError):
        validator(candidate, "knowledge-analysis-input-v11.schema.json").validate(worker_input)


def test_plan_candidate_does_not_retain_a_hidden_past_exam_source_requirement(candidate):
    plan = candidate["schemas"]["resolved-execution-plan-v29.schema.json"]
    source_validator = Draft202012Validator(
        plan["properties"]["item_source"], registry=candidate["registry"]
    )
    source_validator.validate(request_value()["source"])
    assert plan["properties"]["base_analysis"] == {
        "$ref": "eom://schemas/knowledge/knowledge-analysis-solution-types/2.0#/$defs/baseAnalysis"
    }
