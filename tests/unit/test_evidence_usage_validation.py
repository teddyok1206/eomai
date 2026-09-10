from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, cast

import pytest
from eom_catalog_contracts import EvidenceBundleManifestV2
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.control_models import (
    ExecutionBundleRevisionRecord,
    ResolvedExecutionPlanRecord,
)
from eom_orchestrator.evidence_usage_validation import (
    EvidenceUsageValidationError,
    _validate_citations,
    _validated_context_evidence_ids,
    canonical_citation_set_sha256,
    evidence_receipt_event_data,
    evidence_receipt_required_for_result,
    validate_evidence_usage_for_commit,
)
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_workflow import (
    EvidenceResultArtifactPointer,
    validate_control_contract,
)
from eom_workflow.control_plane import (
    AuthoringEvidenceUsageValidationReceipt,
    ReviewEvidenceUsageValidationReceipt,
)
from eom_workflow.models import (
    ArtifactPointer,
    ArtifactSpec,
    ContentTeamAuthoringRoleResultV10,
    ContentTeamImageRoleResultV10,
    ContentTeamRegistrationRoleResultV10,
    ContentTeamReviewRoleResultV10,
    EvidenceUsageCitationV1,
    RoleWorkerInput,
    WorkerRequest,
)
from eom_workflow.schemas import validate_role_result
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from tests.unit.test_content_team_v3_protocol import _content_v3, _envelope, _image_result
from tests.unit.test_execution_materializer import (
    FakeSession,
)
from tests.unit.test_execution_materializer import (
    _knowledge_fixture as _base_knowledge_fixture,
)

EVIDENCE_ID = "evidenceitem_" + "3" * 32
AUTHORING_JOB_ID = "job_" + "7" * 32
AUTHORING_ARTIFACT_ID = "artifact_" + "7" * 32
AUTHORING_REVISION_ID = "rev_" + "7" * 32
REVIEW_JOB_ID = "job_" + "8" * 32
REVIEW_ARTIFACT_ID = "artifact_" + "8" * 32
REVIEW_REVISION_ID = "rev_" + "8" * 32


def _knowledge_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    return _base_knowledge_fixture(
        tmp_path,
        monkeypatch,
        workflow_definition_version="1.10.0",
    )


def _usage(
    fixture: dict[str, Any],
    *,
    path: str = "/stem",
    citation_changes: Mapping[str, object] | None = None,
    usage_changes: Mapping[str, object] | None = None,
) -> dict[str, object]:
    manifest = fixture["manifest"]
    citation: dict[str, object] = {
        "evidence_id": EVIDENCE_ID,
        "anchor_ids": ["anchor_item"],
        "application": "STRUCTURE_PATTERN",
        "application_description": "Pinned item structure informed this authored sentence.",
        "draft_json_paths": [path],
    }
    citation.update(citation_changes or {})
    usage: dict[str, object] = {
        "schema_version": "evidence-usage/1.0",
        "evidence_bundle_id": manifest["evidence_bundle_id"],
        "evidence_bundle_revision_id": manifest["evidence_bundle_revision_id"],
        "retrieval_request_id": manifest["retrieval_request_id"],
        "graph_snapshot_revision_id": manifest["graph_snapshot"]["graph_snapshot_revision_id"],
        "evidence_manifest_sha256": manifest["manifest_sha256"],
        "evidence_context_sha256": sha256_bytes(fixture["context_payload"]),
        "citations": [citation],
    }
    usage.update(usage_changes or {})
    return usage


def _authoring_result(
    fixture: dict[str, Any],
    *,
    path: str = "/stem",
    citation_changes: Mapping[str, object] | None = None,
    usage_changes: Mapping[str, object] | None = None,
) -> ContentTeamAuthoringRoleResultV10:
    return ContentTeamAuthoringRoleResultV10.model_validate(
        {
            "job_id": AUTHORING_JOB_ID,
            "workflow_id": fixture["session"]
            .records[(ResolvedExecutionPlanRecord, str(fixture["plan_id"]))]
            .canonical_document["workflow_id"],
            "step_run_id": "steprun_" + "7" * 32,
            "role": "authoring",
            "artifact": ArtifactSpec(
                logical_artifact_id=AUTHORING_ARTIFACT_ID,
                revision_id=AUTHORING_REVISION_ID,
            ),
            "completed_at": datetime(2026, 9, 10, tzinfo=UTC),
            "output": {
                "draft": _content_v3().model_dump(mode="json"),
                "metadata": {
                    "subject": "통합과학",
                    "topic": "근거 사용 검증",
                    "difficulty": "medium",
                    "knowledge_source_mode": "graph_grounded",
                },
                "evidence_usage": _usage(
                    fixture,
                    path=path,
                    citation_changes=citation_changes,
                    usage_changes=usage_changes,
                ),
            },
        }
    )


