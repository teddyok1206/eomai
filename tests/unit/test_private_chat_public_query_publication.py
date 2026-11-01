"""Recipe2 uses the existing private file-set owner; execution authority is synthetic."""

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from eom_catalog_contracts.embedding_vector_binary import EmbeddingVectorBinaryError
from eom_catalog_contracts.public_solution_query import PUBLIC_SOLUTION_QUERY_RESULT_REF
from eom_catalog_service.embedding_encoder_adapter import encode_public_solution_query
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.embedding_artifact_store import (
    EMBEDDING_PRIVATE_CHAT_QUERY_ARTIFACT_TYPE,
    EmbeddingArtifactStore,
    EmbeddingArtifactStoreError,
)
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetIdentity,
    ControlFileSetPublisher,
)
from eom_workflow.private_chat_query_publication_v2 import (
    PRIVATE_CHAT_PUBLIC_QUERY_RECORD_REF,
    PrivateChatPublicQueryExecutionRecord,
)

from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.test_embedding_artifact_store import SOURCE_COMMIT
from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend
from tests.unit.test_private_chat_public_query_workflow import public_completed as public_completed
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_publication import (
    IdentifiedPublisher,
    PublicationCase,
    launch_case,
    write_member,
)
from tests.unit.test_private_chat_query_workflow import completed as completed


def prepare_public(tmp_path: Path, public_completed, *, publisher=None):
    completed = public_completed
    owner = IdentifiedPublisher() if publisher is None else publisher
    workspace = tmp_path / "private-public-query"
    workspace.mkdir(mode=0o700)
    native = completed.native
    backend = SyntheticNativeBackend(native.spaces.query)
    backend.batch_size, backend.threads = native.batch_size, native.threads
    output = encode_public_solution_query(native, backend)
    assert output.result == completed.result
    write_member(workspace / "input.json", canonical_json_bytes(native))
    write_member(workspace / "result.json", canonical_json_bytes(output.result))
    write_member(workspace / "vectors.f32", output.vectors)
    return PublicationCase(
        EmbeddingArtifactStore(cast(ControlFileSetPublisher, owner), source_commit=SOURCE_COMMIT),
        owner,
        dict(
            workflow_request=completed.request,
            policy=completed.policy,
            bundle=completed.bundle,
            launch=completed.launch,
            request=native,
            workspace=workspace,
            created_at=NOW,
            identity=ControlFileSetIdentity(
                "job_" + "9" * 32, "artifact_" + "a" * 32, "rev_" + "b" * 32
            ),
            expected_result_sha256=output.result.result_sha256,
        ),
        workspace,
        native,
        output.result,
    )


def test_common_query_replays_one_private_four_member_set_without_question_copy(
    tmp_path, public_completed
):
    value = prepare_public(tmp_path, public_completed)
    first = value.store.publish_private_chat_query(**value.arguments)
    assert value.store.publish_private_chat_query(**value.arguments) == first
    assert len(value.publisher.saved) == 1
    metadata = value.publisher.calls[0]
    assert metadata["artifact_type"] == EMBEDDING_PRIVATE_CHAT_QUERY_ARTIFACT_TYPE
    assert tuple(member.file_name for member in metadata["members"]) == (
        "intent.json",
        "result.json",
        "shard.json",
        "vectors.f32",
    )
    assert first.intent.schema_ref == PRIVATE_CHAT_PUBLIC_QUERY_RECORD_REF
    assert first.result.schema_ref == PUBLIC_SOLUTION_QUERY_RESULT_REF
    assert first.owner_job_id != first.logical_query_job_id
    record = PrivateChatPublicQueryExecutionRecord.model_validate_json(
        (value.workspace / "intent.json").read_bytes()
    )
    assert record == public_completed.record
    for member in metadata["members"]:
        assert TEXT.encode() not in member.source.read_bytes()
    assert (value.workspace / "input.json").read_bytes() == canonical_json_bytes(value.native)


@pytest.mark.parametrize(
    "fault",
    (
        "policy_family",
        "request_family",
        "native_family",
        "result_family",
        "observed_hash",
        "binary",
        "duplicate_json",
        "input",
        "identity",
    ),
)
def test_cross_family_or_changed_local_material_cannot_publish(tmp_path, public_completed, fault):
    value = prepare_public(tmp_path, public_completed)
    old_request, old_policy, _bundle, old_native, _launch = launch_case()
    arguments = value.arguments.copy()
    if fault == "policy_family":
        arguments["policy"] = old_policy
    elif fault == "request_family":
        arguments["workflow_request"] = old_request
    elif fault == "native_family":
        arguments["request"] = old_native
    elif fault == "result_family":
        write_member(
            value.workspace / "result.json", canonical_json_bytes(public_completed.previous.result)
        )
    elif fault == "observed_hash":
        arguments["expected_result_sha256"] = "sha256:" + "f" * 64
    elif fault == "binary":
        write_member(value.workspace / "vectors.f32", b"invalid")
    elif fault == "duplicate_json":
        raw = (value.workspace / "result.json").read_bytes()
        write_member(
            value.workspace / "result.json", raw[:-1] + b',"job_id":"job_' + b"f" * 32 + b'"}'
        )
    elif fault == "input":
        write_member(value.workspace / "input.json", b"{}")
    else:
        arguments["identity"] = replace(arguments["identity"], job_id=value.native.job_id)
    with pytest.raises((EmbeddingArtifactStoreError, EmbeddingVectorBinaryError)):
        value.store.publish_private_chat_query(**arguments)
    assert value.publisher.calls == []


@pytest.mark.parametrize(
    "member", ("input.json", "intent.json", "result.json", "shard.json", "vectors.f32")
)
def test_common_query_fds_remain_pinned_through_commit(tmp_path, public_completed, member):
    value = prepare_public(tmp_path, public_completed)
    value.publisher.before_return = lambda: (value.workspace / member).chmod(0o640)
    with pytest.raises(EmbeddingArtifactStoreError, match="MEMBER_CHANGED"):
        value.store.publish_private_chat_query(**value.arguments)
    assert len(value.publisher.saved) == 1


def test_common_query_bad_late_receipt_does_not_erase_commit(tmp_path, public_completed):
    value = prepare_public(tmp_path, public_completed)
    value.publisher.receipt_updates["manifest_sha256"] = "invalid"
    with pytest.raises(EmbeddingArtifactStoreError, match="PRIVATE_CHAT_QUERY_RECEIPT_INVALID"):
        value.store.publish_private_chat_query(**value.arguments)
    assert len(value.publisher.saved) == 1


def test_unknown_common_query_commit_is_preserved_without_automatic_retry(
    tmp_path, public_completed
):
    class UncertainPublisher(IdentifiedPublisher):
        def publish_identified(self, **kwargs):
            super().publish_identified(**kwargs)
            raise RuntimeError("synthetic uncertain commit")

    value = prepare_public(tmp_path, public_completed, publisher=UncertainPublisher())
    with pytest.raises(RuntimeError, match="uncertain commit"):
        value.store.publish_private_chat_query(**value.arguments)
    assert len(value.publisher.calls) == len(value.publisher.saved) == 1
