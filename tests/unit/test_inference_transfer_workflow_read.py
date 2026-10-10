"""Purpose read owner checks with synthetic official ports; no DB/NAS/model."""

from __future__ import annotations

from copy import deepcopy

import pytest
from eom_catalog_service.inference_transfer_service import InferenceTransferServiceError
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.control_models import ResolvedExecutionPlanStepRecord
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_workflow_runner.models import WorkflowStepRunRecord
from jsonschema import ValidationError as SchemaError

from tests.unit.inference_transfer_workflow_fixtures import OPERATOR_ID, OTHER_OPERATOR_ID
from tests.unit.inference_transfer_workflow_read_fixtures import owner_fixture, read_request


def test_canonical_member_comes_from_official_loader_not_db_result(monkeypatch):
    fixture = owner_fixture(monkeypatch)
    response = fixture.owner.read(OPERATOR_ID, read_request())
    assert response.result_state == "MEMBER_VERIFIED"
    assert response.result == fixture.role_result.output
    assert response.result_artifact.sha256 == fixture.revision.content_hash
    assert response.result_artifact.sha256 != response.result.result_sha256
    fixture.owner.artifacts.load_json_revision.assert_called_once_with(
        artifact_id=fixture.revision.logical_artifact_id,
        revision_id=fixture.revision.revision_id,
        content_hash=fixture.revision.content_hash,
        max_bytes=128 * 1024,
    )
    assert fixture.owner.source.authorize_pair.call_count == 2
    command, left, right = fixture.owner.source.authorize_pair.call_args.args
    assert command.actor_id == OPERATOR_ID
    assert command.maximum_candidates == 2 and command.top_k == 2
    assert left == fixture.request.left_profile and right == fixture.request.right_profile
    assert response.result.assessment_kind == "MACHINE_HYPOTHESIS_NOT_HUMAN_VERIFICATION"


def test_status_only_closes_pointer_lineage_without_canonical_materialization(monkeypatch):
    fixture = owner_fixture(monkeypatch)
    response = fixture.owner.read(OPERATOR_ID, read_request("STATUS_ONLY"))
    assert response.result_state == "POINTER_ONLY" and response.result is None
    assert response.result_artifact.member_path == "result.json"
    fixture.owner.artifacts.load_json_revision.assert_not_called()
    assert fixture.owner.source.authorize_pair.call_count == 2


@pytest.mark.parametrize("state", ["REQUESTED", "RUNNING", "FAILED", "CANCELLED"])
@pytest.mark.parametrize("mode", ["STATUS_ONLY", "CANONICAL_RESULT"])
def test_noncompleted_status_is_honest_and_never_reads_result_member(monkeypatch, state, mode):
    fixture = owner_fixture(monkeypatch, state)
    fixture.row_lists[WorkflowStepRunRecord] = []
    response = fixture.owner.read(OPERATOR_ID, read_request(mode))
    assert response.result_state == (
        "PENDING" if state in {"REQUESTED", "RUNNING"} else "NO_RESULT"
    )
    assert response.result is None and response.result_artifact is None
    assert "UNTRUSTED_SECRET" not in response.model_dump_json()
    fixture.owner.artifacts.load_json_revision.assert_not_called()
    assert fixture.owner.source.authorize_pair.call_count == 2


def test_pending_without_execution_plan_has_no_fabricated_result(monkeypatch):
    fixture = owner_fixture(monkeypatch, "REQUESTED")
    fixture.workflow.runtime_context = {"artifact_pointers": []}
    response = fixture.owner.read(OPERATOR_ID, read_request())
    assert response.result_state == "PENDING"
    fixture.owner.artifacts.load_json_revision.assert_not_called()


@pytest.mark.parametrize("state", ["REQUESTED", "RUNNING", "COMPLETED"])
def test_partially_stored_plan_pin_is_an_explicit_invalid_result_not_latest(monkeypatch, state):
    fixture = owner_fixture(monkeypatch, state)
    fixture.workflow.runtime_context["execution_plan"].pop("plan_id")
    with pytest.raises(InferenceTransferServiceError, match="INFERENCE_TRANSFER_RESULT_INVALID"):
        fixture.owner.read(OPERATOR_ID, read_request())
    fixture.owner.artifacts.load_json_revision.assert_not_called()


@pytest.mark.parametrize("actor", [OTHER_OPERATOR_ID, "worker_01", "ADMIN"])
def test_actual_owner_only_no_admin_worker_or_other_creator_override(monkeypatch, actor):
    fixture = owner_fixture(monkeypatch)
    with pytest.raises(InferenceTransferServiceError, match="INFERENCE_TRANSFER_FORBIDDEN"):
        fixture.owner.read(actor, read_request())
    fixture.owner.source.authorize_pair.assert_not_called()
    fixture.owner.artifacts.load_json_revision.assert_not_called()


