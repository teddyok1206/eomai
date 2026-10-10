from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.inference_transfer_experiment import (
    ExperimentAdmissionScope,
    InferenceTransferExperimentRequest,
    SuppliedGraphBaseline,
)
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_catalog_contracts.knowledge import ApprovedPastExamItemKnowledgeSourceV3
from eom_catalog_contracts.validation import load_schema, validate_contract
from eom_identifiers import content_sha256
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from tests.unit.inference_transfer_experiment_fixtures import entry, experiment_request
from tests.unit.inference_transfer_fixtures import sha


def rehashed(body: dict[str, Any]) -> dict[str, Any]:
    body.pop("request_sha256", None)
    return body | {"request_sha256": content_sha256(body)}


def test_schema_was_defined_before_behavior_and_package_mirror_is_exact() -> None:
    schema = load_schema("item-inference-transfer-experiment")
    Draft202012Validator.check_schema(schema)
    canonical = Path("schemas/knowledge/item-inference-transfer-experiment-v1.schema.json")
    mirror = Path(
        "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge/item-inference-transfer-experiment-v1.schema.json"
    )
    assert canonical.read_bytes() == mirror.read_bytes()
    assert json.loads(canonical.read_bytes()) == schema
    validate_contract(
        "item-inference-transfer-experiment", experiment_request().model_dump(mode="json")
    )


@pytest.mark.parametrize("source_class", ["PAST_EXAM", "APPROVED_ITEM"])
def test_approved_item_sources_are_exactly_closed_to_profile(source_class: str) -> None:
    value = experiment_request(entry("a", source_class=source_class), entry("b"))
    validate_contract("item-inference-transfer-experiment", value.model_dump(mode="json"))
    assert value.scope.data_provenance == "TEST_ONLY_SYNTHETIC"
    assert value.scope.producer_admission == "SYNTHETIC_NON_AUTHORITATIVE"


@pytest.mark.parametrize(
    "mutation", ["hash", "source", "content", "metadata", "graph", "query", "scope", "admission"]
)
def test_forged_or_inconsistent_request_closure_is_rejected(mutation: str) -> None:
    body = experiment_request().model_dump(mode="json")
    if mutation == "hash":
        body["request_sha256"] = sha("f")
    elif mutation == "source":
        body["scope"]["population_sources"][0]["artifact_member"]["sha256"] = sha("f")
        body["scope"]["population_sha256"] = content_sha256(body["scope"]["population_sources"])
    elif mutation == "content":
        body["entries"][0]["content"]["original_source"]["sha256"] = sha("f")
    elif mutation == "metadata":
        # Accepted result hash is deliberately not the solution-report member hash.
        body["entries"][0]["metadata"][0]["source_sha256"] = sha("6")
    elif mutation == "graph":
        body["scope"]["graph_snapshot"]["graph_snapshot_revision_id"] = "graphrev_" + "f" * 32
    elif mutation == "query":
        body["queries"][0]["profile_sha256"] = sha("f")
    elif mutation == "scope":
        body["scope"]["policy_revision_id"] = "latest"
    else:
        body["scope"]["producer_admission"] = "CATALOG_AUTHORIZED_SNAPSHOT"
    if mutation != "hash":
        body = rehashed(body)
    with pytest.raises(ValidationError):
        InferenceTransferExperimentRequest.model_validate(body)


@pytest.mark.parametrize("key", ["EXAM_NAME", "ITEM_ID", "FILENAME"])
def test_metadata_cannot_embed_exam_filename_or_internal_identity(key: str) -> None:
    body = experiment_request().model_dump(mode="json")
    body["entries"][0]["metadata"][0]["key"] = key
    with pytest.raises(ValidationError):
        InferenceTransferExperimentRequest.model_validate(rehashed(body))


def test_baseline_hash_binds_ordered_candidates_and_is_not_original_artifact_hash() -> None:
    value = experiment_request()
    body = {
        "query": value.queries[0].model_dump(mode="json"),
        "command_sha256": sha("1"),
        "provenance": "SUPPORTED_GRAPH_LEXICAL_SUPPLIED_BY_PRODUCER",
        "ordered_candidates": [
            InferenceTransferProfilePointer.from_profile(e.profile).model_dump(mode="json")
            for e in value.entries[1:]
        ],
    }
    parsed = SuppliedGraphBaseline.model_validate(body | {"result_sha256": content_sha256(body)})
    changed = parsed.model_dump(mode="json")
    changed["ordered_candidates"].reverse()
    with pytest.raises(ValidationError, match="result_sha256"):
        SuppliedGraphBaseline.model_validate(changed)


