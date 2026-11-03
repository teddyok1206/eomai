"""Native Office provenance changes no numerical text, vector identity or old schema bytes."""

from copy import deepcopy

import pytest
from eom_catalog_contracts.embedding_index_families import (
    parse_supported_embedding_entry,
    parse_supported_embedding_index,
    validate_supported_embedding_source_bindings,
)
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingEntry
from eom_catalog_contracts.registered_public_solution_embedding import (
    parse_public_solution_encoding_entry,
)
from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryLookup,
    ResolvedEmbeddingLookup,
)
from eom_catalog_service.local_embedding_source_plan_v3 import build_local_embedding_source_plan_v4
from eom_catalog_service.public_solution_encoding import prepare_public_solution_encoding
from eom_catalog_service.public_solution_index_assembly import (
    assemble_registered_public_solution_index_revision,
)
from eom_identifiers import content_sha256
from eom_workflow.local_embedding_source_plan_dispatch import (
    parse_supported_local_embedding_source_plan,
)
from eom_workflow.local_embedding_source_plan_v4 import (
    parse_local_embedding_source_plan_v4,
    validate_local_embedding_plan_entries_v4,
)
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from tests.unit.inference_transfer_embedding_fixtures import embedding_space
from tests.unit.test_local_embedding_source_plan_v4 import entries, plan_value
from tests.unit.test_public_solution_encoding import public_entry
from tests.unit.test_registered_public_solution_index import successor


def native_entry(original=None):
    value = (original or public_entry(creative=True)).model_dump(mode="json")
    value["schema_version"] = "public-solution-embedding-entry/3.0"
    value["evidence"]["role_result"]["schema_ref"] = "external-item-learning-result@3.0"
    value["entry_sha256"] = content_sha256({k: v for k, v in value.items() if k != "entry_sha256"})
    return PublicSolutionEmbeddingEntry.model_validate(value)


@pytest.mark.parametrize("device", ["CPU", "CUDA"])
@pytest.mark.parametrize("purpose", ["DOCUMENT", "QUERY"])
def test_native_report_keeps_the_exact_old_numerical_input(device, purpose):
    old, new = public_entry(creative=True), native_entry()
    space = embedding_space(device=device, purpose=purpose)
    previous = prepare_public_solution_encoding(
        old, space=space, storage_partition="public-solution"
    )
    current = prepare_public_solution_encoding(
        new, space=space, storage_partition="public-solution"
    )
    assert previous.input == current.input
    assert old.public_solution == new.public_solution and old.recipe == new.recipe
    assert old.entry_sha256 != new.entry_sha256
    assert parse_public_solution_encoding_entry(new) == parse_supported_embedding_entry(new) == new


def native_plan():
    previous = parse_local_embedding_source_plan_v4(plan_value())
    captured = tuple(
        native_entry(e) if e.evidence.kind == "REGISTERED_CREATIVE_SOURCE_REPORT" else e
        for e in entries(previous)
    )
    query = EmbeddingRegistryLookup(
        previous.corpus_id,
        previous.namespace,
        previous.graph_snapshot,
        previous.access_policy_revision_id,
        previous.access_policy_sha256,
    )
    resolved = ResolvedEmbeddingLookup(
        query.corpus_id,
        previous.space,
        previous.recipe,
        tuple(e.source for e in captured),
        captured,
        base_analysis_run_ids=tuple(
            (e.source.item_revision_id, e.base_analysis_run_id) for e in captured
        ),
    )
    current = build_local_embedding_source_plan_v4(
        query, resolved, target_revision_ids=tuple(e.source.item_revision_id for e in captured)
    )
    return previous, current, captured