def _authoring_input(result: ContentTeamAuthoringRoleResultV10) -> RoleWorkerInput:
    return RoleWorkerInput(
        protocol_version="workflow-role/1.20.0",
        job_id=result.job_id,
        workflow_id=result.workflow_id,
        step_run_id=result.step_run_id,
        attempt=1,
        role="authoring",
        request=WorkerRequest(request_name="GENERATED_KNOWLEDGE_ITEM_REQUEST", image_mode="skip"),
        upstream_artifacts=(),
        artifact=result.artifact,
    )


def _result_pointer(
    result: ContentTeamAuthoringRoleResultV10 | ContentTeamReviewRoleResultV10,
) -> EvidenceResultArtifactPointer:
    schema = (
        "authoring-result@10.0"
        if isinstance(result, ContentTeamAuthoringRoleResultV10)
        else "review-result@10.0"
    )
    return EvidenceResultArtifactPointer(
        logical_artifact_id=result.artifact.logical_artifact_id,
        revision_id=result.artifact.revision_id,
        content_hash=sha256_bytes(canonical_json_bytes(result.model_dump(mode="json"))),
        result_schema=cast(Literal["authoring-result@10.0", "review-result@10.0"], schema),
    )


def _validate_authoring(
    fixture: dict[str, Any], result: ContentTeamAuthoringRoleResultV10
) -> AuthoringEvidenceUsageValidationReceipt:
    receipt = validate_evidence_usage_for_commit(
        fixture["session"],
        plan_id=str(fixture["plan_id"]),
        step_key="authoring",
        worker_input=_authoring_input(result),
        result=result,
        result_artifact=_result_pointer(result),
        canonical_artifact_root=fixture["artifact_root"],
    )
    assert isinstance(receipt, AuthoringEvidenceUsageValidationReceipt)
    return receipt


