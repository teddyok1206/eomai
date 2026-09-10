from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, NoReturn, cast

import pytest
from eom_catalog_contracts import resolve_integrated_science_curriculum_scope
from eom_catalog_contracts.mock_exam_production_plan import (
    CONTENT_TEAM_ITEM_GUIDANCE,
    CONTENT_TEAM_ITEM_GUIDANCE_SHA256,
)
from eom_catalog_service.evidence_usage_receipts import (
    EvidenceUsageProvenanceExpectation,
    EvidenceUsageReceiptPair,
    EvidenceUsageReceiptResolutionError,
    OrchestratorEvidenceUsageReceiptResolver,
)
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_identifiers import content_sha256
from eom_item_registry import ComponentPointer, RegistrationRequest
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobEventRecord,
    JobRecord,
)
from eom_workflow import (
    ArtifactPointer,
    AuthoringEvidenceUsageValidationReceipt,
    ReviewEvidenceUsageValidationReceipt,
    RoleWorkerInput,
    WorkerRequest,
    WorkflowRequest,
)
from eom_workflow.models import ArtifactSpec
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord

NOW = datetime(2026, 9, 10, tzinfo=UTC)
AUTHORING = ArtifactPointer(
    step_key="authoring",
    attempt=1,
    job_id="job_" + "1" * 32,
    logical_artifact_id="artifact_" + "2" * 32,
    revision_id="rev_" + "3" * 32,
    content_hash="sha256:" + "4" * 64,
    result_schema="authoring-result@10.0",
)
REVIEW = ArtifactPointer(
    step_key="review",
    attempt=1,
    job_id="job_" + "5" * 32,
    logical_artifact_id="artifact_" + "6" * 32,
    revision_id="rev_" + "7" * 32,
    content_hash="sha256:" + "8" * 64,
    result_schema="review-result@10.0",
)
REGISTRATION = ArtifactPointer(
    step_key="registration",
    attempt=1,
    job_id="job_" + "9" * 32,
    logical_artifact_id="artifact_" + "a" * 32,
    revision_id="rev_" + "b" * 32,
    content_hash="sha256:" + "c" * 64,
    result_schema="registration-result@10.0",
)


def _material_pointer(*, manifest: bool) -> dict[str, object]:
    marker = "d" if manifest else "e"
    return {
        "artifact_id": "artifact_" + marker * 32,
        "artifact_revision_id": "rev_" + marker * 32,
        "member_path": "evidence/manifest.json" if manifest else "evidence/context.md",
        "sha256": "sha256:" + marker * 64,
        "schema_ref": (
            "eom://schemas/knowledge/evidence-bundle-manifest/4.0"
            if manifest
            else "eom://schemas/knowledge/evidence-bundle-context/1.0"
        ),
        "media_type": "application/json" if manifest else "text/markdown",
        "logical_name": "evidence-manifest" if manifest else "evidence-context",
    }