def test_missing_workflow_is_not_latest_or_successful_equivalent(monkeypatch):
    fixture = owner_fixture(monkeypatch)
    with pytest.raises(InferenceTransferServiceError, match="WORKFLOW_NOT_FOUND"):
        fixture.owner.read(OPERATOR_ID, read_request(workflow_id="workflow_" + "9" * 32))
    fixture.owner.artifacts.load_json_revision.assert_not_called()


def test_current_workflow_permission_is_required_in_catalog_not_just_api(monkeypatch):
    fixture = owner_fixture(monkeypatch)
    monkeypatch.setattr(
        "eom_catalog_service.inference_transfer_workflow_read.effective_permissions",
        lambda *_: set(),
    )
    with pytest.raises(InferenceTransferServiceError, match="INFERENCE_TRANSFER_FORBIDDEN"):
        fixture.owner.read(OPERATOR_ID, read_request())
    fixture.owner.source.authorize_pair.assert_not_called()


@pytest.mark.parametrize("at", ["initial", "final"])
def test_generic_workflow_permission_does_not_override_current_source_rights(monkeypatch, at):
    fixture = owner_fixture(monkeypatch)
    failure = InferenceTransferServiceError("INFERENCE_TRANSFER_FORBIDDEN")
    fixture.owner.source.authorize_pair.side_effect = (
        failure if at == "initial" else [None, failure]
    )
    with pytest.raises(InferenceTransferServiceError, match="INFERENCE_TRANSFER_FORBIDDEN"):
        fixture.owner.read(OPERATOR_ID, read_request())
    assert fixture.owner.artifacts.load_json_revision.call_count == (0 if at == "initial" else 1)


@pytest.mark.parametrize(
    ("entity", "attribute", "value"),
    [
        ("workflow", "definition_key", "customer-support"),
        ("workflow", "definition_hash", "sha256:" + "9" * 64),
        ("workflow", "role_schema_version", "workflow-role/1.22.0"),
        ("workflow", "protocol_version", "workflow-role/1.29.0"),
        ("workflow", "request_hash", "sha256:" + "9" * 64),
        ("workflow", "current_step_key", "compare_pair"),
        ("workflow", "rework_cycle_count", 1),
        ("step", "attempt", 2),
        ("step", "worker_role", "review"),
        ("step", "result_schema", "customer-support-result@1.0"),
        ("step", "state", "RUNNING"),
        ("step", "platform_job_id", "job_" + "9" * 32),
        ("step", "superseded_by_step_run_id", "steprun_" + "9" * 32),
        ("job", "status", "RUNNING"),
        ("job", "task_type", "workflow_review"),
        ("job", "protocol_version", "workflow-role/1.22.0"),
        ("job", "request_hash", "sha256:" + "9" * 64),
        ("job", "revision_id", "rev_" + "9" * 32),
        ("job", "worker_slot_id", "05"),
        ("job", "completed_at", None),
        ("artifact", "approved", False),
        ("artifact", "job_id", "job_" + "9" * 32),
        ("artifact", "artifact_type", "workflow_review"),
        ("revision", "approved", False),
        ("revision", "job_id", "job_" + "9" * 32),
        ("revision", "logical_artifact_id", "artifact_" + "9" * 32),
        ("revision", "manifest_hash", "sha256:" + "9" * 64),
        ("revision", "content_hash", "sha256:" + "9" * 64),
        ("revision", "content_bytes", 0),
        ("revision", "content_bytes", 128 * 1024 + 1),
        ("plan", "plan_sha256", "sha256:" + "9" * 64),
        ("plan", "workflow_id", "workflow_" + "9" * 32),
        ("plan", "graph_snapshot_revision_id", "graphrev_" + "9" * 32),
        ("plan", "evidence_bundle_revision_id", "evidencerev_" + "9" * 32),
        ("plan", "preset_revision_id", "execpresetrev_" + "9" * 32),
        ("plan_step", "model", "different-model"),
        ("plan_step", "role", "review"),
        ("plan_step", "network", "enabled"),
    ],
)
def test_exact_lineage_lifecycle_and_pins_are_required_before_member_read(
    monkeypatch, entity, attribute, value
):
    fixture = owner_fixture(monkeypatch)
    setattr(getattr(fixture, entity), attribute, value)
    with pytest.raises(InferenceTransferServiceError, match="INFERENCE_TRANSFER_RESULT_INVALID"):
        fixture.owner.read(OPERATOR_ID, read_request())
    fixture.owner.artifacts.load_json_revision.assert_not_called()


@pytest.mark.parametrize("entity", [JobRecord, ArtifactRecord, ArtifactRevisionRecord])
def test_missing_exact_member_lineage_never_falls_back_to_metadata(monkeypatch, entity):
    fixture = owner_fixture(monkeypatch)
    fixture.rows.pop(entity)
    with pytest.raises(InferenceTransferServiceError, match="INFERENCE_TRANSFER_RESULT_INVALID"):
        fixture.owner.read(OPERATOR_ID, read_request())
    fixture.owner.artifacts.load_json_revision.assert_not_called()


