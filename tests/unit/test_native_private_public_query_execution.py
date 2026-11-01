"""Common numerical2 through the existing private local files and fixed unit seam."""

import json
from contextlib import contextmanager
from dataclasses import replace

import pytest
from eom_catalog_contracts.embedding_private_chat_query import parse_private_numerical_query_result
from eom_catalog_service import embedding_native_stdio as descriptors
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator import native_private_chat_query_handoff as handoff
from eom_workflow.private_chat_query_execution_v2 import (
    PrivateChatQueryExecutionPolicyV2,
    PrivateChatQueryWorkflowRequestV2,
)
from eom_workflow.private_chat_query_publication import PrivateChatQueryLaunchAssociation

from tests.unit import test_native_private_chat_query_execution as cases
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend
from tests.unit.test_embedding_private_chat_query import private_descriptors as private_descriptors
from tests.unit.test_native_embedding_query_handoff import prepared as reference_prepared
from tests.unit.test_native_private_chat_query_execution import staged as staged
from tests.unit.test_private_chat_public_query_execution import native
from tests.unit.test_private_chat_public_query_workflow import public_completed as public_completed
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_workflow import completed as completed


@pytest.fixture
def prepared(public_completed):
    value = public_completed
    resources = reference_prepared().workflow_request.resource_profile
    policy = PrivateChatQueryExecutionPolicyV2.model_validate(
        seal(
            value.policy.model_dump(mode="json")
            | {"resource_profile": resources.model_dump(mode="json")},
            "policy_sha256",
        )
    )
    request = PrivateChatQueryWorkflowRequestV2.model_validate(
        seal(
            value.request.model_dump(mode="json")
            | {
                "resource_profile": resources.model_dump(mode="json"),
                "native_execution_policy": value.request.native_execution_policy.model_dump(
                    mode="json"
                )
                | {"sha256": sha256_bytes(canonical_json_bytes(policy))},
                "native_execution_policy_sha256": policy.policy_sha256,
            },
            "request_sha256",
        )
    )
    numerical = native(request, policy, value.bundle).native
    launch = PrivateChatQueryLaunchAssociation.model_validate(
        seal(
            value.launch.model_dump(mode="json")
            | {
                "workflow_request_sha256": request.request_sha256,
                "resource_profile_sha256": resources.resource_profile_sha256,
                "query_request_sha256": numerical.request_sha256,
                "query_input_set_sha256": numerical.input_set_sha256,
            },
            "association_sha256",
        )
    )
    return handoff.PreparedNativePrivateChatQuery(
        numerical.job_id.removeprefix("job_"), request, policy, value.bundle, launch, numerical
    )


def test_common_private_control_set_stays_local_and_replays_without_replacing_files(staged):
    cases.test_exact_five_controls_and_marking_replay_keep_private_question_local(staged)
    assert staged.request.schema_version == "embedding-reference-query-input/2.0"
    assert "2 m/s와 3 m/s는 같지 않다" not in repr(staged)


@pytest.mark.parametrize(
    "member", ["workflow.json", "policy.json", "bundle.json", "association.json", "input.json"]
)
@pytest.mark.parametrize("fault", ["bytes", "symlink", "mode"])
def test_private2_control_epoch_hash_and_mode_cannot_be_overwritten(staged, member, fault):
    cases.test_changed_local_control_cannot_be_overwritten_or_marked(staged, member, fault)


@pytest.mark.parametrize("fault", ["id", "reference", "resource", "native_bool"])
def test_private2_copied_values_and_reference_workflow_cannot_borrow_private_admission(
    prepared, fault
):
    cases.test_prepared_revalidates_copied_values_and_cannot_borrow_reference_purpose(
        prepared, fault
    )


def test_private2_original_mark_transfers_only_its_numeric_input(staged, monkeypatch):
    cases.test_root_handoff_requires_original_mark_and_only_transfers_native_input(
        staged, monkeypatch
    )


def test_private2_numerical_result_and_l2_row_materialize_exactly_once(staged, monkeypatch):
    cases.test_exact_private_result_hash_finite_l2_row_and_local_publication_inputs(
        staged, monkeypatch
    )


def test_private2_handoff_uses_private_artifact_owner_without_committing_question(
    staged, monkeypatch
):
    cases.test_private_handoff_result_uses_existing_artifact_owner_without_committing_input(
        staged, monkeypatch
    )


@pytest.mark.parametrize("fault", ["json", "noncanonical", "job", "vectors", "extra_row"])
def test_private2_changed_result_never_becomes_publication_material(staged, monkeypatch, fault):
    cases.test_changed_result_is_never_materialized_for_commit(staged, monkeypatch, fault)