def test_authoring_receipt_is_exact_self_hashed_and_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _knowledge_fixture(tmp_path, monkeypatch)
    result = _authoring_result(fixture)

    first = _validate_authoring(fixture, result)
    second = _validate_authoring(fixture, result)

    assert first == second
    assert (
        first.plan_sha256
        == fixture["session"]
        .records[(ResolvedExecutionPlanRecord, str(fixture["plan_id"]))]
        .plan_sha256
    )
    assert first.evidence_manifest_artifact.sha256 == sha256_bytes(fixture["manifest_payload"])
    assert first.evidence_manifest_sha256 == fixture["manifest"]["manifest_sha256"]
    usage = result.output.evidence_usage
    assert usage is not None
    assert first.authoring_citation_set_sha256 == canonical_citation_set_sha256(usage.citations)
    event_data = evidence_receipt_event_data(
        result,
        first,
        logical_artifact_id=result.artifact.logical_artifact_id,
        revision_id=result.artifact.revision_id,
        content_hash=_result_pointer(result).content_hash,
    )
    persisted_receipt = event_data["evidence_usage_validation_receipt"]
    assert isinstance(persisted_receipt, dict)
    assert (
        persisted_receipt["result_artifact"]["content_hash"] == _result_pointer(result).content_hash
    )
    validate_control_contract("evidence-usage-validation-receipt", first.model_dump(mode="json"))
    wrong = first.model_dump(mode="json")
    wrong["receipt_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(ValidationError, match="receipt hash differs"):
        AuthoringEvidenceUsageValidationReceipt.model_validate(wrong)
    wrong_pointer = first.model_dump(mode="json")
    wrong_pointer["evidence_context_artifact"]["member_path"] = "evidence/other.md"
    with pytest.raises(JsonSchemaValidationError):
        validate_control_contract("evidence-usage-validation-receipt", wrong_pointer)


def test_all_four_at10_role_wrappers_pass_schema_and_typed_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _knowledge_fixture(tmp_path, monkeypatch)
    authoring = _authoring_result(fixture).model_dump(mode="json")
    image = _image_result().model_dump(mode="json")
    image["protocol_version"] = "workflow-role/1.20.0"
    review = ContentTeamReviewRoleResultV10.model_validate(
        {
            **_envelope("review", seed=3),
            "protocol_version": "workflow-role/1.20.0",
            "output": {
                "review": {
                    "decision": "ready_for_human",
                    "findings": [],
                    "summary": "No Graph evidence was claimed in this generic schema check.",
                },
                "evidence_usage_attestation": None,
            },
        }
    ).model_dump(mode="json")
    registration = ContentTeamRegistrationRoleResultV10.model_validate(
        {
            **_envelope("item_management", seed=4),
            "protocol_version": "workflow-role/1.20.0",
            "output": {
                "registration": {
                    "result": "ready_for_registration",
                    "summary": "The validated pointer is ready for registration.",
                }
            },
        }
    ).model_dump(mode="json")
    cases = (
        ("authoring", "authoring-result@10.0", authoring, ContentTeamAuthoringRoleResultV10),
        ("image", "image-result@10.0", image, ContentTeamImageRoleResultV10),
        ("review", "review-result@10.0", review, ContentTeamReviewRoleResultV10),
        (
            "item_management",
            "registration-result@10.0",
            registration,
            ContentTeamRegistrationRoleResultV10,
        ),
    )
    for role, schema_id, document, expected_type in cases:
        assert isinstance(validate_role_result(document, role, schema_id), expected_type)


def test_evidence_step_rejects_ungrounded_authoring_without_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _knowledge_fixture(tmp_path, monkeypatch)
    document = _authoring_result(fixture).model_dump(mode="json")
    document["output"]["metadata"]["knowledge_source_mode"] = "general_model_knowledge"
    document["output"]["evidence_usage"] = None
    result = ContentTeamAuthoringRoleResultV10.model_validate(document)
    with pytest.raises(EvidenceUsageValidationError, match="evidence usage is missing"):
        _validate_authoring(fixture, result)


def test_unpinned_workflow_cannot_claim_graph_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _knowledge_fixture(tmp_path, monkeypatch)
    result = _authoring_result(fixture)
    with pytest.raises(EvidenceUsageValidationError, match="without a pinned evidence step"):
        validate_evidence_usage_for_commit(
            fixture["session"],
            plan_id=None,
            step_key="authoring",
            worker_input=_authoring_input(result),
            result=result,
            result_artifact=_result_pointer(result),
            canonical_artifact_root=fixture["artifact_root"],
        )


def test_graph_claim_marks_atomic_commit_receipt_as_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _knowledge_fixture(tmp_path, monkeypatch)
    result = _authoring_result(fixture)
    assert evidence_receipt_required_for_result(result)
    commit_calls: list[str] = []
    with pytest.raises(EvidenceUsageValidationError, match="exactly one validation receipt"):
        evidence_receipt_event_data(
            result,
            None,
            logical_artifact_id=result.artifact.logical_artifact_id,
            revision_id=result.artifact.revision_id,
            content_hash=_result_pointer(result).content_hash,
        )
        commit_calls.append("NAS_COMMIT")
    assert commit_calls == []


def test_at10_result_cannot_reinterpret_historical_v3_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _base_knowledge_fixture(tmp_path, monkeypatch)
    result = _authoring_result(fixture)
    with pytest.raises(EvidenceUsageValidationError, match=r"immutable 1\.10 workflow family"):
        _validate_authoring(fixture, result)


@pytest.mark.parametrize(
    ("field_path", "value"),
    [
        (("plan_id",), "execplan_" + "9" * 32),
        (("retrieval_request_sha256",), "sha256:" + "9" * 64),
        (("graph_snapshot", "manifest_sha256"), "sha256:" + "9" * 64),
        (("evidence_manifest_artifact", "sha256"), "sha256:" + "9" * 64),
        (("evidence_context_artifact", "sha256"), "sha256:" + "9" * 64),
    ],
)
def test_commit_validation_reloads_and_rejects_stale_plan_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field_path: tuple[str, ...],
    value: str,
) -> None:
    fixture = _knowledge_fixture(tmp_path, monkeypatch)
    result = _authoring_result(fixture)
    record = fixture["session"].records[(ResolvedExecutionPlanRecord, str(fixture["plan_id"]))]
    document = deepcopy(record.canonical_document)
    target = document
    for segment in field_path[:-1]:
        target = target[segment]
    target[field_path[-1]] = value
    document["plan_sha256"] = content_sha256(
        {key: item for key, item in document.items() if key != "plan_sha256"}
    )
    record.canonical_document = document
    record.plan_sha256 = document["plan_sha256"]

    with pytest.raises(EvidenceUsageValidationError):
        _validate_authoring(fixture, result)


