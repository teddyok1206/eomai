"""Actual index assembly and exact receipt closure, no model, authority or storage."""

from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.registered_public_solution_registry import (
    PublicSolutionIndexRegistrationResultV4,
    RegisterPublicSolutionIndexCommandV4,
)
from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow
from eom_catalog_service.public_solution_index_assembly import (
    assemble_public_solution_index,
    assemble_registered_public_solution_index,
    assemble_registered_public_solution_index_revision,
)
from eom_identifiers import content_sha256, sha256_bytes
from eom_workflow.local_embedding_workflow_receipt_v3 import (
    parse_local_embedding_workflow_receipt_v3,
)
from eom_workflow.local_embedding_workflow_receipt_v4 import (
    ResolvedNativeIndexCoverageV4,
    parse_local_embedding_step_output_v4,
    parse_local_embedding_workflow_receipt_v4,
    validate_local_embedding_step_output_v4,
    validate_local_embedding_workflow_receipt_v4,
)
from eom_workflow.schemas import load_local_embedding_admission_schema
from jsonschema import Draft202012Validator

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.local_embedding_admission_fixtures import member
from tests.unit.test_local_embedding_source_plan_v4 import entries
from tests.unit.test_public_solution_index_assembly import setup
from tests.unit.test_registered_public_solution_index import registered_index_entry, successor
from tests.unit.test_registered_public_solution_ownership import ownership_case


@lru_cache(maxsize=1)
def completion_case():
    case = ownership_case()
    row = RegisteredEmbeddingRow(case.job_request.encoding, case.completed.receipt.row_ref)
    values = dict(
        available_rows=(row,),
        shards=((case.shard, case.result.shard),),
        index_id="embeddingindex_" + "4" * 32,
        index_revision_id="embeddingindexrev_" + "4" * 32,
        previous_manifest=None,
        created_at=NOW,
    )
    assembled = assemble_registered_public_solution_index(
        entries(case.plan),
        namespace=case.plan.namespace,
        space=case.plan.space,
        **values,
    )
    from_plan = assemble_registered_public_solution_index_revision(case.plan, **values)
    assert assembled == from_plan
    index = assembled.index
    previous = case.original["receipt"]
    pointer = member(
        "index.json",
        "eom://schemas/knowledge/embedding-index-manifest/4.0",
        index.model_dump(mode="json"),
        "c",
    )
    command = RegisterPublicSolutionIndexCommandV4.model_validate(
        seal(
            previous.registration_command.model_dump(mode="json")
            | {
                "schema_version": "embedding-registry-registration-command/4.0",
                "namespace": case.plan.namespace,
                "graph_snapshot": case.plan.graph_snapshot,
                "policy_revision_id": case.plan.access_policy_revision_id,
                "policy_sha256": case.plan.access_policy_sha256,
                "corpus_id": case.plan.corpus_id,
                "index_id": index.index_id,
                "index_revision_id": index.index_revision_id,
                "index_manifest": pointer,
                "index_sha256": index.index_sha256,
                "source_set_sha256": case.plan.source_set_sha256,
                "binding_set_sha256": content_sha256(
                    [binding.binding_sha256 for binding in index.bindings]
                ),
                "eligible_source_count": len(case.plan.sources),
                "binding_count": len(index.bindings),
            },
            "request_sha256",
        )
    )
    result = PublicSolutionIndexRegistrationResultV4.model_validate(
        seal(
            previous.registration_result.model_dump(mode="json")
            | {
                "schema_version": "embedding-registry-registration-result/4.0",
                **{
                    field: getattr(command, field)
                    for field in (
                        "operation_key",
                        "request_sha256",
                        "index_id",
                        "index_revision_id",
                        "index_manifest",
                        "index_sha256",
                    )
                },
                "current_index_revision_id": command.index_revision_id,
            },
            "result_sha256",
        )
    )
    receipt = parse_local_embedding_workflow_receipt_v4(
        seal(
            previous.model_dump(mode="json")
            | {
                "schema_version": "local-embedding-workflow-receipt/4.0",
                "workflow_request_sha256": case.request.request_sha256,
                "source_plan": case.request.source_plan,
                "source_plan_sha256": case.plan.plan_sha256,
                "launch_association_sha256": case.association.association_sha256,
                "registration_command": command.model_dump(mode="json"),
                "registration_result": result.model_dump(mode="json"),
            },
            "receipt_sha256",
        )
    )
    output = parse_local_embedding_step_output_v4(
        seal(
            case.original["output"].model_dump(mode="json")
            | {
                "schema_version": "local-embedding-step-output/4.0",
                "receipt_schema": "eom://schemas/workflow/local-embedding-workflow-receipt/4.0",
                "receipt": member(
                    "receipt.json",
                    "eom://schemas/workflow/local-embedding-workflow-receipt/4.0",
                    receipt.model_dump(mode="json"),
                    "e",
                ),
                "receipt_sha256": receipt.receipt_sha256,
            },
            "output_sha256",
        )
    )
    coverage = ResolvedNativeIndexCoverageV4(index, case.plan.sources)
    return SimpleNamespace(**locals())