def test_native_plan_index_reuses_past_creative_and_registered_rows_without_reencoding():
    previous, current, captured = native_plan()
    assert current.schema_version == "local-embedding-source-plan/5.0"
    assert current.encoding_set_sha256 == previous.encoding_set_sha256
    validate_local_embedding_plan_entries_v4(current, captured)
    assert parse_supported_local_embedding_source_plan(current) == current
    _parent, old_index, _pointer, shards = successor()
    rows = (RegisteredEmbeddingRow(old_index.bindings[0].encoding, old_index.bindings[0].row_ref),)
    built = assemble_registered_public_solution_index_revision(
        current,
        available_rows=rows,
        shards=shards,
        index_id=old_index.index_id,
        index_revision_id="embeddingindexrev_" + "7" * 32,
        previous_manifest=None,
        created_at=old_index.created_at,
    )
    assert built.index.schema_version == "embedding-index-manifest/5.0"
    assert len(built.index.bindings) == 3
    assert len({b.encoding for b in built.index.bindings}) == 1
    assert built.shards == shards
    assert parse_supported_embedding_index(built.index) == built.index
    validate_supported_embedding_source_bindings(built.index.bindings, captured, shards)
    native = next(b for b in built.index.bindings if b.schema_version.endswith("/5.0"))
    assert native.profile.schema_ref.endswith("/3.0")
    assert native.evidence.role_result.schema_ref == "external-item-learning-result@3.0"
    from eom_catalog_service.embedding_index_refresh_plan import (
        registered_public_index_membership_refresh_reason,
    )

    pointer = type(_pointer).model_validate(
        _pointer.model_dump(mode="json")
        | {
            "schema_ref": "eom://schemas/knowledge/embedding-index-manifest/5.0",
            "sha256": content_sha256(built.index.model_dump(mode="json")),
        }
    )
    # A second discovery must reuse the published head, not reject schema5 or
    # launch the same numerical work again. A real membership withdrawal differs.
    assert (
        registered_public_index_membership_refresh_reason(
            eligible_sources=tuple(e.source for e in captured),
            available_bindings=built.index.bindings[::-1],
            previous=(pointer, built.index),
        )
        is None
    )
    assert (
        registered_public_index_membership_refresh_reason(
            eligible_sources=tuple(e.source for e in captured),
            available_bindings=built.index.bindings[:1],
            previous=(pointer, built.index),
        )
        == "INDEX_MEMBERSHIP_CHANGED"
    )
    continued = assemble_registered_public_solution_index_revision(
        current,
        available_rows=rows,
        shards=shards,
        index_id=built.index.index_id,
        index_revision_id="embeddingindexrev_" + "8" * 32,
        previous_manifest=pointer,
        created_at=old_index.created_at,
    )
    assert continued.index.previous_manifest == pointer
    assert continued.index.bindings == built.index.bindings
    assert continued.shards == built.shards
    assert parse_supported_embedding_index(continued.index) == continued.index


@pytest.mark.parametrize(
    "fault", ["old_tag", "wrong_role", "past_evidence", "stale_hash", "unrecognized_role"]
)
def test_native_proof_cannot_be_disguised_as_a_predecessor_or_weakened(fault):
    value = deepcopy(native_entry().model_dump(mode="json"))
    if fault == "old_tag":
        value["schema_version"] = "public-solution-embedding-entry/1.0"
    elif fault == "wrong_role":
        value["evidence"]["role_result"]["schema_ref"] = "external-item-learning-result@2.0"
    elif fault == "past_evidence":
        value["evidence"] = public_entry().model_dump(mode="json")["evidence"]
    elif fault == "unrecognized_role":
        value["evidence"]["role_result"]["schema_ref"] = "external-item-learning-result@4.0"
    else:
        value["entry_sha256"] = "sha256:" + "0" * 64
    if fault != "stale_hash":
        value["entry_sha256"] = content_sha256(
            {k: v for k, v in value.items() if k != "entry_sha256"}
        )
    with pytest.raises((ValueError, JsonSchemaValidationError)):
        parse_public_solution_encoding_entry(value)