def test_authorization_contract_failure_is_normalized_as_result_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _knowledge_fixture(tmp_path, monkeypatch)
    result = _authoring_result(fixture)
    plan = (
        fixture["session"]
        .records[(ResolvedExecutionPlanRecord, str(fixture["plan_id"]))]
        .canonical_document
    )
    instruction_revision_id = plan["steps"][0]["instruction_bundle"]["bundle_revision_id"]
    bundle = fixture["session"].records[(ExecutionBundleRevisionRecord, instruction_revision_id)]
    bundle.canonical_document = {}

    with pytest.raises(
        EvidenceUsageValidationError, match="pinned evidence material cannot be re-resolved"
    ) as captured:
        _validate_authoring(fixture, result)
    assert captured.value.code == "EVIDENCE_MATERIAL_RESOLUTION_FAILED"


@pytest.mark.parametrize(
    "path",
    [
        "/score_display",
        "/visual_layout",
        "/equation_sources/0",
        "/choices",
        "/choices/01/text",
        "/choices/9/text",
        "/choices/0/missing",
        "/stem/value",
    ],
)
def test_authoring_rejects_nonsemantic_nonleaf_and_unresolved_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    fixture = _knowledge_fixture(tmp_path, monkeypatch)
    with pytest.raises(EvidenceUsageValidationError):
        _validate_authoring(fixture, _authoring_result(fixture, path=path))


@pytest.mark.parametrize(
    "citation_changes",
    [
        {"evidence_id": "evidenceitem_" + "9" * 32},
        {"anchor_ids": ["anchor_unknown"]},
        {"application": "CONCEPT_GROUNDING"},
    ],
)
def test_authoring_rejects_unknown_or_semantically_mismatched_citation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    citation_changes: dict[str, object],
) -> None:
    fixture = _knowledge_fixture(tmp_path, monkeypatch)
    with pytest.raises(EvidenceUsageValidationError):
        _validate_authoring(
            fixture,
            _authoring_result(fixture, citation_changes=citation_changes),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("evidence_bundle_id", "evidence_" + "9" * 32),
        ("evidence_bundle_revision_id", "evidencerev_" + "9" * 32),
        ("retrieval_request_id", "retrieval_" + "9" * 32),
        ("graph_snapshot_revision_id", "graphrev_" + "9" * 32),
        ("evidence_manifest_sha256", "sha256:" + "9" * 64),
        ("evidence_context_sha256", "sha256:" + "9" * 64),
    ],
)
def test_authoring_rejects_every_stale_usage_pin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
) -> None:
    fixture = _knowledge_fixture(tmp_path, monkeypatch)
    result = _authoring_result(fixture, usage_changes={field: value})
    with pytest.raises(EvidenceUsageValidationError, match="differs from exact plan pins"):
        _validate_authoring(fixture, result)


def test_context_entry_list_must_exactly_match_ranked_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _knowledge_fixture(tmp_path, monkeypatch)
    manifest = EvidenceBundleManifestV2.model_validate(fixture["manifest"])
    with pytest.raises(EvidenceUsageValidationError, match="differ from the manifest"):
        _validated_context_evidence_ids(
            manifest,
            fixture["context_payload"].replace(EVIDENCE_ID.encode(), b"evidenceitem_" + b"9" * 32),
        )


def test_answer_bearing_evidence_cannot_be_used_as_positive_support() -> None:
    entry = SimpleNamespace(
        evidence_id=EVIDENCE_ID,
        relevance_milli=900,
        use="GROUNDING",
        answer_bearing=True,
        anchor_ids=("anchor_item",),
    )
    manifest = SimpleNamespace(entries=(entry,))
    citation = EvidenceUsageCitationV1(
        evidence_id=EVIDENCE_ID,
        anchor_ids=("anchor_item",),
        application="CONCEPT_GROUNDING",
        application_description="This must fail despite an otherwise matching use.",
        draft_json_paths=("/stem",),
    )
    context = (
        f"- `{EVIDENCE_ID}` score=900 use=GROUNDING class=APPROVED_ITEM source=`itemrev_x`\n"
    ).encode()
    with pytest.raises(EvidenceUsageValidationError, match="answer-bearing evidence"):
        _validate_citations(
            cast(Any, manifest),
            context,
            (citation,),
            {"stem": "semantic content"},
        )


def test_usage_model_rejects_noncanonical_citation_collections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _knowledge_fixture(tmp_path, monkeypatch)
    for changes in (
        {"anchor_ids": ["anchor_item", "anchor_item"]},
        {"draft_json_paths": ["/stem", "/stem"]},
        {"draft_json_paths": ["/stem~2bad"]},
    ):
        with pytest.raises(ValidationError):
            _authoring_result(fixture, citation_changes=changes)