def _receipts(*, review_plan_marker: str = "f") -> EvidenceUsageReceiptPair:
    shared: dict[str, object] = {
        "schema_version": "evidence-usage-validation-receipt/1.0",
        "plan_id": "execplan_" + "f" * 32,
        "plan_sha256": "sha256:" + review_plan_marker * 64,
        "evidence_bundle_id": "evidence_" + "1" * 32,
        "evidence_bundle_revision_id": "evidencerev_" + "2" * 32,
        "retrieval_request_id": "retrieval_" + "3" * 32,
        "retrieval_request_sha256": "sha256:" + "4" * 64,
        "graph_snapshot_revision_id": "graphrev_" + "5" * 32,
        "graph_snapshot_sha256": "sha256:" + "6" * 64,
        "evidence_manifest_artifact": _material_pointer(manifest=True),
        "evidence_manifest_sha256": "sha256:" + "7" * 64,
        "evidence_context_artifact": _material_pointer(manifest=False),
    }
    authoring_result = {
        "logical_artifact_id": AUTHORING.logical_artifact_id,
        "revision_id": AUTHORING.revision_id,
        "content_hash": AUTHORING.content_hash,
        "result_schema": AUTHORING.result_schema,
    }
    citation_hash = "sha256:" + "8" * 64
    authoring_value = {
        **shared,
        "plan_sha256": "sha256:" + "f" * 64,
        "step_key": "authoring",
        "result_artifact": authoring_result,
        "authoring_citation_set_sha256": citation_hash,
    }
    authoring = AuthoringEvidenceUsageValidationReceipt.model_validate(
        {**authoring_value, "receipt_sha256": content_sha256(authoring_value)}
    )
    review_value = {
        **shared,
        "step_key": "review",
        "result_artifact": {
            "logical_artifact_id": REVIEW.logical_artifact_id,
            "revision_id": REVIEW.revision_id,
            "content_hash": REVIEW.content_hash,
            "result_schema": REVIEW.result_schema,
        },
        "authoring_artifact": authoring_result,
        "authoring_citation_set_sha256": citation_hash,
        "review_citation_set_sha256": citation_hash,
        "citation_sets_equal": True,
    }
    review = ReviewEvidenceUsageValidationReceipt.model_validate(
        {**review_value, "receipt_sha256": content_sha256(review_value)}
    )
    return EvidenceUsageReceiptPair(authoring=authoring, review=review)


def _replace_review_receipt(
    review: ReviewEvidenceUsageValidationReceipt,
    **changes: object,
) -> ReviewEvidenceUsageValidationReceipt:
    value = review.model_dump(mode="json", exclude={"receipt_sha256"})
    value.update(changes)
    return ReviewEvidenceUsageValidationReceipt.model_validate(
        {**value, "receipt_sha256": content_sha256(value)}
    )


def _record_set(
    pointer: ArtifactPointer,
    receipt: AuthoringEvidenceUsageValidationReceipt | ReviewEvidenceUsageValidationReceipt,
) -> tuple[JobRecord, ArtifactRecord, ArtifactRevisionRecord, JobEventRecord]:
    manifest = {
        "protocol_version": "1.0.1",
        "manifest_version": "1.0.0",
        "job_id": pointer.job_id,
        "logical_artifact_id": pointer.logical_artifact_id,
        "revision_id": pointer.revision_id,
        "content_hash": pointer.content_hash,
        "content_bytes": 100,
        "file_name": "result.json",
        "media_type": "application/json",
        "worker_slot": "01",
        "created_at": NOW.isoformat(),
    }
    job = JobRecord(
        job_id=pointer.job_id,
        protocol_version="workflow-role/1.20.0",
        idempotency_key=f"unit-{pointer.step_key}-receipt",
        request_hash="sha256:" + "0" * 64,
        task_type=f"workflow_{pointer.step_key}",
        request={},
        status="SUCCEEDED",
        logical_artifact_id=pointer.logical_artifact_id,
        revision_id=pointer.revision_id,
        completed_at=NOW,
    )
    artifact = ArtifactRecord(
        logical_artifact_id=pointer.logical_artifact_id,
        job_id=pointer.job_id,
        artifact_type=f"workflow_{pointer.step_key}",
        approved=True,
    )
    revision = ArtifactRevisionRecord(
        revision_id=pointer.revision_id,
        logical_artifact_id=pointer.logical_artifact_id,
        job_id=pointer.job_id,
        content_hash=pointer.content_hash,
        manifest_hash=content_sha256(manifest),
        content_bytes=100,
        nas_path="/not-read-by-unit-test",
        manifest=manifest,
        result={},
        approved=True,
    )
    event = JobEventRecord(
        job_id=pointer.job_id,
        sequence=7,
        from_state="COMMITTING",
        to_state="SUCCEEDED",
        event="ARTIFACT_COMMITTED",
        data={
            "logical_artifact_id": pointer.logical_artifact_id,
            "revision_id": pointer.revision_id,
            "content_hash": pointer.content_hash,
            "evidence_usage_validation_receipt": receipt.model_dump(mode="json"),
        },
    )
    return job, artifact, revision, event


