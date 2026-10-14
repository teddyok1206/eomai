"""Synthetic QUERY publication leaf; not real producer, auth, lease, NAS or DB evidence."""

from __future__ import annotations

import json
import os
import stat
import struct
from dataclasses import FrozenInstanceError, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import pytest
from eom_catalog_contracts.embedding_reference_query import (
    REFERENCE_QUERY_RESULT_REF,
    EmbeddingReferenceQueryResult,
    parse_embedding_reference_query_result,
)
from eom_catalog_contracts.embedding_reference_query_v11 import (
    REFERENCE_QUERY_INPUT_V11_REF,
    parse_embedding_reference_query_input_v11,
)
from eom_catalog_contracts.embedding_vector_binary import (
    EmbeddingVectorBinaryError,
    read_unit_vectors,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    SHARD_SCHEMA_REF,
    embedding_input_set_sha256,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.embedding_artifact_store import (
    EmbeddingArtifactStore,
    EmbeddingArtifactStoreError,
    PublishedReferenceQueryArtifacts,
)
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetPublisher,
    PublishedControlFileSet,
)
from eom_workflow.reference_query_execution import (
    parse_reference_query_launch_association,
    parse_reference_query_workflow_request,
    validate_reference_query_launch_association,
)

from tests.unit.inference_transfer_embedding_fixtures import encoding_identity, seal
from tests.unit.inference_transfer_fixtures import NOW, sha
from tests.unit.test_embedding_artifact_store import SOURCE_COMMIT, FakePublisher
from tests.unit.test_embedding_reference_query_v11_contracts import input_body, result_body
from tests.unit.test_reference_query_execution_contracts import Case, case


@pytest.fixture(scope="module")
def query_case() -> Case:
    return case()


def three_view_case(base: Case) -> Case:
    """Extend supplied test metadata only; no index registration or source authority exists."""
    context = base.request.context_request.model_dump(mode="json")
    third = base.request.context_request.views[0].model_dump(mode="json")
    third["view"] = "METADATA_ONLY"
    third["index"] = third["index"] | {
        "index_id": "embeddingindex_" + "3" * 32,
        "index_revision_id": "embeddingindexrev_" + "3" * 32,
        "index_sha256": sha("3"),
        "index_manifest": third["index"]["index_manifest"]
        | {
            "artifact_id": "artifact_" + "3" * 32,
            "artifact_revision_id": "rev_" + "3" * 32,
            "sha256": sha("3"),
        },
    }
    context["views"].append(third)
    controller = parse_reference_query_workflow_request(
        seal(
            base.request.model_dump(mode="json")
            | {"context_request": seal(context, "request_sha256")},
            "request_sha256",
        )
    )
    native = input_body(batch_size=4, row_count=3)
    native["spaces"] = base.native_input.spaces.model_dump(mode="json")
    native["threads"] = base.native_input.threads
    native["context_request_sha256"] = controller.context_request.request_sha256
    for row in native["rows"]:
        row["encoding"] = encoding_identity(row["text"], base.native_input.spaces.query).model_dump(
            mode="json"
        )
    native["rows"].sort(key=lambda row: row["encoding"]["encoding_sha256"])
    native["input_set_sha256"] = embedding_input_set_sha256(
        tuple(
            encoding_identity(row["text"], base.native_input.spaces.query) for row in native["rows"]
        )
    )
    native_input = parse_embedding_reference_query_input_v11(seal(native, "request_sha256"))
    launch = parse_reference_query_launch_association(
        seal(
            base.launch.model_dump(mode="json")
            | {
                "workflow_request_sha256": controller.request_sha256,
                "context_request_sha256": controller.context_request.request_sha256,
                "query_request_sha256": native_input.request_sha256,
                "query_input_set_sha256": native_input.input_set_sha256,
            },
            "association_sha256",
        )
    )
    validate_reference_query_launch_association(
        launch, controller, base.policy, base.bundle, native_input
    )
    # Case's existing receipt/output are unused fixtures, never evidence of this leaf publication.
    return replace(
        base,
        request=controller,
        launch=launch,
        native_input=native_input,
        result=parse_embedding_reference_query_result(result_body(native_input)),
    )