@pytest.mark.parametrize("replay", [False, True])
def test_private2_uses_the_same_fixed_private_unit_and_exact_terminal_replay(
    staged, tmp_path, monkeypatch, replay
):
    cases.test_shared_lifecycle_one_private_start_or_exact_terminal_read(
        staged, tmp_path, monkeypatch, replay
    )


@pytest.mark.parametrize("fault", [None, "failed", "invocation", "order", "boot", "runtime"])
def test_private2_completion_requires_actual_matching_successful_unit_observations(
    prepared, monkeypatch, fault
):
    cases.test_private_checkpoint_completion_requires_exact_successful_unit_observation(
        prepared, monkeypatch, fault
    )


@pytest.mark.parametrize("state", ["running", "failed", "timeout"])
def test_private2_uncertain_original_unit_is_never_started_again(
    staged, tmp_path, monkeypatch, state
):
    cases.test_private_uncertain_or_failed_original_handle_never_starts(
        staged, tmp_path, monkeypatch, state
    )


def test_private2_result_cannot_be_replaced_by_a_valid_legacy_result(
    staged, monkeypatch, completed
):
    root, _encoded = cases.runtime_output(staged, monkeypatch)
    (root / "result.json").write_bytes(canonical_json_bytes(completed.result))
    with pytest.raises(handoff.NativePrivateQueryHandoffError, match="OUTPUT_INVALID"):
        handoff.materialize_native_private_query_output(staged)
    assert not (staged.workspace / "result.json").exists()
    assert not (staged.workspace / "vectors.f32").exists()


@pytest.mark.parametrize("field", ["workflow_request", "policy", "request"])
def test_new_private_handoff_never_mixes_the_legacy_request_policy_or_numeric_input(
    prepared, completed, field
):
    previous = {
        "workflow_request": completed.request,
        "policy": completed.policy,
        "request": completed.native,
    }
    with pytest.raises(handoff.NativePrivateQueryHandoffError, match="INPUT_INVALID"):
        replace(prepared, **{field: previous[field]})


def test_private2_fd_leaf_produces_common_result_and_no_question_in_output(
    private_descriptors, tmp_path, prepared
):
    (tmp_path / "input.json").write_bytes(canonical_json_bytes(prepared.request))
    backend = SyntheticNativeBackend(prepared.request.spaces.query)
    backend.batch_size, backend.threads = prepared.request.batch_size, prepared.request.threads

    @contextmanager
    def scope():
        yield backend

    descriptors.run_native_supported_private_chat_query_descriptors(private_descriptors, scope)
    raw = (tmp_path / "result.json").read_bytes()
    result = parse_private_numerical_query_result(prepared.request, json.loads(raw))
    assert result.schema_version == "embedding-reference-query-result/2.0"
    assert canonical_json_bytes(result) == raw and canonical_json_bytes(TEXT) not in raw
    assert len((tmp_path / "vectors.f32").read_bytes()) == result.shard.dimension * 4
    assert backend.calls == [((TEXT,), "QUERY")]


def test_released_private1_fd_leaf_is_still_closed_to_common2(
    private_descriptors, tmp_path, prepared
):
    (tmp_path / "input.json").write_bytes(canonical_json_bytes(prepared.request))

    @contextmanager
    def forbidden():
        pytest.fail("legacy private1 must not construct common2 model work")
        yield

    with pytest.raises(descriptors.NativeEmbeddingHandoffError):
        descriptors.run_native_private_chat_query_descriptors(private_descriptors, forbidden)
    assert (tmp_path / "result.json").read_bytes() == (tmp_path / "vectors.f32").read_bytes() == b""


@pytest.mark.parametrize("fault", ["input_hash", "extra", "duplicate", "unknown", "oversized"])
def test_private2_invalid_fd_inputs_never_construct_model_or_write_results(
    private_descriptors, tmp_path, prepared, fault
):
    body = prepared.request.model_dump(mode="json")
    if fault == "input_hash":
        body["request_sha256"] = "sha256:" + "f" * 64
    elif fault == "extra":
        body["authority"] = TEXT
    elif fault == "unknown":
        body["schema_version"] = "embedding-reference-query-input/3.0"
    elif fault == "oversized":
        body["unexpected"] = "x" * descriptors.MAX_REFERENCE_QUERY_BYTES
    raw = canonical_json_bytes(body)
    if fault == "duplicate":
        raw = raw[:-1] + b',"job_id":"job_' + b"f" * 32 + b'"}'
    (tmp_path / "input.json").write_bytes(raw)

    @contextmanager
    def forbidden():
        pytest.fail("invalid input must not construct model work")
        yield

    with pytest.raises(descriptors.NativeEmbeddingHandoffError) as caught:
        descriptors.run_native_supported_private_chat_query_descriptors(
            private_descriptors, forbidden
        )
    assert TEXT not in str(caught.value)
    assert (tmp_path / "result.json").read_bytes() == (tmp_path / "vectors.f32").read_bytes() == b""