def _add_review_step(fixture: dict[str, Any]) -> None:
    record = fixture["session"].records[(ResolvedExecutionPlanRecord, str(fixture["plan_id"]))]
    document = deepcopy(record.canonical_document)
    review = {
        **document["steps"][0],
        "step_key": "review",
        "role": "review",
        "worker_pool_key": "review",
    }
    document["steps"].append(review)
    document["plan_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "plan_sha256"}
    )
    record.canonical_document = document
    record.plan_sha256 = document["plan_sha256"]


def _persist_authoring(
    fixture: dict[str, Any], result: ContentTeamAuthoringRoleResultV10
) -> ArtifactPointer:
    session = fixture["session"]
    assert isinstance(session, FakeSession)
    document = result.model_dump(mode="json")
    payload = canonical_json_bytes(document)
    content_hash = sha256_bytes(payload)
    artifact_root = fixture["artifact_root"] / AUTHORING_ARTIFACT_ID / AUTHORING_REVISION_ID
    artifact_root.mkdir(parents=True)
    (artifact_root / "result.json").write_bytes(payload)
    manifest = {
        "job_id": AUTHORING_JOB_ID,
        "logical_artifact_id": AUTHORING_ARTIFACT_ID,
        "revision_id": AUTHORING_REVISION_ID,
        "content_hash": content_hash,
        "content_bytes": len(payload),
    }
    session.records[(ArtifactRecord, AUTHORING_ARTIFACT_ID)] = SimpleNamespace(
        approved=True, job_id=AUTHORING_JOB_ID
    )
    session.records[(ArtifactRevisionRecord, AUTHORING_REVISION_ID)] = SimpleNamespace(
        approved=True,
        job_id=AUTHORING_JOB_ID,
        logical_artifact_id=AUTHORING_ARTIFACT_ID,
        content_hash=content_hash,
        content_bytes=len(payload),
        nas_path=str(artifact_root),
        manifest=manifest,
        result=document,
    )
    session.records[(JobRecord, AUTHORING_JOB_ID)] = SimpleNamespace(
        logical_artifact_id=AUTHORING_ARTIFACT_ID,
        revision_id=AUTHORING_REVISION_ID,
        request={"workflow_id": result.workflow_id},
    )
    return ArtifactPointer(
        step_key="authoring",
        attempt=1,
        job_id=AUTHORING_JOB_ID,
        logical_artifact_id=AUTHORING_ARTIFACT_ID,
        revision_id=AUTHORING_REVISION_ID,
        content_hash=content_hash,
        result_schema="authoring-result@10.0",
    )


def _review_result(
    fixture: dict[str, Any],
    pointer: ArtifactPointer,
    authoring: ContentTeamAuthoringRoleResultV10,
    *,
    path: str = "/stem",
) -> tuple[RoleWorkerInput, ContentTeamReviewRoleResultV10]:
    usage = authoring.output.evidence_usage
    assert usage is not None
    citations = deepcopy(usage.model_dump(mode="json")["citations"])
    citations[0]["draft_json_paths"] = [path]
    result = ContentTeamReviewRoleResultV10.model_validate(
        {
            "job_id": REVIEW_JOB_ID,
            "workflow_id": authoring.workflow_id,
            "step_run_id": "steprun_" + "8" * 32,
            "role": "review",
            "artifact": ArtifactSpec(
                logical_artifact_id=REVIEW_ARTIFACT_ID,
                revision_id=REVIEW_REVISION_ID,
            ),
            "completed_at": datetime(2026, 9, 10, 1, tzinfo=UTC),
            "output": {
                "review": {
                    "decision": "ready_for_human",
                    "findings": [],
                    "summary": "Exact evidence citations were independently verified.",
                },
                "evidence_usage_attestation": {
                    "schema_version": "evidence-usage-review-attestation/1.0",
                    "decision": "VERIFIED",
                    "authoring_artifact": {
                        "logical_artifact_id": pointer.logical_artifact_id,
                        "revision_id": pointer.revision_id,
                        "content_hash": pointer.content_hash,
                        "result_schema": pointer.result_schema,
                    },
                    "citations": citations,
                },
            },
        }
    )
    worker_input = RoleWorkerInput(
        protocol_version="workflow-role/1.20.0",
        job_id=result.job_id,
        workflow_id=result.workflow_id,
        step_run_id=result.step_run_id,
        attempt=1,
        role="review",
        request=WorkerRequest(request_name="GENERATED_KNOWLEDGE_ITEM_REQUEST", image_mode="skip"),
        upstream_artifacts=(pointer,),
        artifact=result.artifact,
    )
    return worker_input, result


