"""Metadata-only successor uses the existing numeric QUERY2 and finite batch routes."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

from eom_catalog_contracts.inference_transfer_embedding import embedding_input_set_sha256
from eom_catalog_contracts.registered_public_solution_similarity import (
    PublicSolutionSimilarityRequestV4,
    public_solution_reference_for_entry,
)
from eom_catalog_contracts.similarity_read_v4 import (
    SimilarityContextReadReplyV4,
    SimilarityContextReadRequestV4,
)
from eom_catalog_service.embedding_encoder_adapter import encode_public_solution_query
from eom_catalog_service.embedding_registry_ports import (
    AuthorizedEmbeddingReadProfile,
    EmbeddingRegistryRead,
)
from eom_catalog_service.public_solution_index_assembly import (
    assemble_registered_public_solution_index,
)
from eom_catalog_service.public_solution_similarity_service import (
    VerifiedPublicSolutionQueryRead,
    compose_public_solution_similarity,
    prepare_public_solution_query_source,
)
from eom_catalog_service.similarity_read_dispatch import dispatch_similarity_read_frame
from eom_identifiers import canonical_json_bytes
from eom_workflow.embedding_batch_plan_family import (
    embedding_batch_plan_schema_identity,
    parse_embedding_batch_plan_request,
    parse_embedding_batch_selection,
    validate_embedding_batch_plan_controls,
)
from eom_workflow.reference_query_execution import parse_supported_reference_query_workflow_request
from eom_workflow.reference_query_routed_preparation import (
    validate_supported_routed_reference_query_preparation,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.test_embedding_batch_plan import member as batch_member
from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend
from tests.unit.test_native_office_public_embedding import native_entry
from tests.unit.test_public_solution_similarity_contracts import member
from tests.unit.test_registered_public_query_batch_plan import (
    registered_public_parent_case,
    registered_public_preparation_case,
)
from tests.unit.test_registered_public_reference_query_execution import (
    registered_public_workflow_case,
)
from tests.unit.test_registered_public_solution_similarity_service import (
    registered_composition_case,
)


def test_native_index5_composes_and_reads_complete_context5_without_changing_query2():
    original, capture, document, query = registered_composition_case(
        "REGISTERED_CREATIVE_SOURCE_REPORT"
    )
    entries = tuple(
        native_entry(e) if e.evidence.kind == "REGISTERED_CREATIVE_SOURCE_REPORT" else e
        for e in capture.entries
    )
    namespace = document.intent.scope.namespace
    # This fixture's original composition uses the CPU space; preserve its exact
    # registered shard material rather than inventing a CUDA/CPU substitution.
    from tests.unit.test_public_solution_similarity_contracts import public_similarity_case

    shards = public_similarity_case()[4][2]
    index = assemble_registered_public_solution_index(
        entries,
        available_rows=tuple(r.row for r in document.numerical_rows),
        shards=shards,
        namespace=namespace,
        space=capture.space,
        index_id=original.views[0].index.index_id,
        index_revision_id="embeddingindexrev_" + "5" * 32,
        previous_manifest=None,
        created_at=NOW,
    ).index
    body = original.model_dump(mode="json")
    body.update(
        schema_version="system-rag-similarity-request/5.0",
        anchor=public_solution_reference_for_entry(
            next(e for e in entries if e.evidence.kind == "REGISTERED_CREATIVE_SOURCE_REPORT")
        ).model_dump(mode="json"),
    )
    body["views"][0]["index"].update(
        index_revision_id=index.index_revision_id,
        index_sha256=index.index_sha256,
        index_manifest=member(
            index, schema="eom://schemas/knowledge/embedding-index-manifest/5.0", name="index.json"
        ).model_dump(mode="json"),
    )
    request = PublicSolutionSimilarityRequestV4.model_validate(seal(body, "request_sha256"))
    capture = replace(capture, entries=entries)
    prepared = prepare_public_solution_query_source(request, capture)
    numerical = type(query.request).model_validate(
        seal(
            query.request.model_dump(mode="json")
            | {
                "context_request_sha256": request.request_sha256,
                "rows": [prepared.row.model_dump(mode="json")],
                "input_set_sha256": embedding_input_set_sha256((prepared.row.encoding,)),
            },
            "request_sha256",
        )
    )
    backend = SyntheticNativeBackend(numerical.spaces.query)
    backend.batch_size, backend.threads = numerical.batch_size, numerical.threads
    encoded = encode_public_solution_query(numerical, backend)
    query = VerifiedPublicSolutionQueryRead(
        numerical,
        encoded.result,
        member(
            encoded.result,
            schema="eom://schemas/knowledge/embedding-reference-query-result/2.0",
            name="result.json",
        ),
        member(
            encoded.result.shard,
            schema="eom://schemas/knowledge/embedding-vector-shard/1.0",
            name="shard.json",
        ),
        encoded.vectors,
    )
    document = replace(
        document,
        intent=EmbeddingRegistryRead(document.intent.scope, request.views[0]),
        profiles=tuple(
            AuthorizedEmbeddingReadProfile(
                e.source.item_revision_id, public_solution_reference_for_entry(e).profile
            )
            for e in entries
        ),
        bindings=index.bindings,
    )
    result = compose_public_solution_similarity(request, capture, document, query)
    assert result.schema_version == "system-rag-similarity-context/5.0"
    assert result.status == "READY" and len(result.candidates) == 2
    read = SimilarityContextReadRequestV4(
        schema_version="system-rag-similarity-read-request/5.0",
        operation="READ_SIMILARITY_CONTEXT",
        actor_id="operator_" + "1" * 32,
        selection={
            "workflow_id": "workflow_" + "1" * 32,
            "workflow_request_sha256": "sha256:" + "1" * 64,
            "context_request_sha256": request.request_sha256,
        },
    )
    service = SimpleNamespace(read=Mock(return_value=result))
    for _ in range(2):
        reply = SimilarityContextReadReplyV4.model_validate_json(
            dispatch_similarity_read_frame(service, canonical_json_bytes(read) + b"\n")
        )
        assert (
            reply.result == result
            and reply.schema_version == "system-rag-similarity-read-reply/5.0"
        )


def test_native_query_parent19_preparation4_and_workflow5_keep_original_numeric_controls():
    original = registered_public_parent_case()
    body = original.selection.model_dump(mode="json")
    body.update(
        schema_version="embedding-batch-plan/1.9",
        anchors=[public_solution_reference_for_entry(native_entry()).model_dump(mode="json")],
    )
    for device in ("cpu", "cuda"):
        body["index_pairs"][0][device]["index"]["index_manifest"]["schema_ref"] = (
            "eom://schemas/knowledge/embedding-index-manifest/5.0"
        )
    selection = parse_embedding_batch_selection(seal(body, "selection_sha256"))
    parent = parse_embedding_batch_plan_request(
        seal(
            original.request.model_dump(mode="json")
            | {
                "schema_version": "embedding-batch-plan/1.9",
                "selection_manifest": batch_member(
                    "selection.json",
                    "eom://schemas/workflow/embedding-batch-plan/1.9#/$defs/selection",
                    selection,
                    "e",
                ),
                "selection_sha256": selection.selection_sha256,
                "child_selection_sha256s": selection.child_selection_sha256s,
            },
            "request_sha256",
        )
    )
    assert embedding_batch_plan_schema_identity(parent)[0] == "embedding-batch-plan/1.9"
    validate_embedding_batch_plan_controls(parent, selection, original.policy)
    prep = validate_supported_routed_reference_query_preparation(
        seal(
            registered_public_preparation_case().model_dump(mode="json")
            | {
                "schema_version": "reference-query-routed-preparation/4.0",
                "parent": parent.model_dump(mode="json"),
            },
            "preparation_sha256",
        )
    )
    assert prep.parent == parent
    from eom_catalog_contracts.reference_query_prepare import (
        ReferenceQueryPrepareReplyV6,
        parse_supported_reference_query_prepare_reply,
    )

    reply = ReferenceQueryPrepareReplyV6.model_validate(
        {
            "schema_version": "system-rag-reference-query-prepare-reply/6.0",
            "operation": "PREPARE_REFERENCE_QUERY",
            "operation_id": "queryprepare_" + "1" * 32,
            "request_sha256": "sha256:" + "1" * 64,
            "request_schema_version": "system-rag-reference-query-prepare-request/4.0",
            "status": "PENDING",
            "preparation": batch_member(
                "preparation.json",
                "eom://schemas/workflow/reference-query-routed-preparation/4.0",
                prep,
                "d",
            ),
            "parent_request_sha256": parent.request_sha256,
            "device": None,
            "children": [
                {
                    "ordinal": 0,
                    "source_item_revision_id": selection.anchors[0].source.item_revision_id,
                    "workflow_id": None,
                    "state": "PENDING",
                    "selection": None,
                }
            ],
            "workflow_id": None,
            "selection": None,
            "error_code": None,
        }
    )
    assert parse_supported_reference_query_prepare_reply(reply) == reply
    old_workflow = registered_public_workflow_case()
    context = old_workflow.request.context_request.model_dump(mode="json")
    context.update(
        schema_version="system-rag-similarity-request/5.0",
        anchor=selection.anchors[0].model_dump(mode="json"),
    )
    context["views"][0]["index"]["index_manifest"]["schema_ref"] = (
        "eom://schemas/knowledge/embedding-index-manifest/5.0"
    )
    request = parse_supported_reference_query_workflow_request(
        seal(
            old_workflow.request.model_dump(mode="json")
            | {
                "schema_version": "reference-query-workflow-request/5.0",
                "context_request": seal(context, "request_sha256"),
            },
            "request_sha256",
        )
    )
    assert request.workflow_definition_version == "2.0.0"
    assert request.resource_profile == old_workflow.request.resource_profile
    assert request.runtime_bundle == old_workflow.request.runtime_bundle
