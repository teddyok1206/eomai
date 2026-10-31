"""Real ownership/numeric validators, synthetic values, no model or database."""

from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_identifiers import sha256_bytes
from eom_workflow.local_embedding_encoding_dispatch import (
    build_supported_owned_incremental_embedding_input,
    embedding_ownership_version,
    parse_supported_embedding_message,
    validate_supported_embedding_association,
    validate_supported_embedding_completions,
)
from eom_workflow.local_embedding_encoding_job import (
    EmbeddingEncodingJobRequest,
    LocalEmbeddingOwnedJob,
)
from eom_workflow.local_embedding_encoding_ownership_v3 import parse_embedding_encoding_ownership_v3
from eom_workflow.local_embedding_encoding_ownership_v4 import (
    EmbeddingEncodingCompletedEventV4,
    LocalEmbeddingLaunchIntentV4,
    parse_embedding_encoding_ownership_v4,
    parse_local_embedding_launch_association_v4,
)
from eom_workflow.schemas import load_local_embedding_admission_schema
from jsonschema import Draft202012Validator

from tests.unit.inference_transfer_embedding_fixtures import embedding_result, seal
from tests.unit.local_embedding_admission_fixtures import member
from tests.unit.test_local_embedding_source_plan_v4 import entries
from tests.unit.test_registered_public_solution_request import request_case


@lru_cache(maxsize=1)
def ownership_case():
    original, request, plan = request_case()
    intent = LocalEmbeddingLaunchIntentV4.model_validate(
        seal(
            original["association"].intent.model_dump(mode="json")
            | {
                "workflow_request_sha256": request.request_sha256,
                "source_plan": request.source_plan,
                "source_plan_sha256": plan.plan_sha256,
            },
            "intent_sha256",
        )
    )
    old_job = original["association"].owned_jobs[0]
    job_request = EmbeddingEncodingJobRequest.model_validate(
        seal(
            old_job.request.model_dump(mode="json") | {"encoding": plan.demands[0].encoding},
            "request_sha256",
        )
    )
    job = LocalEmbeddingOwnedJob.model_validate(
        {
            "request": job_request,
            "job_reference": old_job.job_reference.model_dump(mode="json")
            | {
                "request_sha256": job_request.request_sha256,
            },
        }
    )
    owned_input = build_supported_owned_incremental_embedding_input(
        plan,
        entries(plan),
        (job,),
        native_launch_job_id=intent.native_launch_job_id,
        resources=request.resource_profile,
    )
    association = parse_local_embedding_launch_association_v4(
        seal(
            original["association"].model_dump(mode="json")
            | {
                "schema_version": "embedding-encoding-ownership/4.0",
                "intent": intent,
                "owned_jobs": (job,),
                "owned_input": member(
                    "input.json",
                    "eom://schemas/knowledge/incremental-embedding-input/1.0",
                    owned_input.model_dump(mode="json"),
                    "7",
                ),
                "owned_input_request_sha256": owned_input.request_sha256,
                "owned_input_set_sha256": owned_input.input_set_sha256,
            },
            "association_sha256",
        )
    )
    result = embedding_result(owned_input)
    shard = member(
        "shard.json",
        "eom://schemas/knowledge/embedding-vector-shard/1.0",
        result.shard.model_dump(mode="json"),
    )
    receipt = original["events"][0].receipt.model_dump(mode="json")
    receipt.update(
        result_manifest=member(
            "result.json",
            "eom://schemas/knowledge/incremental-embedding-result/1.0",
            result.model_dump(mode="json"),
        ),
        result_sha256=result.result_sha256,
        shard_manifest=shard,
        shard_sha256=result.shard.shard_sha256,
        row_ref={
            "shard_manifest": shard,
            "row_index": 0,
            "encoding_sha256": job_request.encoding.encoding_sha256,
        },
    )
    receipt["binary_member"]["sha256"] = result.shard.binary.sha256
    completed = parse_embedding_encoding_ownership_v4(
        seal(
            {
                "schema_version": "embedding-encoding-ownership/4.0",
                "record_type": "COMPLETED",
                "owned_job": job,
                "intent": intent,
                "launch_association_sha256": association.association_sha256,
                "receipt": seal(receipt, "receipt_sha256"),
            },
            "event_sha256",
        )
    )
    assert isinstance(completed, EmbeddingEncodingCompletedEventV4)
    return SimpleNamespace(**locals())