@dataclass
class PreparedQuery:
    store: EmbeddingArtifactStore
    publisher: FakePublisher
    case: Case
    result: EmbeddingReferenceQueryResult
    workspace: Path
    binary: bytes


def write_member(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def prepare(
    tmp_path: Path, query_case: Case, *, publisher: FakePublisher | None = None
) -> PreparedQuery:
    workspace = tmp_path / "query-workspace"
    workspace.mkdir(mode=0o700)
    dimension = query_case.result.shard.dimension
    count = query_case.result.shard.row_count
    binary = struct.pack(f"<{dimension * count}f", *([1.0] + [0.0] * (dimension - 1)) * count)
    body = query_case.result.model_dump(mode="json")
    body["shard"]["binary"]["sha256"] = sha256_bytes(binary)
    body["shard"] = seal(body["shard"], "shard_sha256")
    result = parse_embedding_reference_query_result(seal(body, "result_sha256"))
    write_member(
        workspace / "input.json",
        canonical_json_bytes(query_case.native_input.model_dump(mode="json")),
    )
    write_member(workspace / "result.json", canonical_json_bytes(result.model_dump(mode="json")))
    write_member(workspace / "vectors.f32", binary)
    owner = publisher or FakePublisher()
    return PreparedQuery(
        EmbeddingArtifactStore(cast(ControlFileSetPublisher, owner), source_commit=SOURCE_COMMIT),
        owner,
        query_case,
        result,
        workspace,
        binary,
    )


def publish(value: PreparedQuery, **changes: Any) -> PublishedReferenceQueryArtifacts:
    arguments: dict[str, Any] = {
        "workflow_request": value.case.request,
        "policy": value.case.policy,
        "bundle": value.case.bundle,
        "launch": value.case.launch,
        "request": value.case.native_input,
        "workspace": value.workspace,
        "created_at": NOW,
    } | changes
    return value.store.publish_reference_query(**arguments)


@pytest.mark.parametrize("digest", ("sha256:" + "f" * 64, True, "not-a-hash"))
def test_observed_completion_hash_is_checked_before_any_publication(tmp_path, query_case, digest):
    value = prepare(tmp_path, query_case)
    with pytest.raises(EmbeddingArtifactStoreError):
        publish(value, expected_result_sha256=digest)
    assert value.publisher.calls == []


def test_exact_observed_completion_hash_keeps_existing_publication_contract(tmp_path, query_case):
    value = prepare(tmp_path, query_case)
    result = publish(value, expected_result_sha256=value.result.result_sha256)
    assert result.result.member_path == "result.json"
    assert len(value.publisher.calls) == 1


def replace_binary(value: PreparedQuery, payload: bytes, *, rehash: bool) -> None:
    write_member(value.workspace / "vectors.f32", payload)
    if rehash:
        body = value.result.model_dump(mode="json")
        body["shard"]["binary"]["sha256"] = sha256_bytes(payload)
        body["shard"] = seal(body["shard"], "shard_sha256")
        value.result = parse_embedding_reference_query_result(seal(body, "result_sha256"))
        write_member(
            value.workspace / "result.json",
            canonical_json_bytes(value.result.model_dump(mode="json")),
        )


def prepare_three_views(tmp_path: Path, base: Case) -> PreparedQuery:
    value = prepare(tmp_path, three_view_case(base))
    dimension = value.result.shard.dimension
    values = tuple(1.0 if column == row else 0.0 for row in range(3) for column in range(dimension))
    replace_binary(value, struct.pack(f"<{len(values)}f", *values), rehash=True)
    value.binary = (value.workspace / "vectors.f32").read_bytes()
    return value


def test_three_ordered_view_rows_with_distinct_vectors_and_configured_batch_four(
    tmp_path: Path, query_case: Case
) -> None:
    value = prepare_three_views(tmp_path, query_case)
    published = publish(value)
    native = value.case.native_input
    assert native.batch_size == value.case.request.resource_profile.batch_size == 4
    assert len(native.rows) == value.result.shard.row_count == 3
    assert {row.view for row in native.rows} == {"CONTENT_ONLY", "CONCRETE_FACETS", "METADATA_ONLY"}
    assert tuple(row.encoding.encoding_sha256 for row in native.rows) == tuple(
        sorted(row.encoding.encoding_sha256 for row in native.rows)
    )
    assert tuple(row.view for row in native.rows) == tuple(
        row.view for row in value.result.view_rows
    )
    assert tuple(row.row_index for row in value.result.view_rows) == (0, 1, 2)
    vectors = read_unit_vectors(
        value.binary,
        dimension=value.result.shard.dimension,
        row_count=3,
        expected_sha256=published.binary.sha256,
    )
    assert len(set(vectors)) == 3
    assert tuple(vector[index] for index, vector in enumerate(vectors)) == (1.0, 1.0, 1.0)
    assert published.binary.sha256 == sha256_bytes(value.binary)
    assert (value.workspace / "vectors.f32").read_bytes() == value.binary
    assert tuple(member.file_name for member in value.publisher.calls[0]["members"]) == (
        "input.json",
        "result.json",
        "shard.json",
        "vectors.f32",
    )


@pytest.mark.parametrize("failure", ["view_swap", "row_swap", "binary_swap", "binary_rows"])
def test_three_view_swapped_row_view_or_binary_frame_is_not_published(
    tmp_path: Path, query_case: Case, failure: str
) -> None:
    value = prepare_three_views(tmp_path, query_case)
    if failure in {"view_swap", "row_swap"}:
        body = value.result.model_dump(mode="json")
        if failure == "view_swap":
            body["view_rows"][0]["view"], body["view_rows"][1]["view"] = (
                body["view_rows"][1]["view"],
                body["view_rows"][0]["view"],
            )
        else:
            body["shard"]["rows"][0], body["shard"]["rows"][1] = (
                body["shard"]["rows"][1],
                body["shard"]["rows"][0],
            )
            body["shard"] = seal(body["shard"], "shard_sha256")
        payload = canonical_json_bytes(seal(body, "result_sha256"))
        write_member(value.workspace / "result.json", payload)
        with pytest.raises(
            EmbeddingArtifactStoreError, match="EMBEDDING_REFERENCE_QUERY_RESULT_INVALID"
        ):
            publish(value)
        assert (value.workspace / "result.json").read_bytes() == payload
    else:
        row_bytes = value.result.shard.dimension * 4
        payload = (
            value.binary[row_bytes : 2 * row_bytes]
            + value.binary[:row_bytes]
            + value.binary[2 * row_bytes :]
            if failure == "binary_swap"
            else value.binary[: 2 * row_bytes]
        )
        replace_binary(value, payload, rehash=failure == "binary_rows")
        with pytest.raises(EmbeddingVectorBinaryError):
            publish(value)
        assert (value.workspace / "vectors.f32").read_bytes() == payload
    assert value.publisher.calls == []


def test_fixed_four_members_return_one_pinned_artifact_without_authority_claim(
    tmp_path: Path, query_case: Case
) -> None:
    value = prepare(tmp_path, query_case)
    original = {
        name: (value.workspace / name).read_bytes()
        for name in ("input.json", "result.json", "vectors.f32")
    }
    published = publish(value)
    pointers = (published.input, published.result, published.shard, published.binary)
    assert published.logical_query_job_id == query_case.native_input.job_id
    assert published.owner_job_id == "job_" + "9" * 32
    assert {pointer.artifact_id for pointer in pointers} == {"artifact_" + "a" * 32}
    assert {pointer.artifact_revision_id for pointer in pointers} == {"rev_" + "b" * 32}
    assert tuple(pointer.member_path for pointer in pointers) == (
        "input.json",
        "result.json",
        "shard.json",
        "vectors.f32",
    )
    assert tuple(pointer.schema_ref for pointer in pointers) == (
        REFERENCE_QUERY_INPUT_V11_REF,
        REFERENCE_QUERY_RESULT_REF,
        SHARD_SCHEMA_REF,
        "eom://schemas/knowledge/embedding-f32le-l2-row-major/1.0",
    )
    assert tuple(pointer.media_type for pointer in pointers) == (
        "application/json",
        "application/json",
        "application/json",
        "application/octet-stream",
    )
    for pointer in pointers:
        assert pointer.sha256 == sha256_bytes((value.workspace / pointer.member_path).read_bytes())
    assert published.manifest_sha256 == sha("c")
    assert query_case.native_input.batch_size == 4 and value.result.shard.row_count == 1
    assert (value.workspace / "shard.json").read_bytes() == canonical_json_bytes(
        value.result.shard.model_dump(mode="json")
    )
    assert stat.S_IMODE((value.workspace / "shard.json").stat().st_mode) == 0o600
    assert all(
        (value.workspace / name).read_bytes() == payload for name, payload in original.items()
    )
    call = value.publisher.calls[0]
    assert tuple(member.file_name for member in call["members"]) == tuple(
        pointer.member_path for pointer in pointers
    )
    assert call["primary_file"] == "result.json"
    assert call["artifact_type"] == "control_embedding_reference_query"
    assert call["manifest_version"] == "control-file-set/1.0"
    assert call["idempotency_key"].startswith("embedding-reference-query-artifact:")
    assert set(call) == {
        "members",
        "primary_file",
        "artifact_type",
        "manifest_version",
        "idempotency_key",
        "source_commit",
        "created_at",
    }
    assert not hasattr(published, "admitted") and not hasattr(published, "vectors")
    with pytest.raises(FrozenInstanceError):
        cast(Any, published).owner_job_id = "changed"


def test_same_key_replay_preserves_members_and_owner_identity(
    tmp_path: Path, query_case: Case
) -> None:
    value = prepare(tmp_path, query_case)
    first = publish(value)
    epochs = {
        name: (value.workspace / name).stat()
        for name in ("input.json", "result.json", "shard.json", "vectors.f32")
    }
    assert publish(value) == first
    assert len(value.publisher.saved) == 1
    assert all((value.workspace / name).stat() == epoch for name, epoch in epochs.items())


def test_same_key_cannot_replace_valid_output(tmp_path: Path, query_case: Case) -> None:
    owner = FakePublisher()
    first = prepare(tmp_path, query_case, publisher=owner)
    publish(first)
    other = tmp_path / "other"
    other.mkdir(mode=0o700)
    second = prepare(other, query_case, publisher=owner)
    dimension = second.result.shard.dimension
    replace_binary(
        second, struct.pack(f"<{dimension}f", 0.0, 1.0, *([0.0] * (dimension - 2))), rehash=True
    )
    with pytest.raises(EmbeddingArtifactStoreError, match="SYNTHETIC_SAME_KEY_CONFLICT"):
        publish(second)
    assert len(owner.saved) == 1
    assert owner.calls[0]["idempotency_key"] == owner.calls[1]["idempotency_key"]


@pytest.mark.parametrize("field", ["workflow_request", "policy", "bundle", "launch", "request"])
@pytest.mark.parametrize("failure", ["extra", "wrong_type", "hash"])
def test_raw_contract_revalidation_precedes_workspace_reads(
    tmp_path: Path, query_case: Case, field: str, failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = prepare(tmp_path, query_case)
    original = {
        "workflow_request": query_case.request,
        "policy": query_case.policy,
        "bundle": query_case.bundle,
        "launch": query_case.launch,
        "request": query_case.native_input,
    }[field]
    hash_field = {
        "workflow_request": "request_sha256",
        "policy": "policy_sha256",
        "bundle": "bundle_sha256",
        "launch": "association_sha256",
        "request": "request_sha256",
    }[field]
    malformed = (
        "bad"
        if failure == "wrong_type"
        else original.model_copy(
            update={"authority": "forbidden"} if failure == "extra" else {hash_field: sha("0")}
        )
    )

    def no_open(*args: Any, **kwargs: Any) -> int:
        raise AssertionError("context validation must precede filesystem access")

    monkeypatch.setattr(os, "open", no_open)
    with pytest.raises(
        EmbeddingArtifactStoreError, match="EMBEDDING_REFERENCE_QUERY_CONTEXT_INVALID"
    ):
        publish(value, **{field: malformed})
    assert value.publisher.calls == []


@pytest.mark.parametrize(
    "failure",
    [
        "purpose",
        "input_v1",
        "batch_bool",
        "threads_bool",
        "space_purpose",
        "recipe",
        "launch",
        "runtime",
    ],
)
def test_model_copy_nested_and_fixed_semantics_are_not_repaired(
    tmp_path: Path, query_case: Case, failure: str
) -> None:
    value = prepare(tmp_path, query_case)
    changes: dict[str, Any]
    if failure in {"batch_bool", "threads_bool"}:
        changes = {
            "request": query_case.native_input.model_copy(
                update={
                    failure.removesuffix("_bool")
                    + ("_size" if failure == "batch_bool" else ""): True
                }
            )
        }
    elif failure == "purpose":
        changes = {
            "workflow_request": query_case.request.model_copy(update={"purpose": "DOCUMENT"})
        }
    elif failure == "input_v1":
        changes = {
            "request": query_case.native_input.model_copy(
                update={"schema_version": "embedding-reference-query-input/1.0"}
            )
        }
    elif failure == "space_purpose":
        spaces = query_case.native_input.spaces.model_copy(
            update={"query": query_case.native_input.spaces.document}
        )
        changes = {"request": query_case.native_input.model_copy(update={"spaces": spaces})}
    elif failure == "recipe":
        recipe = query_case.native_input.recipe.model_copy(update={"recipe_sha256": sha("0")})
        changes = {"request": query_case.native_input.model_copy(update={"recipe": recipe})}
    elif failure == "launch":
        body = query_case.launch.model_dump(mode="json") | {
            "query_request_id": "embeddingquery_" + "0" * 32
        }
        changes = {
            "launch": type(query_case.launch).model_validate(seal(body, "association_sha256"))
        }
    else:
        runtime = query_case.bundle.numerical_runtime.model_copy(
            update={"runtime_sha256": sha("0")}
        )
        changes = {"bundle": query_case.bundle.model_copy(update={"numerical_runtime": runtime})}
    with pytest.raises(
        EmbeddingArtifactStoreError, match="EMBEDDING_REFERENCE_QUERY_CONTEXT_INVALID"
    ):
        publish(value, **changes)
    assert value.publisher.calls == []


@pytest.mark.parametrize("member", ["input.json", "result.json"])
@pytest.mark.parametrize("failure", ["whitespace", "duplicate", "malformed", "array", "stale"])
def test_noncanonical_or_other_request_json_is_not_repaired(
    tmp_path: Path, query_case: Case, member: str, failure: str
) -> None:
    value = prepare(tmp_path, query_case)
    original = (value.workspace / member).read_bytes()
    if failure == "whitespace":
        payload = original + b"\n"
    elif failure == "duplicate":
        payload = b'{"schema_version":"bad",' + original[1:]
    elif failure == "malformed":
        payload = b"{"
    elif failure == "array":
        payload = b"[]"
    else:
        body = json.loads(original)
        body["job_id"] = "job_" + "0" * 32
        payload = canonical_json_bytes(
            seal(body, "request_sha256" if member == "input.json" else "result_sha256")
        )
    write_member(value.workspace / member, payload)
    expected = (
        "EMBEDDING_REFERENCE_QUERY_INPUT_INVALID"
        if member == "input.json"
        else "EMBEDDING_REFERENCE_QUERY_RESULT_INVALID"
    )
    with pytest.raises(EmbeddingArtifactStoreError, match=expected):
        publish(value)
    assert value.publisher.calls == []
    assert (value.workspace / member).read_bytes() == payload


@pytest.mark.parametrize("failure", ["hash", "length", "zero", "nonunit", "nan"])
def test_binary_authoritative_codec_rejects_invalid_without_normalizing(
    tmp_path: Path, query_case: Case, failure: str
) -> None:
    value = prepare(tmp_path, query_case)
    count = value.result.shard.dimension * value.result.shard.row_count
    if failure == "length":
        payload = value.binary[:-4]
    elif failure == "nan":
        payload = struct.pack(f"<{count}f", float("nan"), *([0.0] * (count - 1)))
    elif failure == "zero":
        payload = struct.pack(f"<{count}f", *([0.0] * count))
    else:
        payload = struct.pack(f"<{count}f", 2.0, *([0.0] * (count - 1)))
    replace_binary(value, payload, rehash=failure != "hash")
    with pytest.raises(EmbeddingVectorBinaryError):
        publish(value)
    assert value.publisher.calls == []
    assert (value.workspace / "vectors.f32").read_bytes() == payload


@pytest.mark.parametrize("failure", ["extra", "deep_json"])
def test_result_schema_and_decoder_failures_are_content_free(
    tmp_path: Path, query_case: Case, failure: str
) -> None:
    value = prepare(tmp_path, query_case)
    if failure == "deep_json":
        payload = b"[" * 2000 + b"0" + b"]" * 2000
    else:
        body = value.result.model_dump(mode="json") | {"authority": "forbidden"}
        payload = canonical_json_bytes(seal(body, "result_sha256"))
    write_member(value.workspace / "result.json", payload)
    with pytest.raises(
        EmbeddingArtifactStoreError, match="EMBEDDING_REFERENCE_QUERY_RESULT_INVALID"
    ):
        publish(value)
    assert value.publisher.calls == []
    assert (value.workspace / "result.json").read_bytes() == payload


def test_conflicting_shard_is_preserved(tmp_path: Path, query_case: Case) -> None:
    value = prepare(tmp_path, query_case)
    payload = canonical_json_bytes(value.result.shard.model_dump(mode="json")) + b"\n"
    write_member(value.workspace / "shard.json", payload)
    with pytest.raises(
        EmbeddingArtifactStoreError, match="EMBEDDING_REFERENCE_QUERY_SHARD_CONFLICT"
    ):
        publish(value)
    assert value.publisher.calls == []
    assert (value.workspace / "shard.json").read_bytes() == payload


@pytest.mark.parametrize("member", ["input.json", "result.json", "vectors.f32"])
@pytest.mark.parametrize("failure", ["missing", "mode", "link", "hardlink", "directory"])
def test_protected_input_and_output_members_before_publication(
    tmp_path: Path, query_case: Case, member: str, failure: str
) -> None:
    value = prepare(tmp_path, query_case)
    target = value.workspace / member
    if failure == "mode":
        target.chmod(0o640)
    else:
        target.rename(tmp_path / "preserved-member")
        if failure == "link":
            target.symlink_to(tmp_path / "preserved-member")
        elif failure == "hardlink":
            target.hardlink_to(tmp_path / "preserved-member")
        elif failure == "directory":
            target.mkdir(mode=0o700)
    with pytest.raises(EmbeddingArtifactStoreError, match="EMBEDDING_ARTIFACT_MEMBER_INVALID"):
        publish(value)
    assert value.publisher.calls == []


@pytest.mark.parametrize("member", ["input.json", "result.json", "shard.json", "vectors.f32"])
@pytest.mark.parametrize("failure", ["mode", "replacement"])
def test_all_member_fds_remain_held_through_publication(
    tmp_path: Path, query_case: Case, member: str, failure: str
) -> None:
    value = prepare(tmp_path, query_case)

    def mutate() -> None:
        target = value.workspace / member
        if failure == "mode":
            target.chmod(0o640)
        else:
            payload = target.read_bytes()
            target.rename(tmp_path / "preserved-member")
            write_member(target, payload)

    value.publisher.before_return = mutate
    with pytest.raises(EmbeddingArtifactStoreError, match="EMBEDDING_ARTIFACT_MEMBER_CHANGED"):
        publish(value)
    assert len(value.publisher.calls) == 1


def test_workspace_replacement_is_not_adopted(tmp_path: Path, query_case: Case) -> None:
    value = prepare(tmp_path, query_case)

    def mutate() -> None:
        value.workspace.rename(tmp_path / "preserved-workspace")
        value.workspace.mkdir(mode=0o700)

    value.publisher.before_return = mutate
    with pytest.raises(EmbeddingArtifactStoreError):
        publish(value)
    assert len(value.publisher.calls) == 1


@pytest.mark.parametrize(
    "field",
    [
        "job_id",
        "artifact_id",
        "artifact_revision_id",
        "manifest_sha256",
        "primary_file",
        "primary_sha256",
    ],
)
def test_malformed_publication_receipt_is_not_returned(
    tmp_path: Path, query_case: Case, field: str
) -> None:
    value = prepare(tmp_path, query_case)
    value.publisher.receipt_updates[field] = "bad"
    with pytest.raises(
        EmbeddingArtifactStoreError, match="EMBEDDING_REFERENCE_QUERY_RECEIPT_INVALID"
    ):
        publish(value)
    assert len(value.publisher.calls) == 1


def test_wrong_receipt_type_is_stable_error(tmp_path: Path, query_case: Case) -> None:
    class NullPublisher(FakePublisher):
        def publish(self, **kwargs: Any) -> PublishedControlFileSet:
            super().publish(**kwargs)
            return cast(PublishedControlFileSet, None)

    value = prepare(tmp_path, query_case, publisher=NullPublisher())
    with pytest.raises(
        EmbeddingArtifactStoreError, match="EMBEDDING_REFERENCE_QUERY_RECEIPT_INVALID"
    ):
        publish(value)
    assert len(value.publisher.calls) == 1


def test_job_concepts_do_not_require_arbitrary_inequality(tmp_path: Path, query_case: Case) -> None:
    value = prepare(tmp_path, query_case)
    value.publisher.receipt_updates["job_id"] = query_case.native_input.job_id
    result = publish(value)
    assert result.owner_job_id == result.logical_query_job_id


def test_unknown_publication_outcome_is_not_automatically_retried(
    tmp_path: Path, query_case: Case
) -> None:
    class UnknownOutcomePublisher(FakePublisher):
        def publish(self, **kwargs: Any) -> PublishedControlFileSet:
            super().publish(**kwargs)
            raise RuntimeError("synthetic unknown publication outcome")

    value = prepare(tmp_path, query_case, publisher=UnknownOutcomePublisher())
    with pytest.raises(RuntimeError, match="synthetic unknown publication outcome"):
        publish(value)
    assert len(value.publisher.calls) == len(value.publisher.saved) == 1
    assert (value.workspace / "input.json").exists()


@pytest.mark.parametrize(
    "timestamp",
    [
        NOW - timedelta(seconds=1),
        datetime(2026, 10, 12),
        NOW.astimezone(timezone(timedelta(hours=9))),
        True,
        NOW.isoformat(),
    ],
)
def test_publication_timestamp_is_actual_utc_not_before_launch(
    tmp_path: Path, query_case: Case, timestamp: object
) -> None:
    value = prepare(tmp_path, query_case)
    with pytest.raises(
        EmbeddingArtifactStoreError, match="EMBEDDING_REFERENCE_QUERY_CONTEXT_INVALID"
    ):
        publish(value, created_at=timestamp)
    assert value.publisher.calls == []