def _worker_input(
    pointer: ArtifactPointer,
    *,
    workflow_id: str,
    step_run_id: str,
) -> RoleWorkerInput:
    return RoleWorkerInput(
        protocol_version="workflow-role/1.20.0",
        job_id=pointer.job_id,
        workflow_id=workflow_id,
        step_run_id=step_run_id,
        attempt=pointer.attempt,
        role=cast(Any, pointer.step_key),
        request=WorkerRequest(
            request_name="GENERATED_KNOWLEDGE_ITEM_REQUEST",
            image_mode="skip",
        ),
        upstream_artifacts=(),
        artifact=ArtifactSpec(
            logical_artifact_id=pointer.logical_artifact_id,
            revision_id=pointer.revision_id,
        ),
    )


def test_trusted_receipt_record_and_pair_bind_exact_artifacts_and_plan() -> None:
    pair = _receipts()
    authoring_records = _record_set(AUTHORING, pair.authoring)
    review_records = _record_set(REVIEW, pair.review)

    authoring = OrchestratorEvidenceUsageReceiptResolver._validate_receipt_record(
        pointer=AUTHORING,
        job=authoring_records[0],
        artifact=authoring_records[1],
        revision=authoring_records[2],
        events=(authoring_records[3],),
    )
    review = OrchestratorEvidenceUsageReceiptResolver._validate_receipt_record(
        pointer=REVIEW,
        job=review_records[0],
        artifact=review_records[1],
        revision=review_records[2],
        events=(review_records[3],),
    )
    resolved = EvidenceUsageReceiptPair(
        authoring=cast(AuthoringEvidenceUsageValidationReceipt, authoring),
        review=cast(ReviewEvidenceUsageValidationReceipt, review),
    )
    OrchestratorEvidenceUsageReceiptResolver._validate_pair(resolved)

    assert resolved.authoring.result_artifact.revision_id == AUTHORING.revision_id
    assert resolved.review.authoring_artifact == resolved.authoring.result_artifact


def test_trusted_receipt_resolution_rejects_duplicate_event_and_stale_chain() -> None:
    pair = _receipts()
    job, artifact, revision, event = _record_set(AUTHORING, pair.authoring)
    with pytest.raises(EvidenceUsageReceiptResolutionError, match="does not resolve"):
        OrchestratorEvidenceUsageReceiptResolver._validate_receipt_record(
            pointer=AUTHORING,
            job=job,
            artifact=artifact,
            revision=revision,
            events=(event, event),
        )

    mismatched = _receipts(review_plan_marker="0")
    with pytest.raises(EvidenceUsageReceiptResolutionError, match="immutable chain"):
        OrchestratorEvidenceUsageReceiptResolver._validate_pair(mismatched)


