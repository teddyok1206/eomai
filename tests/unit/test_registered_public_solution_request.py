"""Metadata-only source-plan4 request pinning, without model or runtime activation."""

from pathlib import Path

import pytest
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryLookup,
    ResolvedEmbeddingLookup,
)
from eom_catalog_service.local_embedding_source_plan_v3 import build_local_embedding_source_plan_v4
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.local_embedding_request_v3 import (
    parse_local_embedding_workflow_request_v3,
)
from eom_workflow.local_embedding_request_v4 import (
    local_embedding_request_service_v4,
    parse_local_embedding_workflow_request_v4,
    validate_local_embedding_request_references_v4,
)
from eom_workflow.local_embedding_source_plan_v4 import parse_local_embedding_source_plan_v4
from eom_workflow.schemas import load_local_embedding_admission_schema
from jsonschema import Draft202012Validator

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_admission_fixtures import member
from tests.unit.test_local_embedding_source_plan_v4 import entries, plan_value
from tests.unit.test_public_solution_native_carriers import public_native_fixture


def request_case():
    original = public_native_fixture(device="CUDA")
    template = parse_local_embedding_source_plan_v4(plan_value())
    space = original["request"].space
    namespace = PublicSolutionIndexNamespace.model_validate(
        template.namespace.model_dump(mode="json") | {"space_sha256": space.space_sha256}
    )
    query = EmbeddingRegistryLookup(
        template.corpus_id,
        namespace,
        template.graph_snapshot,
        template.access_policy_revision_id,
        template.access_policy_sha256,
    )
    staged = entries(template)
    captured = ResolvedEmbeddingLookup(
        template.corpus_id,
        space,
        template.recipe,
        template.sources,
        staged,
        False,
        tuple((entry.source.item_revision_id, entry.base_analysis_run_id) for entry in staged),
    )
    plan = build_local_embedding_source_plan_v4(
        query,
        captured,
        target_revision_ids=tuple(source.item_revision_id for source in template.sources),
    )
    body = original["request"].model_dump(mode="json")
    body.update(
        schema_version="local-embedding-workflow-request/4.0",
        **{
            field: getattr(plan, field)
            for field in (
                "corpus_id",
                "graph_snapshot",
                "access_policy_revision_id",
                "access_policy_sha256",
                "namespace",
                "space",
            )
        },
        source_plan=member(
            "source-plan.json",
            "eom://schemas/workflow/local-embedding-source-plan/4.0",
            plan.model_dump(mode="json"),
            "4",
        ),
        source_plan_sha256=plan.plan_sha256,
    )
    request = parse_local_embedding_workflow_request_v4(seal(body, "request_sha256"))
    return original, request, plan


def test_request4_pins_full_report_plan4_but_preserves_index2_numeric_policy():
    original, request, plan = request_case()
    validate_local_embedding_request_references_v4(request, plan, original["policy"])
    assert local_embedding_request_service_v4(request) == original["policy"].service
    assert request.workflow_definition_version == "2.0.0"
    assert request.workflow_definition_sha256 == original["request"].workflow_definition_sha256
    assert request.runtime_bundle == original["request"].runtime_bundle
    assert request.resource_profile == original["request"].resource_profile
    assert request.source_plan.sha256 == sha256_bytes(
        canonical_json_bytes(plan.model_dump(mode="json"))
    )
    assert parse_local_embedding_workflow_request_v4(request.model_dump(mode="json")) == request
    with pytest.raises(ValueError):
        parse_local_embedding_workflow_request_v3(request.model_dump(mode="json"))
    with pytest.raises(ValueError):
        parse_local_embedding_workflow_request_v4(original["request"].model_dump(mode="json"))


@pytest.mark.parametrize(
    "fault",
    [
        "plan_schema",
        "plan_member",
        "plan_raw_hash",
        "plan_semantic_hash",
        "service",
        "definition",
        "extra",
        "float",
    ],
)
def test_exact_request4_rejects_wrong_pins_or_raw_coercion(fault):
    original, request, plan = request_case()
    body = request.model_dump(mode="json")
    if fault == "plan_schema":
        body["source_plan"]["schema_ref"] = "eom://schemas/workflow/local-embedding-source-plan/3.0"
    elif fault == "plan_member":
        body["source_plan"]["member_path"] = "other.json"
    elif fault == "plan_raw_hash":
        body["source_plan"]["sha256"] = "sha256:" + "0" * 64
    elif fault == "plan_semantic_hash":
        body["source_plan_sha256"] = "sha256:" + "0" * 64
    elif fault == "service":
        body["actor_context"]["service_id"] = "localindexservice_" + "f" * 32
    elif fault == "definition":
        body["workflow_definition_version"] = "4.0.0"
    elif fault == "extra":
        body["operator_permissions"] = ["ADMIN"]
    else:
        body["resource_profile"]["batch_size"] = 1.0
    with pytest.raises(ValueError):
        checked = parse_local_embedding_workflow_request_v4(
            body if fault == "float" else seal(body, "request_sha256")
        )
        validate_local_embedding_request_references_v4(checked, plan, original["policy"])


def test_request4_schema_is_closed_2020_12_packaged_and_does_not_rewrite_request3():
    root = Path(__file__).resolve().parents[2]
    name = "local-embedding-workflow-request-v4.schema.json"
    assert (root / "schemas/workflow" / name).read_bytes() == (
        root / "packages/workflow/eom_workflow/resources" / name
    ).read_bytes()
    schema = load_local_embedding_admission_schema("registered-public-request")
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    old = root / "schemas/workflow/local-embedding-workflow-request-v3.schema.json"
    assert sha256_bytes(old.read_bytes()) == (
        "sha256:81f38bd9a5996ca02e5463d6fffe89d01d61c9972d50abb049ebbdbcd4304e4f"
    )