@pytest.mark.parametrize("entity", [WorkflowStepRunRecord, ResolvedExecutionPlanStepRecord])
def test_missing_or_duplicate_steps_are_not_guessed_by_latest(monkeypatch, entity):
    fixture = owner_fixture(monkeypatch)
    fixture.row_lists[entity] *= 2
    with pytest.raises(InferenceTransferServiceError, match="INFERENCE_TRANSFER_RESULT_INVALID"):
        fixture.owner.read(OPERATOR_ID, read_request())
    fixture.owner.artifacts.load_json_revision.assert_not_called()


@pytest.mark.parametrize("container", ["runtime", "terminal", "prompt", "request_payload"])
def test_stored_purpose_pointer_and_prompt_substitution_fails_closed(monkeypatch, container):
    fixture = owner_fixture(monkeypatch)
    if container == "runtime":
        fixture.workflow.runtime_context["artifact_pointers"] = []
    elif container == "terminal":
        fixture.workflow.runtime_context["final_pointer_manifest"]["comparison_result"] = None
    elif container == "prompt":
        fixture.step.input_pointer_manifest["transfer_prompt"]["prompt_sha256"] = (
            "sha256:" + "9" * 64
        )
    else:
        fixture.workflow.request_payload = {}
    with pytest.raises(InferenceTransferServiceError, match="INFERENCE_TRANSFER_RESULT_INVALID"):
        fixture.owner.read(OPERATOR_ID, read_request())
    fixture.owner.artifacts.load_json_revision.assert_not_called()


@pytest.mark.parametrize("mutation", ["hash", "outer_identity", "facet", "protocol"])
def test_canonical_member_reparse_catches_real_payload_drift_not_db_metadata(monkeypatch, mutation):
    fixture = owner_fixture(monkeypatch)
    document = deepcopy(fixture.document)
    if mutation == "hash":
        document["output"]["shared_idea"] = "changed uncommitted result"
    elif mutation == "outer_identity":
        document["job_id"] = "job_" + "9" * 32
    elif mutation == "protocol":
        document["protocol_version"] = "workflow-role/1.22.0"
    else:
        document["output"]["mappings"][0]["facet"] = "DECISIVE_INFERENCE"
        document["output"]["result_sha256"] = content_sha256(
            {k: v for k, v in document["output"].items() if k != "result_sha256"}
        )
    if mutation != "hash":
        # A rehashed member cannot replace independent job or profile facets.
        pointer_sha = content_sha256(document)
        fixture.revision.content_hash = pointer_sha
        fixture.revision.content_bytes = len(canonical_json_bytes(document))
        fixture.revision.manifest.update(
            content_hash=pointer_sha, content_bytes=fixture.revision.content_bytes
        )
        fixture.revision.manifest_hash = content_sha256(fixture.revision.manifest)
        fixture.step.output_pointer_manifest["content_hash"] = pointer_sha
        fixture.workflow.runtime_context["artifact_pointers"][0]["content_hash"] = pointer_sha
        final = fixture.workflow.runtime_context["final_pointer_manifest"]
        final["artifact_pointers"][0]["content_hash"] = pointer_sha
        final["comparison_result"]["content_hash"] = pointer_sha
    fixture.owner.artifacts.load_json_revision.return_value = document
    with pytest.raises((InferenceTransferServiceError, ValueError)):
        fixture.owner.read(OPERATOR_ID, read_request())


def test_canonical_outer_hash_is_checked_after_official_loader_returns(monkeypatch):
    fixture = owner_fixture(monkeypatch)
    fixture.owner.artifacts.load_json_revision.return_value = fixture.revision.result
    with pytest.raises(InferenceTransferServiceError, match="INFERENCE_TRANSFER_RESULT_INVALID"):
        fixture.owner.read(OPERATOR_ID, read_request())


@pytest.mark.parametrize("mutation", ["workflow_version", "artifact_revoked"])
def test_changes_during_member_read_are_observed_before_result_is_returned(monkeypatch, mutation):
    fixture = owner_fixture(monkeypatch)

    def changing_loader(**_):
        if mutation == "workflow_version":
            fixture.workflow.lock_version += 1
        else:
            fixture.revision.approved = False
        return fixture.document

    fixture.owner.artifacts.load_json_revision.side_effect = changing_loader
    with pytest.raises(InferenceTransferServiceError):
        fixture.owner.read(OPERATOR_ID, read_request())


def test_copied_unvalidated_read_request_cannot_skip_public_schema(monkeypatch):
    fixture = owner_fixture(monkeypatch)
    bad = read_request().model_copy(update={"mode": "UNSAFE_LATEST"})
    with pytest.raises((ValueError, SchemaError)):
        fixture.owner.read(OPERATOR_ID, bad)
    fixture.owner.artifacts.load_json_revision.assert_not_called()