@pytest.mark.parametrize(
    "case",
    (
        "missing_job",
        "missing_event",
        "missing_event_data",
        "wrong_event_data",
        "extra_event_data",
        "job_state",
        "job_protocol",
        "job_task_type",
        "job_identity",
        "artifact_type",
        "artifact_approval",
        "revision_approval",
        "revision_hash",
        "manifest_hash",
        "manifest_identity",
        "manifest_bytes",
        "receipt_self_hash",
    ),
)
def test_trusted_receipt_record_rejects_missing_stale_or_untrusted_state(case: str) -> None:
    pair = _receipts()
    job, artifact, revision, event = _record_set(AUTHORING, pair.authoring)
    resolved_job: JobRecord | None = job
    events: tuple[JobEventRecord, ...] = (event,)
    if case == "missing_job":
        resolved_job = None
    elif case == "missing_event":
        events = ()
    elif case == "missing_event_data":
        del event.data["evidence_usage_validation_receipt"]
    elif case == "wrong_event_data":
        event.data["revision_id"] = "rev_" + "0" * 32
    elif case == "extra_event_data":
        event.data["untrusted"] = True
    elif case == "job_state":
        job.status = "FAILED"
    elif case == "job_protocol":
        job.protocol_version = "workflow-role/1.19.0"
    elif case == "job_task_type":
        job.task_type = "workflow_review"
    elif case == "job_identity":
        job.revision_id = "rev_" + "0" * 32
    elif case == "artifact_type":
        artifact.artifact_type = "workflow_review"
    elif case == "artifact_approval":
        artifact.approved = False
    elif case == "revision_approval":
        revision.approved = False
    elif case == "revision_hash":
        revision.content_hash = "sha256:" + "0" * 64
    elif case == "manifest_hash":
        revision.manifest_hash = "sha256:" + "0" * 64
    elif case == "manifest_identity":
        revision.manifest["revision_id"] = "rev_" + "0" * 32
        revision.manifest_hash = content_sha256(revision.manifest)
    elif case == "manifest_bytes":
        revision.content_bytes = 101
    elif case == "receipt_self_hash":
        raw_receipt = cast(dict[str, Any], event.data["evidence_usage_validation_receipt"])
        raw_receipt["receipt_sha256"] = "sha256:" + "0" * 64

    with pytest.raises(EvidenceUsageReceiptResolutionError):
        OrchestratorEvidenceUsageReceiptResolver._validate_receipt_record(
            pointer=AUTHORING,
            job=resolved_job,
            artifact=artifact,
            revision=revision,
            events=events,
        )


def test_trusted_receipt_resolution_rejects_wrong_role_schema_or_shared_job() -> None:
    resolver = OrchestratorEvidenceUsageReceiptResolver(cast(Any, None))
    wrong_pairs = (
        (AUTHORING.model_copy(update={"step_key": "review"}), REVIEW),
        (AUTHORING.model_copy(update={"result_schema": "authoring-result@9.0"}), REVIEW),
        (AUTHORING, REVIEW.model_copy(update={"step_key": "authoring"})),
        (AUTHORING, REVIEW.model_copy(update={"result_schema": "review-result@9.0"})),
        (AUTHORING, REVIEW.model_copy(update={"job_id": AUTHORING.job_id})),
    )

    for authoring, review in wrong_pairs:
        with pytest.raises(EvidenceUsageReceiptResolutionError, match="exact @10"):
            resolver.resolve_pair(authoring=authoring, review=review)


def test_trusted_receipt_pair_rejects_material_and_citation_mismatch() -> None:
    pair = _receipts()
    different_context = _material_pointer(manifest=False)
    different_context["artifact_id"] = "artifact_" + "0" * 32
    material_mismatch = EvidenceUsageReceiptPair(
        authoring=pair.authoring,
        review=_replace_review_receipt(pair.review, evidence_context_artifact=different_context),
    )
    different_citation_hash = "sha256:" + "0" * 64
    citation_mismatch = EvidenceUsageReceiptPair(
        authoring=pair.authoring,
        review=_replace_review_receipt(
            pair.review,
            authoring_citation_set_sha256=different_citation_hash,
            review_citation_set_sha256=different_citation_hash,
        ),
    )

    for mismatched in (material_mismatch, citation_mismatch):
        with pytest.raises(EvidenceUsageReceiptResolutionError, match="immutable chain"):
            OrchestratorEvidenceUsageReceiptResolver._validate_pair(mismatched)