def test_past_exam_population_cannot_claim_approved_generated_item() -> None:
    body = experiment_request(
        entry("a", source_class="APPROVED_ITEM"), entry("b")
    ).scope.model_dump(mode="json")
    body["population_scope"] = "OCCURRENCE_BACKED_PAST_EXAM"
    with pytest.raises(ValidationError, match="past-exam scope"):
        ExperimentAdmissionScope.model_validate(body)


def test_content_intake_source_is_not_a_registered_item_source() -> None:
    body = experiment_request().model_dump(mode="json")
    body["scope"]["population_sources"][0]["source_kind"] = "CONTENT_INTAKE"
    with pytest.raises(ValidationError):
        InferenceTransferExperimentRequest.model_validate(rehashed(body))
    with pytest.raises(SchemaValidationError):
        validate_contract("item-inference-transfer-experiment", rehashed(body))


def test_full_v3_source_is_preserved_without_losing_admission_fields() -> None:
    value = experiment_request()
    body = value.model_dump(mode="json")
    source = body["scope"]["population_sources"][0]
    source["artifact_member"].update(
        materialized_path="source/item-content.json", logical_name="item-content.json"
    )
    profile_body = body["entries"][0]["profile"]
    profile_body["source_basis"]["source"]["artifact_member"] = source["artifact_member"]
    profile_body.pop("profile_sha256")
    profile_body["profile_sha256"] = content_sha256(profile_body)
    body["entries"][0]["content"]["original_source"] = source["artifact_member"]

    def pointer(member: str, schema: str, media: str = "application/json") -> dict[str, str]:
        return {
            "artifact_id": "artifact_" + "f" * 32,
            "artifact_revision_id": "rev_" + "f" * 32,
            "member_path": member,
            "sha256": sha("f"),
            "schema_ref": "eom://schemas/legacy-assessment/" + schema + "/1.0",
            "media_type": media,
        }

    source.update(
        {
            "extraction_acceptance_id": "itemacceptance_" + "f" * 32,
            "extraction_acceptance_sha256": sha("f"),
            "extraction_acceptance_artifact": pointer(
                "acceptance.json", "legacy-item-extraction-acceptance"
            ),
            "extraction_result_id": "itemextractresult_" + "f" * 32,
            "extraction_result_sha256": sha("f"),
            "extraction_result_artifact": pointer("result.json", "legacy-item-extraction-result"),
            "item_proposal_id": "itemproposal_" + "f" * 32,
            "item_number": 1,
            "bundle": {
                "assessment_source_bundle_id": "assessbundle_" + "f" * 32,
                "assessment_source_bundle_revision_id": "assessbundlerev_" + "f" * 32,
                "bundle_manifest_sha256": sha("f"),
            },
            "layout_observation": {
                "assessment_layout_observation_id": "assessmentlayout_" + "f" * 32,
                "artifact": pointer("layout.json", "assessment-layout-observation"),
                "workspace_relative_path": "source/layout-observation.json",
                "observation_sha256": sha("f"),
            },
            "page_inputs": [
                {
                    "page_input_id": "assessmentpage_" + "f" * 32,
                    "source_role": "PROBLEM_DOCUMENT",
                    "physical_page": 1,
                    "source": pointer("sources/problem.pdf", "pdf-source", "application/pdf"),
                    "image": pointer("pages/problem-000001.png", "page-image", "image/png"),
                    "workspace_relative_path": "source/pages/assessmentpage_" + "f" * 32 + ".png",
                    "width_px": 1200,
                    "height_px": 1800,
                }
            ],
            "page_image_count": 1,
        }
    )
    body["scope"]["population_sha256"] = content_sha256(body["scope"]["population_sources"])
    pins = [
        {
            "profile_id": e["profile"]["profile_id"],
            "profile_revision_id": e["profile"]["profile_revision_id"],
            "profile_sha256": e["profile"]["profile_sha256"],
            "schema_ref": "eom://schemas/knowledge/item-inference-transfer/1.0",
        }
        for e in body["entries"]
    ]
    body["scope"]["eligible_profile_set_sha256"] = content_sha256(pins)
    body["queries"][0] = pins[0]
    parsed = InferenceTransferExperimentRequest.model_validate(rehashed(body))
    assert isinstance(parsed.scope.population_sources[0], ApprovedPastExamItemKnowledgeSourceV3)
    assert parsed.scope.population_sources[0].extraction_acceptance_sha256 == sha("f")
    validate_contract("item-inference-transfer-experiment", parsed.model_dump(mode="json"))