def validate(value, receipt=None, **context):
    actual = value.receipt if receipt is None else receipt
    return validate_local_embedding_workflow_receipt_v4(
        actual,
        value.case.request,
        value.case.plan,
        value.case.original["policy"],
        workflow_id=value.case.intent.workflow_id,
        step_run_id=value.case.intent.step_run_id,
        receipt_owner_job_id=actual.receipt_owner_job_id,
        launch_association=value.case.association,
        owned_input=value.case.owned_input,
        index_coverage=context.get("coverage", value.coverage),
    )


def test_entry_and_plan_assembly_produce_same_three_bindings_one_row_and_exact_receipt4():
    value = completion_case()
    assert len(value.index.bindings) == 3 and value.index.shards == (value.case.shard,)
    assert len({binding.encoding for binding in value.index.bindings}) == 1
    assert validate(value) == value.receipt
    assert validate_local_embedding_step_output_v4(value.output, value.receipt) == value.output
    assert value.output.execution_result_schema == "incremental-embedding-result@1.0"
    with pytest.raises(ValueError):
        parse_local_embedding_workflow_receipt_v3(value.receipt.model_dump(mode="json"))


def test_actual_successor_assembly_preserves_parent3_bindings_and_shared_rows_verbatim():
    _parent, expected, pointer, shards = successor()
    old_entries, rows, _shards, namespace, space = setup(device="CUDA")
    selected = tuple(
        sorted(
            (*old_entries, registered_index_entry()),
            key=lambda entry: entry.source.item_revision_id,
        )
    )
    kwargs = dict(
        available_rows=rows,
        shards=shards,
        namespace=namespace,
        space=space,
        index_id=expected.index_id,
        index_revision_id=expected.index_revision_id,
        previous_manifest=pointer,
        created_at=expected.created_at,
    )
    assert assemble_registered_public_solution_index(selected, **kwargs).index == expected
    with pytest.raises(ValueError, match="FAMILY_MISMATCH"):
        assemble_public_solution_index(selected, **kwargs)


@pytest.mark.parametrize(
    "fault",
    [
        "source_plan",
        "request",
        "association",
        "producer",
        "observation_time",
        "command3",
        "float",
        "extra",
    ],
)
def test_receipt4_rejects_forged_history_even_when_outer_hash_is_recomputed(fault):
    value = completion_case()
    body = value.receipt.model_dump(mode="json")
    if fault == "source_plan":
        body["source_plan"]["schema_ref"] = "eom://schemas/workflow/local-embedding-source-plan/3.0"
    elif fault == "request":
        body["workflow_request_sha256"] = "sha256:" + "0" * 64
    elif fault == "association":
        body["launch_association_sha256"] = "sha256:" + "0" * 64
    elif fault == "producer":
        body["native_launch_job_id"] = "job_" + "f" * 32
    elif fault == "observation_time":
        body["registration_observed_at"] = "2000-01-01T00:00:00Z"
    elif fault == "command3":
        body["registration_command"] = value.case.original[
            "receipt"
        ].registration_command.model_dump(mode="json")
    elif fault == "float":
        body["attempt"] = 1.0
    else:
        body["authorized"] = True
    with pytest.raises(ValueError):
        parsed = parse_local_embedding_workflow_receipt_v4(
            body if fault == "float" else seal(body, "receipt_sha256")
        )
        validate(value, parsed)


def test_receipt_requires_exact_full_population_and_carrier_raw_hash():
    value = completion_case()
    with pytest.raises(ValueError):
        validate(
            value,
            coverage=replace(value.coverage, eligible_sources=value.coverage.eligible_sources[:-1]),
        )
    body = value.output.model_dump(mode="json")
    body["receipt"]["sha256"] = "sha256:" + "0" * 64
    output = parse_local_embedding_step_output_v4(seal(body, "output_sha256"))
    with pytest.raises(ValueError):
        validate_local_embedding_step_output_v4(output, value.receipt)


def test_all_cached_rows_can_complete_without_claiming_a_new_numeric_launch():
    value = completion_case()
    receipt = parse_local_embedding_workflow_receipt_v4(
        seal(
            value.receipt.model_dump(mode="json")
            | {
                "native_launch_job_id": None,
                "launch_association_sha256": None,
            },
            "receipt_sha256",
        )
    )
    assert (
        validate_local_embedding_workflow_receipt_v4(
            receipt,
            value.case.request,
            value.case.plan,
            value.case.original["policy"],
            workflow_id=value.case.intent.workflow_id,
            step_run_id=value.case.intent.step_run_id,
            receipt_owner_job_id=receipt.receipt_owner_job_id,
            launch_association=None,
            owned_input=None,
            index_coverage=value.coverage,
        )
        == receipt
    )


def test_completion4_schema_packaged_closed_2020_12_and_predecessor3_unchanged():
    root = Path(__file__).resolve().parents[2]
    name = "local-embedding-completion-v4.schema.json"
    assert (root / "schemas/workflow" / name).read_bytes() == (
        root / "packages/workflow/eom_workflow/resources" / name
    ).read_bytes()
    schema = load_local_embedding_admission_schema("registered-public-completion")
    Draft202012Validator.check_schema(schema)
    assert all(value["additionalProperties"] is False for value in schema["$defs"].values())
    assert sha256_bytes(
        (root / "schemas/workflow/local-embedding-completion-v3.schema.json").read_bytes()
    ) == ("sha256:63cb7949b7c71ec0cc6f83bd95463a31269a789f5b4f0642cdbf6f7c24c2627b")