def test_mock_exam_receipt_resolution_binds_worker_inputs_plan_and_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_id = "workflow_" + "9" * 32
    authoring_step_run_id = "steprun_" + "1" * 32
    review_step_run_id = "steprun_" + "2" * 32
    pair = _receipts()
    authoring_job = _record_set(AUTHORING, pair.authoring)[0]
    review_job = _record_set(REVIEW, pair.review)[0]
    for job, pointer, step_run_id in (
        (authoring_job, AUTHORING, authoring_step_run_id),
        (review_job, REVIEW, review_step_run_id),
    ):
        worker_input = _worker_input(
            pointer,
            workflow_id=workflow_id,
            step_run_id=step_run_id,
        )
        job.request = worker_input.model_dump(mode="json")
        job.request_hash = content_sha256(
            {
                "protocol_version": job.protocol_version,
                "task_type": job.task_type,
                "request": job.request,
            }
        )
    jobs = {AUTHORING.job_id: authoring_job, REVIEW.job_id: review_job}
    plan = SimpleNamespace(
        plan_id=pair.authoring.plan_id,
        workflow_id=workflow_id,
        preset_id="execpreset_" + "3" * 32,
        preset_revision_id="execpresetrev_" + "4" * 32,
        capacity_policy_revision_id="capacityrev_" + "5" * 32,
        graph_snapshot=SimpleNamespace(
            graph_snapshot_revision_id=pair.authoring.graph_snapshot_revision_id,
            manifest_sha256=pair.authoring.graph_snapshot_sha256,
        ),
        evidence_bundle_id=pair.authoring.evidence_bundle_id,
        evidence_bundle_revision_id=pair.authoring.evidence_bundle_revision_id,
        retrieval_request_id=pair.authoring.retrieval_request_id,
        retrieval_request_sha256=pair.authoring.retrieval_request_sha256,
        evidence_manifest_artifact=pair.authoring.evidence_manifest_artifact,
        evidence_manifest_sha256=pair.authoring.evidence_manifest_sha256,
        evidence_context_artifact=pair.authoring.evidence_context_artifact,
        workflow_definition_key="generic-item-development",
        workflow_definition_version="1.10.0",
        plan_sha256=pair.authoring.plan_sha256,
        resolved_at=NOW,
    )
    plan_record = SimpleNamespace(
        plan_id=plan.plan_id,
        workflow_id=workflow_id,
        preset_id=plan.preset_id,
        preset_revision_id=plan.preset_revision_id,
        capacity_policy_revision_id=plan.capacity_policy_revision_id,
        graph_snapshot_revision_id=plan.graph_snapshot.graph_snapshot_revision_id,
        evidence_bundle_revision_id=plan.evidence_bundle_revision_id,
        plan_sha256=plan.plan_sha256,
        resolved_at=plan.resolved_at,
        canonical_document={},
    )

    class Session:
        def __enter__(self) -> Session:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def scalar(self, _statement: object) -> object:
            return plan_record

    resolver = OrchestratorEvidenceUsageReceiptResolver(cast(Any, lambda: Session()))
    monkeypatch.setattr(
        resolver,
        "_resolve_pair_with_jobs",
        lambda **_kwargs: (pair, jobs),
    )
    monkeypatch.setattr(
        "eom_catalog_service.evidence_usage_receipts.ResolvedExecutionPlanV3.model_validate",
        staticmethod(lambda _value: plan),
    )
    expectation = EvidenceUsageProvenanceExpectation(
        plan_id=plan.plan_id,
        plan_sha256=plan.plan_sha256,
        evidence_bundle_revision_id=plan.evidence_bundle_revision_id,
        retrieval_request_id=plan.retrieval_request_id,
        retrieval_request_sha256=plan.retrieval_request_sha256,
        graph_snapshot_revision_id=plan.graph_snapshot.graph_snapshot_revision_id,
        evidence_manifest_sha256=plan.evidence_manifest_sha256,
    )

    resolved = resolver.resolve_mock_exam_pair(
        workflow_id=workflow_id,
        authoring_step_run_id=authoring_step_run_id,
        authoring=AUTHORING,
        review_step_run_id=review_step_run_id,
        review=REVIEW,
        expected_provenance=expectation,
        expected_authoring_receipt_sha256=pair.authoring.receipt_sha256,
        expected_review_receipt_sha256=pair.review.receipt_sha256,
    )

    assert resolved == pair

    wrong_input = _worker_input(
        REVIEW,
        workflow_id="workflow_" + "0" * 32,
        step_run_id=review_step_run_id,
    )
    review_job.request = wrong_input.model_dump(mode="json")
    review_job.request_hash = content_sha256(
        {
            "protocol_version": review_job.protocol_version,
            "task_type": review_job.task_type,
            "request": review_job.request,
        }
    )
    with pytest.raises(EvidenceUsageReceiptResolutionError, match="Workflow occurrence"):
        resolver.resolve_mock_exam_pair(
            workflow_id=workflow_id,
            authoring_step_run_id=authoring_step_run_id,
            authoring=AUTHORING,
            review_step_run_id=review_step_run_id,
            review=REVIEW,
        )