def test_actual_capture_keeps_native_role_proof_and_the_unchanged_inner_report(monkeypatch):
    from dataclasses import replace

    from tests.unit.test_public_solution_source_capture import capture_case, run

    value = capture_case(monkeypatch, creative=True)
    lineage = value.registered.report.lineage
    raw = lineage.model_dump(mode="json")
    raw["role_result"]["schema_ref"] = "external-item-learning-result@3.0"
    raw["lineage_sha256"] = content_sha256({k: v for k, v in raw.items() if k != "lineage_sha256"})
    native_lineage = type(lineage).model_validate(raw)
    captured = replace(
        value.registered, report=replace(value.registered.report, lineage=native_lineage)
    )
    value.batches.return_value = {value.source.item_revision_id: captured}
    result = run(value)
    assert len(result.entries) == 1
    assert result.entries[0].schema_version == "public-solution-embedding-entry/3.0"
    assert result.entries[0].evidence.role_result == native_lineage.role_result
    assert result.entries[0].public_solution.text is not None


def test_native_request_ownership_completion_and_replay_metadata_keep_index2_numerics():
    from eom_catalog_contracts.registered_public_solution_registry import (
        PublicSolutionIndexRegistrationResultV4,
        RegisterPublicSolutionIndexCommandV4,
    )
    from eom_workflow.local_embedding_encoding_dispatch import (
        embedding_ownership_version,
        parse_supported_embedding_message,
        validate_supported_embedding_association,
        validate_supported_embedding_completions,
    )
    from eom_workflow.local_embedding_encoding_ownership_v4 import LocalEmbeddingLaunchIntentV4
    from eom_workflow.local_embedding_request_v2 import parse_supported_local_embedding_request
    from eom_workflow.local_embedding_workflow_receipt_v2 import (
        build_supported_local_embedding_step_output,
        parse_supported_local_embedding_workflow_receipt,
    )
    from eom_workflow.local_embedding_workflow_receipt_v4 import (
        ResolvedNativeIndexCoverageV4,
        validate_local_embedding_workflow_receipt_v4,
    )
    from eom_workflow.native_embedding_coordinator import (
        NativeArtifactProducerIdentity,
        NativeCoordinatorAllocation,
    )
    from eom_workflow.native_embedding_coordinator_v4 import native_coordinator_checkpoint_v4

    from tests.unit.inference_transfer_embedding_fixtures import seal
    from tests.unit.local_embedding_admission_fixtures import member
    from tests.unit.test_registered_public_solution_completion import completion_case

    old = completion_case()
    source_entries = tuple(
        native_entry(e) if e.evidence.kind == "REGISTERED_CREATIVE_SOURCE_REPORT" else e
        for e in entries(old.case.plan)
    )
    p = old.case.plan
    query = EmbeddingRegistryLookup(
        p.corpus_id,
        p.namespace,
        p.graph_snapshot,
        p.access_policy_revision_id,
        p.access_policy_sha256,
    )
    resolved = ResolvedEmbeddingLookup(
        p.corpus_id,
        p.space,
        p.recipe,
        p.sources,
        source_entries,
        base_analysis_run_ids=tuple(
            (e.source.item_revision_id, e.base_analysis_run_id) for e in source_entries
        ),
    )
    plan = build_local_embedding_source_plan_v4(
        query, resolved, target_revision_ids=tuple(s.item_revision_id for s in p.sources)
    )
    request = parse_supported_local_embedding_request(
        seal(
            old.case.request.model_dump(mode="json")
            | {
                "schema_version": "local-embedding-workflow-request/5.0",
                "source_plan": member(
                    "source-plan.json",
                    "eom://schemas/workflow/local-embedding-source-plan/5.0",
                    plan.model_dump(mode="json"),
                    "4",
                ),
                "source_plan_sha256": plan.plan_sha256,
            },
            "request_sha256",
        )
    )
    assert request.workflow_definition_version == "2.0.0"
    assert request.runtime_bundle == old.case.request.runtime_bundle
    intent = LocalEmbeddingLaunchIntentV4.model_validate(
        seal(
            old.case.intent.model_dump(mode="json")
            | {
                "workflow_request_sha256": request.request_sha256,
                "source_plan": request.source_plan,
                "source_plan_sha256": plan.plan_sha256,
            },
            "intent_sha256",
        )
    )
    assert embedding_ownership_version(intent) == "embedding-encoding-ownership/5.0"
    association = parse_supported_embedding_message(
        seal(
            old.case.association.model_dump(mode="json")
            | {"schema_version": "embedding-encoding-ownership/5.0", "intent": intent},
            "association_sha256",
        )
    )
    completed = parse_supported_embedding_message(
        seal(
            old.case.completed.model_dump(mode="json")
            | {
                "schema_version": "embedding-encoding-ownership/5.0",
                "intent": intent,
                "launch_association_sha256": association.association_sha256,
            },
            "event_sha256",
        )
    )
    validate_supported_embedding_association(
        association, plan, old.case.owned_input, request.resource_profile, request.request_sha256
    )
    validate_supported_embedding_completions(
        (completed,), association, old.case.owned_input, old.case.result
    )
    built = assemble_registered_public_solution_index_revision(
        plan,
        available_rows=(
            RegisteredEmbeddingRow(old.case.job_request.encoding, completed.receipt.row_ref),
        ),
        shards=((old.case.shard, old.case.result.shard),),
        index_id=old.index.index_id,
        index_revision_id=old.index.index_revision_id,
        previous_manifest=None,
        created_at=old.index.created_at,
    )
    index = built.index
    command = RegisterPublicSolutionIndexCommandV4.model_validate(
        seal(
            old.command.model_dump(mode="json")
            | {
                "schema_version": "embedding-registry-registration-command/5.0",
                "index_manifest": member(
                    "index.json",
                    "eom://schemas/knowledge/embedding-index-manifest/5.0",
                    index.model_dump(mode="json"),
                    "c",
                ),
                "index_sha256": index.index_sha256,
                "binding_set_sha256": content_sha256([b.binding_sha256 for b in index.bindings]),
            },
            "request_sha256",
        )
    )
    result = PublicSolutionIndexRegistrationResultV4.model_validate(
        seal(
            old.result.model_dump(mode="json")
            | {
                "schema_version": "embedding-registry-registration-result/5.0",
                "request_sha256": command.request_sha256,
                "index_manifest": command.index_manifest,
                "index_sha256": command.index_sha256,
            },
            "result_sha256",
        )
    )
    receipt = parse_supported_local_embedding_workflow_receipt(
        seal(
            old.receipt.model_dump(mode="json")
            | {
                "schema_version": "local-embedding-workflow-receipt/5.0",
                "workflow_request_sha256": request.request_sha256,
                "source_plan": request.source_plan,
                "source_plan_sha256": plan.plan_sha256,
                "launch_association_sha256": association.association_sha256,
                "registration_command": command.model_dump(mode="json"),
                "registration_result": result.model_dump(mode="json"),
            },
            "receipt_sha256",
        )
    )
    validate_local_embedding_workflow_receipt_v4(
        receipt,
        request,
        plan,
        old.case.original["policy"],
        workflow_id=intent.workflow_id,
        step_run_id=intent.step_run_id,
        receipt_owner_job_id=receipt.receipt_owner_job_id,
        launch_association=association,
        owned_input=old.case.owned_input,
        index_coverage=ResolvedNativeIndexCoverageV4(index, plan.sources),
    )
    output = build_supported_local_embedding_step_output(
        receipt,
        member(
            "receipt.json",
            "eom://schemas/workflow/local-embedding-workflow-receipt/5.0",
            receipt.model_dump(mode="json"),
            "e",
        ),
    )
    assert output.schema_version == "local-embedding-step-output/5.0"
    allocation = NativeCoordinatorAllocation(
        index_producer=NativeArtifactProducerIdentity(
            job_id="job_" + "c" * 32,
            artifact_id=command.index_manifest.artifact_id,
            artifact_revision_id=command.index_manifest.artifact_revision_id,
        ),
        receipt_producer=NativeArtifactProducerIdentity(
            job_id=receipt.receipt_owner_job_id,
            artifact_id=output.receipt.artifact_id,
            artifact_revision_id=output.receipt.artifact_revision_id,
        ),
        created_at=index.created_at,
        source_commit="a" * 40,
    )
    assert (
        native_coordinator_checkpoint_v4(intent, "ALLOCATION", allocation).schema_version
        == "native-embedding-coordinator/5.0"
    )