def _validate_review(
    fixture: dict[str, Any],
    worker_input: RoleWorkerInput,
    result: ContentTeamReviewRoleResultV10,
) -> ReviewEvidenceUsageValidationReceipt:
    receipt = validate_evidence_usage_for_commit(
        fixture["session"],
        plan_id=str(fixture["plan_id"]),
        step_key="review",
        worker_input=worker_input,
        result=result,
        result_artifact=_result_pointer(result),
        canonical_artifact_root=fixture["artifact_root"],
    )
    assert isinstance(receipt, ReviewEvidenceUsageValidationReceipt)
    return receipt


def test_review_reloads_exact_authoring_and_attests_same_citations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _knowledge_fixture(tmp_path, monkeypatch)
    _add_review_step(fixture)
    authoring = _authoring_result(fixture)
    pointer = _persist_authoring(fixture, authoring)
    worker_input, result = _review_result(fixture, pointer, authoring)

    receipt = _validate_review(fixture, worker_input, result)

    assert receipt is not None
    assert receipt.step_key == "review"
    assert receipt.authoring_artifact.content_hash == pointer.content_hash
    assert receipt.review_citation_set_sha256 == receipt.authoring_citation_set_sha256
    assert receipt.citation_sets_equal is True


def test_review_rejects_different_but_individually_valid_citations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _knowledge_fixture(tmp_path, monkeypatch)
    _add_review_step(fixture)
    authoring = _authoring_result(fixture)
    pointer = _persist_authoring(fixture, authoring)
    worker_input, result = _review_result(fixture, pointer, authoring, path="/bottom_stem")

    with pytest.raises(
        EvidenceUsageValidationError, match="differ from the exact authoring result"
    ):
        _validate_review(fixture, worker_input, result)


def test_review_rejects_attested_pointer_different_from_worker_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _knowledge_fixture(tmp_path, monkeypatch)
    _add_review_step(fixture)
    authoring = _authoring_result(fixture)
    pointer = _persist_authoring(fixture, authoring)
    worker_input, result = _review_result(fixture, pointer, authoring)
    document = result.model_dump(mode="json")
    document["output"]["evidence_usage_attestation"]["authoring_artifact"]["content_hash"] = (
        "sha256:" + "9" * 64
    )
    mismatched = ContentTeamReviewRoleResultV10.model_validate(document)

    with pytest.raises(EvidenceUsageValidationError, match="differs from its exact authoring"):
        _validate_review(fixture, worker_input, mismatched)


def test_review_rejects_stale_authoring_pointer_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _knowledge_fixture(tmp_path, monkeypatch)
    _add_review_step(fixture)
    authoring = _authoring_result(fixture)
    pointer = _persist_authoring(fixture, authoring)
    stale_document = pointer.model_dump(mode="json")
    stale_document["content_hash"] = "sha256:" + "9" * 64
    stale = ArtifactPointer.model_validate(stale_document)
    worker_input, result = _review_result(fixture, stale, authoring)

    with pytest.raises(EvidenceUsageValidationError, match="pointer is stale"):
        _validate_review(fixture, worker_input, result)


@pytest.mark.parametrize("drift", ["nas_path", "result_bytes", "revision_symlink"])
def test_review_rejects_stale_authoring_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    fixture = _knowledge_fixture(tmp_path, monkeypatch)
    _add_review_step(fixture)
    authoring = _authoring_result(fixture)
    pointer = _persist_authoring(fixture, authoring)
    worker_input, result = _review_result(fixture, pointer, authoring)
    revision = fixture["session"].records[(ArtifactRevisionRecord, AUTHORING_REVISION_ID)]
    if drift == "nas_path":
        revision.nas_path = str(fixture["artifact_root"] / "wrong")
    elif drift == "result_bytes":
        (Path(revision.nas_path) / "result.json").write_bytes(b"{}")
    else:
        revision_root = Path(revision.nas_path)
        actual_root = revision_root.with_name(revision_root.name + "-actual")
        revision_root.rename(actual_root)
        revision_root.symlink_to(actual_root, target_is_directory=True)

    with pytest.raises(EvidenceUsageValidationError):
        _validate_review(fixture, worker_input, result)