class _ReceiptResolver:
    def __init__(self, pair: EvidenceUsageReceiptPair) -> None:
        self.pair = pair
        self.calls: list[tuple[ArtifactPointer, ArtifactPointer]] = []

    def resolve_pair(
        self,
        *,
        authoring: ArtifactPointer,
        review: ArtifactPointer,
    ) -> EvidenceUsageReceiptPair:
        self.calls.append((authoring, review))
        return self.pair


class _FailingReceiptResolver:
    def resolve_pair(
        self,
        *,
        authoring: ArtifactPointer,
        review: ArtifactPointer,
    ) -> NoReturn:
        del authoring, review
        raise EvidenceUsageReceiptResolutionError("trusted receipt is missing")


class _Registry:
    def __init__(self) -> None:
        self.requests: list[RegistrationRequest] = []

    def register(self, request: RegistrationRequest) -> SimpleNamespace:
        self.requests.append(request)
        return SimpleNamespace(
            item_id="item_" + "1" * 32,
            item_revision_id="itemrev_" + "2" * 32,
            revision_number=1,
            manifest_artifact_id="artifact_" + "3" * 32,
            manifest_artifact_revision_id="rev_" + "4" * 32,
            manifest_sha256="sha256:" + "5" * 64,
        )


def _grounded_request() -> WorkflowRequest:
    scope = resolve_integrated_science_curriculum_scope("eom.is.middle.1-1")
    return WorkflowRequest.model_validate(
        {
            "request_name": "GENERATED_KNOWLEDGE_ITEM_REQUEST",
            "image_mode": "required",
            "content_pack": {
                "pack_key": "generated-knowledge-item",
                "environment": "test",
            },
            "profiles": {
                "authoring": "generated-knowledge-authoring",
                "image": "generated-stimulus-drawing",
                "review": "generated-knowledge-review",
                "registration": "generated-structured-registration",
            },
            "source_intake": {"batch_ids": []},
            "registry_intent": {"mode": "CREATE_ITEM"},
            "item_brief": {
                "schema_version": "3.0",
                "subject": "통합과학",
                "topic": "시간과 공간",
                "task_type": "TEXT",
                "difficulty": "MEDIUM",
                "authoring_guidance": CONTENT_TEAM_ITEM_GUIDANCE,
                "authoring_guidance_sha256": CONTENT_TEAM_ITEM_GUIDANCE_SHA256,
                "curriculum_scope": scope.model_dump(mode="json"),
                "mock_exam_slot": None,
                "original_request_sha256": "0" * 64,
            },
            "execution_preset_key": "knowledge-grounded-item",
            "educational_retrieval": {
                "schema_version": "educational-retrieval-requirement/1.0",
                "corpus_key": "integrated-science-textbooks",
                "query_kind": "ITEM_PREPARATION",
                "curriculum_root_key": scope.graph_root_stable_key,
                "topic_keys": [],
                "required_item_elements": ["choice", "paragraph"],
                "source_classes": ["APPROVED_ITEM", "PAST_EXAM", "TEXTBOOK"],
            },
        }
    )


def _ungrounded_request() -> WorkflowRequest:
    value = _grounded_request().model_dump(mode="json")
    value["execution_preset_key"] = "standard-item"
    value["educational_retrieval"] = None
    return WorkflowRequest.model_validate(value)


