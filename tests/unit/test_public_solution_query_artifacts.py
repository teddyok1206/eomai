"""Real local canonical publication/read, synthetic QUERY/source/launch; not live authority."""

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_contracts.public_solution_query import (
    PUBLIC_SOLUTION_QUERY_INPUT_REF,
    PUBLIC_SOLUTION_QUERY_RESULT_REF,
)
from eom_catalog_service.embedding_encoder_adapter import encode_public_solution_query
from eom_catalog_service.reference_query_artifact_read import CatalogReferenceQueryArtifacts
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.embedding_artifact_store import (
    EmbeddingArtifactStore,
    EmbeddingArtifactStoreError,
)
from eom_workflow.reference_query_execution import ReferenceQueryWorkflowReceiptV2

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend
from tests.unit.test_public_solution_reference_query_execution import public_workflow_case
from tests.unit.test_reference_query_execution_contracts import case
from tests.unit.test_registered_public_reference_query_execution import (
    registered_public_workflow_case,
)


def public_artifact_case(tmp_path, publisher=None, *, case_factory=public_workflow_case):
    c = case_factory(identity=uuid4().hex)
    backend = SyntheticNativeBackend(c.native_input.spaces.query)
    backend.batch_size, backend.threads = c.native_input.batch_size, c.native_input.threads
    encoded = encode_public_solution_query(c.native_input, backend)
    c.result = encoded.result
    workspace = tmp_path / "public-query-output"
    workspace.mkdir(mode=0o700)
    for name, payload in (
        ("input.json", canonical_json_bytes(c.native_input.model_dump(mode="json"))),
        ("result.json", canonical_json_bytes(encoded.result.model_dump(mode="json"))),
        ("vectors.f32", encoded.vectors),
    ):
        target = workspace / name
        target.write_bytes(payload)
        target.chmod(0o600)
    if publisher is None:
        publisher, _ = _publisher(tmp_path)
    return SimpleNamespace(
        case=c,
        publisher=publisher,
        workspace=workspace,
        binary=encoded.vectors,
        store=EmbeddingArtifactStore(publisher, source_commit="a" * 40),
    )


def publication_arguments(value):
    c = value.case
    return dict(
        workflow_request=c.request,
        policy=c.policy,
        bundle=c.bundle,
        launch=c.launch,
        request=c.native_input,
        workspace=value.workspace,
        created_at=c.receipt.published_at,
        expected_result_sha256=c.result.result_sha256,
    )


def publish_public_query(value):
    return value.store.publish_public_solution_reference_query(**publication_arguments(value))


def published_read_arguments(value, published):
    c = value.case
    receipt = ReferenceQueryWorkflowReceiptV2.model_validate(
        seal(
            c.receipt.model_dump(mode="json")
            | {
                "query_artifact_owner_job_id": published.owner_job_id,
                "query_input": published.input.model_dump(mode="json"),
                "query_execution": {
                    "job_id": c.native_input.job_id,
                    "query_request_id": c.native_input.query_request_id,
                    "request_sha256": c.native_input.request_sha256,
                    "input_set_sha256": c.native_input.input_set_sha256,
                    "result_member": published.result.model_dump(mode="json"),
                    "result_sha256": c.result.result_sha256,
                },
                "shard": published.shard.model_dump(mode="json"),
                "binary": published.binary.model_dump(mode="json"),
            },
            "receipt_sha256",
        )
    )
    return dict(
        workflow_request=c.request,
        policy=c.policy,
        bundle=c.bundle,
        launch=c.launch,
        receipt=receipt,
        workflow_id=c.launch.workflow_id,
        step_run_id=c.launch.step_run_id,
        receipt_owner_job_id=receipt.receipt_owner_job_id,
        manifest_sha256=published.manifest_sha256,
    )


@pytest.mark.parametrize("case_factory", [public_workflow_case, registered_public_workflow_case])
def test_public_query_publication_and_canonical_read_preserve_producer_and_exact_family(
    tmp_path, case_factory
):
    value = public_artifact_case(tmp_path, case_factory=case_factory)
    first, replay = publish_public_query(value), publish_public_query(value)
    assert first == replay and first.logical_query_job_id == value.case.native_input.job_id
    assert first.owner_job_id != first.logical_query_job_id
    assert first.input.schema_ref == PUBLIC_SOLUTION_QUERY_INPUT_REF
    assert first.result.schema_ref == PUBLIC_SOLUTION_QUERY_RESULT_REF
    with value.publisher.sessions.begin() as session:
        reader = CatalogReferenceQueryArtifacts(
            session, CatalogSettings(nas_artifact_root=value.publisher.settings.nas_artifact_root)
        )
        resolved = reader.resolve_public_solution_publication(
            **published_read_arguments(value, first)
        )
    assert resolved.request == value.case.native_input
    assert resolved.result == value.case.result and resolved.binary == value.binary
    assert resolved.publication_job_id == first.owner_job_id


@pytest.mark.parametrize(
    "fault",
    ["old_request", "old_input", "result_context", "result_family", "binary", "expected_result"],
)
def test_public_query_publication_rejects_wrong_family_hash_or_completion_before_commit(
    tmp_path, fault
):
    value = public_artifact_case(tmp_path)
    args = publication_arguments(value)
    if fault == "old_request":
        args["workflow_request"] = case().request
    elif fault == "old_input":
        args["request"] = case().native_input
    elif fault in {"result_context", "result_family"}:
        document = value.case.result.model_dump(mode="json")
        if fault == "result_context":
            document["context_request_sha256"] = content_sha256({"foreign": True})
        else:
            document["schema_version"] = "embedding-reference-query-result/1.0"
        document = seal(document, "result_sha256")
        (value.workspace / "result.json").write_bytes(canonical_json_bytes(document))
    elif fault == "binary":
        (value.workspace / "vectors.f32").write_bytes(bytes(len(value.binary)))
    else:
        args["expected_result_sha256"] = content_sha256({"foreign": True})
    with pytest.raises(ValueError):
        value.store.publish_public_solution_reference_query(**args)


def test_legacy_publication_and_read_do_not_accept_query2_or_its_receipt(tmp_path):
    value = public_artifact_case(tmp_path)
    with pytest.raises(EmbeddingArtifactStoreError, match="CONTEXT_INVALID"):
        value.store.publish_reference_query(**publication_arguments(value))
    published = publish_public_query(value)
    with value.publisher.sessions.begin() as session:
        reader = CatalogReferenceQueryArtifacts(
            session, CatalogSettings(nas_artifact_root=value.publisher.settings.nas_artifact_root)
        )
        with pytest.raises(ValueError):
            reader.resolve_publication(**published_read_arguments(value, published))


def test_publication_read_checks_actual_committed_member_bytes_not_only_receipt(tmp_path):
    value = public_artifact_case(tmp_path)
    published = publish_public_query(value)
    with value.publisher.sessions.begin() as session:
        reader = CatalogReferenceQueryArtifacts(
            session, CatalogSettings(nas_artifact_root=value.publisher.settings.nas_artifact_root)
        )
        args = published_read_arguments(value, published)
        reader.resolve_public_solution_publication(**args)
    root = Path(value.publisher.settings.nas_artifact_root)
    vector_members = tuple(root.rglob("vectors.f32"))
    assert len(vector_members) == 1
    vector_members[0].write_bytes(bytes(len(value.binary)))
    with value.publisher.sessions.begin() as session:
        reader = CatalogReferenceQueryArtifacts(session, CatalogSettings(nas_artifact_root=root))
        with pytest.raises(ValueError):
            reader.resolve_public_solution_publication(**args)