def test_all_three_report_provenances_own_one_unchanged_numeric_job_and_exact_completion():
    case = ownership_case()
    assert len(case.plan.demands) == 3 and len(case.owned_input.rows) == 1
    assert {entry.evidence.kind for entry in entries(case.plan)} == {
        "ACCEPTED_SOLUTION_ANALYSIS",
        "REGISTERED_CREATIVE_SOURCE_REPORT",
        "ACCEPTED_REGISTERED_SOLUTION_ANALYSIS",
    }
    assert case.owned_input.rows[0].text == entries(case.plan)[0].public_solution.text
    assert case.owned_input.schema_version == "incremental-embedding-input/1.0"
    assert case.result.schema_version == "incremental-embedding-result/1.0"
    assert case.job.request.schema_version == "embedding-encoding-job/1.0"
    assert embedding_ownership_version(case.intent) == "embedding-encoding-ownership/4.0"
    assert parse_supported_embedding_message(case.association) == case.association
    validate_supported_embedding_association(
        case.association,
        case.plan,
        case.owned_input,
        case.request.resource_profile,
        case.request.request_sha256,
    )
    validate_supported_embedding_completions(
        (case.completed,), case.association, case.owned_input, case.result
    )
    for body, hash_field in (
        (
            {
                "schema_version": "embedding-encoding-ownership/4.0",
                "record_type": "ATTACHED",
                "owned_job": case.job,
                "intent": case.intent,
            },
            "event_sha256",
        ),
        (
            {
                "schema_version": "embedding-encoding-ownership/4.0",
                "record_type": "READ_RESULT",
                "owned_job": case.job,
                "owner_intent": case.intent,
                "status": "COMPLETED",
                "completion": case.completed,
            },
            "read_sha256",
        ),
    ):
        value = parse_embedding_encoding_ownership_v4(seal(body, hash_field))
        assert parse_supported_embedding_message(value) == value
    with pytest.raises(ValueError):
        parse_embedding_encoding_ownership_v3(case.association.model_dump(mode="json"))


@pytest.mark.parametrize(
    "fault", ["old_family", "plan_schema", "plan_hash", "request_hash", "float", "extra"]
)
def test_owned_association_rejects_foreign_or_forged_context_even_after_rehash(fault):
    case = ownership_case()
    body = case.association.model_dump(mode="json")
    if fault == "old_family":
        body["schema_version"] = "embedding-encoding-ownership/3.0"
    elif fault == "plan_schema":
        body["intent"]["source_plan"]["schema_ref"] = (
            "eom://schemas/workflow/local-embedding-source-plan/3.0"
        )
    elif fault == "plan_hash":
        body["intent"]["source_plan"]["sha256"] = "sha256:" + "0" * 64
    elif fault == "request_hash":
        body["intent"]["workflow_request_sha256"] = "sha256:" + "0" * 64
    elif fault == "float":
        body["intent"]["attempt"] = 1.0
    else:
        body["permissions"] = ["ADMIN"]
    if fault != "float":
        body["intent"] = seal(body["intent"], "intent_sha256")
        body = seal(body, "association_sha256")
    with pytest.raises(ValueError):
        checked = parse_local_embedding_launch_association_v4(body)
        validate_supported_embedding_association(
            checked,
            case.plan,
            case.owned_input,
            case.request.resource_profile,
            case.request.request_sha256,
        )


def test_completion_rejects_duplicate_receipts_or_wrong_physical_row():
    case = ownership_case()
    with pytest.raises(ValueError, match="exact owned set"):
        validate_supported_embedding_completions(
            (case.completed, case.completed), case.association, case.owned_input, case.result
        )
    body = case.completed.model_dump(mode="json")
    body["receipt"]["row_ref"]["row_index"] = 1
    body["receipt"] = seal(body["receipt"], "receipt_sha256")
    event = parse_embedding_encoding_ownership_v4(seal(body, "event_sha256"))
    assert isinstance(event, EmbeddingEncodingCompletedEventV4)
    with pytest.raises(ValueError):
        validate_supported_embedding_completions(
            (event,), case.association, case.owned_input, case.result
        )


def test_ownership_schema_is_closed_packaged_and_preserves_released_schema3():
    root = Path(__file__).resolve().parents[2]
    name = "embedding-encoding-ownership-v4.schema.json"
    assert (root / "schemas/workflow" / name).read_bytes() == (
        root / "packages/workflow/eom_workflow/resources" / name
    ).read_bytes()
    schema = load_local_embedding_admission_schema("registered-public-ownership")
    Draft202012Validator.check_schema(schema)
    assert all(part["additionalProperties"] is False for part in schema["$defs"].values())
    assert sha256_bytes(
        (root / "schemas/workflow/embedding-encoding-ownership-v3.schema.json").read_bytes()
    ) == ("sha256:d30a5355499c7576249ca46c147411b52ac11407f2115003f87b20fcaa4db465")
