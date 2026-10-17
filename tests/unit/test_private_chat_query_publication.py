"""Synthetic launch closure and local file publication; not actual native admission."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

import pytest
from eom_catalog_contracts.embedding_vector_binary import EmbeddingVectorBinaryError
from eom_catalog_service.embedding_encoder_adapter import encode_private_chat_query
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.embedding_artifact_store import (
    EMBEDDING_PRIVATE_CHAT_QUERY_ARTIFACT_TYPE,
    EmbeddingArtifactStore,
    EmbeddingArtifactStoreError,
)
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetIdentity,
    ControlFileSetPublisher,
)
from eom_workflow.private_chat_query_publication import (
    PRIVATE_CHAT_QUERY_RECORD_REF,
    PrivateChatQueryExecutionRecord,
    PrivateChatQueryLaunchAssociation,
    validate_private_chat_query_launch,
)
from eom_workflow.reference_query_execution import parse_reference_query_launch_association
from eom_workflow.schemas import (
    PRIVATE_CHAT_QUERY_PUBLICATION_SCHEMA_RESOURCE,
    load_local_embedding_admission_schema,
)
from jsonschema import Draft202012Validator

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.test_embedding_artifact_store import SOURCE_COMMIT, FakePublisher
from tests.unit.test_embedding_private_chat_query import backend
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_execution import execution_case, native_input
from tests.unit.test_reference_query_execution_contracts import case


class IdentifiedPublisher(FakePublisher):
    def publish_identified(self, *, identity, **kwargs):
        result = super().publish(**kwargs)
        result = replace(
            result,
            job_id=identity.job_id,
            artifact_id=identity.artifact_id,
            artifact_revision_id=identity.artifact_revision_id,
        )
        return replace(result, **self.receipt_updates)


def launch_case():
    request, policy, bundle = execution_case()
    native = native_input(request, policy, bundle)
    launch = case().launch.model_dump(mode="json") | {
        "schema_version": "private-chat-query-launch-association/1.0",
        "purpose": "PRIVATE_CHAT_QUERY",
        "step_key": "encode_private_chat_query",
        "workflow_request_sha256": request.request_sha256,
        "context_request_sha256": request.context_request.request_sha256,
        "basis_sha256": native.basis.basis_sha256,
        "native_launch_job_id": native.job_id,
        "query_request_id": native.query_request_id,
        "query_request_sha256": native.request_sha256,
        "query_input_set_sha256": native.input_set_sha256,
        "recipe_sha256": native.document_recipe.recipe_sha256,
    }
    return (
        request,
        policy,
        bundle,
        native,
        PrivateChatQueryLaunchAssociation.model_validate(seal(launch, "association_sha256")),
    )


@dataclass
class PublicationCase:
    store: EmbeddingArtifactStore
    publisher: IdentifiedPublisher
    arguments: dict
    workspace: Path
    native: object
    result: object


def write_member(path, payload):
    path.write_bytes(payload)
    path.chmod(0o600)


def prepare(tmp_path, *, publisher=None):
    request, policy, bundle, native, launch = launch_case()
    owner = IdentifiedPublisher() if publisher is None else publisher
    store = EmbeddingArtifactStore(
        cast(ControlFileSetPublisher, owner), source_commit=SOURCE_COMMIT
    )
    workspace = tmp_path / "private-query"
    workspace.mkdir(mode=0o700)
    output = encode_private_chat_query(native, backend(native))
    write_member(workspace / "input.json", canonical_json_bytes(native))
    write_member(workspace / "result.json", canonical_json_bytes(output.result))
    write_member(workspace / "vectors.f32", output.vectors)
    arguments = {
        "workflow_request": request,
        "policy": policy,
        "bundle": bundle,
        "launch": launch,
        "request": native,
        "workspace": workspace,
        "created_at": NOW,
        "identity": ControlFileSetIdentity(
            "job_" + "9" * 32, "artifact_" + "a" * 32, "rev_" + "b" * 32
        ),
        "expected_result_sha256": output.result.result_sha256,
    }
    return PublicationCase(store, owner, arguments, workspace, native, output.result)


def test_private_publication_schema_is_separate_exact_and_packaged():
    _, filename, schema_id, digest = PRIVATE_CHAT_QUERY_PUBLICATION_SCHEMA_RESOURCE
    root = Path(__file__).resolve().parents[2]
    raw = (root / "schemas/workflow" / filename).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / filename).read_bytes()
    assert sha256_bytes(raw) == digest
    schema = load_local_embedding_admission_schema("private-chat-publication")
    assert schema["$id"] == schema_id
    Draft202012Validator.check_schema(schema)
    request, policy, bundle, native, launch = launch_case()
    record = validate_private_chat_query_launch(launch, request, policy, bundle, native)
    assert PrivateChatQueryExecutionRecord.model_validate(record) == record
    assert TEXT not in canonical_json_bytes(record).decode()
    with pytest.raises(ValueError):
        parse_reference_query_launch_association(launch)


@pytest.mark.parametrize(
    "field",
    [
        "workflow_request_sha256",
        "context_request_sha256",
        "basis_sha256",
        "query_request_sha256",
        "query_input_set_sha256",
        "recipe_sha256",
        "resource_profile_sha256",
        "native_launch_job_id",
        "query_request_id",
    ],
)
def test_cross_bound_launch_cannot_publish(field):
    request, policy, bundle, native, launch = launch_case()
    body = launch.model_dump(mode="json")
    if field.endswith("sha256"):
        body[field] = "sha256:" + "f" * 64
    else:
        body[field] = ("job_" if field == "native_launch_job_id" else "embeddingquery_") + "f" * 32
    changed = PrivateChatQueryLaunchAssociation.model_validate(seal(body, "association_sha256"))
    with pytest.raises(ValueError):
        validate_private_chat_query_launch(changed, request, policy, bundle, native)


def test_exact_replay_publishes_no_second_question_text_copy(tmp_path):
    value = prepare(tmp_path)
    first = value.store.publish_private_chat_query(**value.arguments)
    assert value.store.publish_private_chat_query(**value.arguments) == first
    assert len(value.publisher.saved) == 1
    metadata = value.publisher.calls[0]
    assert metadata["artifact_type"] == EMBEDDING_PRIVATE_CHAT_QUERY_ARTIFACT_TYPE
    assert metadata["idempotency_key"].startswith("embedding-private-chat-query-artifact:")
    assert tuple(v.file_name for v in metadata["members"]) == (
        "intent.json",
        "result.json",
        "shard.json",
        "vectors.f32",
    )
    assert first.intent.schema_ref == PRIVATE_CHAT_QUERY_RECORD_REF
    assert first.owner_job_id != first.logical_query_job_id
    assert (value.workspace / "input.json").read_bytes() == canonical_json_bytes(value.native)
    for member in metadata["members"]:
        assert TEXT.encode() not in member.source.read_bytes()
    record = PrivateChatQueryExecutionRecord.model_validate_json(
        (value.workspace / "intent.json").read_bytes()
    )
    assert record.workflow_request.context_request.query_basis == value.native.basis
    assert record.launch.query_request_sha256 == value.native.request_sha256


@pytest.mark.parametrize(
    "fault",
    [
        "input",
        "result",
        "binary",
        "duplicate_json",
        "intent",
        "symlink",
        "mode",
        "observed_hash",
        "identity",
    ],
)
def test_invalid_input_result_or_files_fail_before_publication(tmp_path, fault):
    value = prepare(tmp_path)
    arguments = value.arguments.copy()
    if fault == "input":
        write_member(value.workspace / "input.json", b"{}")
    elif fault == "result":
        write_member(value.workspace / "result.json", b"{}")
    elif fault == "binary":
        write_member(value.workspace / "vectors.f32", b"invalid")
    elif fault == "duplicate_json":
        raw = (value.workspace / "result.json").read_bytes()
        write_member(
            value.workspace / "result.json", raw[:-1] + b',"job_id":"job_' + b"f" * 32 + b'"}'
        )
    elif fault == "intent":
        write_member(value.workspace / "intent.json", b"{}")
    elif fault == "symlink":
        (value.workspace / "vectors.f32").rename(tmp_path / "preserved-vector")
        (value.workspace / "vectors.f32").symlink_to(tmp_path / "preserved-vector")
    elif fault == "mode":
        (value.workspace / "result.json").chmod(0o644)
    elif fault == "observed_hash":
        arguments["expected_result_sha256"] = "sha256:" + "f" * 64
    else:
        arguments["identity"] = ControlFileSetIdentity(
            value.native.job_id, "artifact_" + "a" * 32, "rev_" + "b" * 32
        )
    with pytest.raises((EmbeddingArtifactStoreError, EmbeddingVectorBinaryError)):
        value.store.publish_private_chat_query(**arguments)
    assert value.publisher.calls == []


@pytest.mark.parametrize(
    "field",
    [
        "job_id",
        "artifact_id",
        "artifact_revision_id",
        "primary_file",
        "primary_sha256",
        "manifest_sha256",
    ],
)
def test_malformed_publisher_receipt_is_not_success(tmp_path, field):
    value = prepare(tmp_path)
    value.publisher.receipt_updates[field] = "invalid"
    with pytest.raises(EmbeddingArtifactStoreError, match="PRIVATE_CHAT_QUERY_RECEIPT_INVALID"):
        value.store.publish_private_chat_query(**value.arguments)
    assert len(value.publisher.calls) == 1


@pytest.mark.parametrize(
    "member", ["input.json", "intent.json", "result.json", "shard.json", "vectors.f32"]
)
def test_input_and_all_committed_member_fds_stay_pinned_through_publication(tmp_path, member):
    value = prepare(tmp_path)
    value.publisher.before_return = lambda: (value.workspace / member).chmod(0o640)
    with pytest.raises(EmbeddingArtifactStoreError, match="MEMBER_CHANGED"):
        value.store.publish_private_chat_query(**value.arguments)
    assert len(value.publisher.saved) == 1


def test_unknown_commit_outcome_is_not_retried_or_relabelled_success(tmp_path):
    class UncertainPublisher(IdentifiedPublisher):
        def publish_identified(self, **kwargs):
            super().publish_identified(**kwargs)
            raise RuntimeError("synthetic uncertain commit")

    value = prepare(tmp_path, publisher=UncertainPublisher())
    with pytest.raises(RuntimeError, match="uncertain commit"):
        value.store.publish_private_chat_query(**value.arguments)
    assert len(value.publisher.calls) == len(value.publisher.saved) == 1