def _workflow_and_step() -> tuple[WorkflowInstanceRecord, WorkflowStepRunRecord]:
    workflow = cast(
        WorkflowInstanceRecord,
        SimpleNamespace(
            workflow_id="workflow_" + "f" * 32,
            definition_key="generic-item-development",
            definition_version="1.10.0",
            created_actor_id="editor",
            runtime_context={
                "content_pack": {
                    "release_id": "packrel_" + "1" * 32,
                    "release_sha256": "sha256:" + "2" * 64,
                },
                "registry_intent": {"mode": "CREATE_ITEM"},
                "source_intake": {"batch_ids": []},
            },
        ),
    )
    step = cast(
        WorkflowStepRunRecord,
        SimpleNamespace(
            step_key="registration",
            attempt=1,
            step_run_id="steprun_" + "3" * 32,
        ),
    )
    return workflow, step


def test_grounded_v10_registration_validates_receipts_before_writes_and_pins_hashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pair = _receipts()
    resolver = _ReceiptResolver(pair)
    registry = _Registry()
    service = object.__new__(WorkflowCatalogService)
    service.evidence_usage_receipts = resolver
    service.registry = cast(Any, registry)
    content_component = ComponentPointer(
        component_type="ITEM_CONTENT",
        ordinal=0,
        schema_ref="eom.assessment.item-content/3.0",
        media_type="application/json",
        artifact_id="artifact_" + "d" * 32,
        artifact_revision_id="rev_" + "e" * 32,
        sha256="sha256:" + "f" * 64,
        logical_name="assessment-item-content.json",
    )
    monkeypatch.setattr(
        service,
        "_knowledge_item_content",
        cast(Any, lambda _workflow, _request, _artifacts: content_component),
    )
    monkeypatch.setattr(
        service,
        "_content_team_image_components",
        cast(Any, lambda _workflow, _artifacts: ()),
    )
    workflow, step = _workflow_and_step()

    for _ in range(2):
        service.register_workflow(
            workflow=workflow,
            step=step,
            request=_grounded_request(),
            artifacts=(AUTHORING, REVIEW, REGISTRATION),
        )

    assert resolver.calls == [(AUTHORING, REVIEW), (AUTHORING, REVIEW)]
    assert registry.requests[0] == registry.requests[1]
    components = {row.component_type: row for row in registry.requests[0].components}
    assert components["UPPER_STEM"].artifact_revision_id == AUTHORING.revision_id
    assert components["UPPER_STEM"].metadata == {
        "evidence_usage_validation_receipt_sha256": pair.authoring.receipt_sha256
    }
    assert components["REVIEW_REPORT"].artifact_revision_id == REVIEW.revision_id
    assert components["REVIEW_REPORT"].metadata == {
        "evidence_usage_validation_receipt_sha256": pair.review.receipt_sha256
    }
    assert components["ITEM_CONTENT"] == content_component


def test_ungrounded_v10_registration_never_resolves_a_receipt() -> None:
    service = object.__new__(WorkflowCatalogService)
    service.evidence_usage_receipts = cast(Any, _FailingReceiptResolver())

    assert (
        service._require_evidence_usage_receipts(
            request=_ungrounded_request(),
            artifacts=(AUTHORING, REVIEW, REGISTRATION),
        )
        is None
    )


def test_grounded_v10_missing_receipt_fails_before_catalog_or_registry_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _Registry()
    service = object.__new__(WorkflowCatalogService)
    service.evidence_usage_receipts = cast(Any, _FailingReceiptResolver())
    service.registry = cast(Any, registry)
    derived_writes: list[str] = []
    monkeypatch.setattr(
        service,
        "_knowledge_item_content",
        cast(Any, lambda *_args: derived_writes.append("item-content")),
    )
    workflow, step = _workflow_and_step()

    with pytest.raises(EvidenceUsageReceiptResolutionError, match="missing"):
        service.register_workflow(
            workflow=workflow,
            step=step,
            request=_grounded_request(),
            artifacts=(AUTHORING, REVIEW, REGISTRATION),
        )

    assert derived_writes == []
    assert registry.requests == []
