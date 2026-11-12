"""Selected models reach support/review plans without weakening source or isolation."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from eom_catalog_contracts import ReviewTextbookEvidence
from eom_catalog_contracts.knowledge import EvidenceBundleManifestV4
from eom_identifiers import content_sha256
from eom_orchestrator import review_textbook_evidence_validation as admission
from eom_orchestrator.control_models import WorkerCapacityPolicyRevisionRecord
from eom_orchestrator.execution_resolver import resolve_pdf_document_review_plan
from eom_orchestrator.orchestrator import _plan_step_evidence_access
from eom_workflow import (
    PairedDocumentReviewRoleResultV4,
    RoleWorkerInput,
    build_pdf_document_review_request,
    validate_control_contract,
)
from eom_workflow.models import PdfDocumentReviewRoleResultV5
from eom_workflow.shared_model_execution_plans import (
    SharedCustomerSupportPlan,
    SharedPairedReviewPlan,
    SharedSingleReviewPlan,
)
from eom_workflow.shared_worker_capacity import SharedWorkerCapacityPolicy

from tests.unit.test_paired_document_review_textbook_v4 import _paired_worker_input, _result_v4
from tests.unit.test_pdf_document_review_execution import (
    NOW,
    FakeSession,
    _document,
    _v2_preset_document,
)
from tests.unit.test_review_textbook_evidence import _binding, _manifest, _usage
from tests.unit.test_shared_worker_capacity import capacity_value
from tests.unit.test_single_document_review_textbook_v5 import _input_v5, _result_v5


def rehash(document, field="plan_sha256"):
    document[field] = content_sha256({k: v for k, v in document.items() if k != field})
    return document


def resolved_single(*, model="approved-model", effort="high"):
    review = build_pdf_document_review_request(
        document=_document(), preset_key="MOCK_EXAM", additional_guidance=None
    )
    binding = _binding()
    binding["review_input_sha256"] = review.request_sha256
    binding = ReviewTextbookEvidence.model_validate(rehash(binding, "binding_sha256"))
    preset = _v2_preset_document()
    preset["role_policies"][0]["model_candidates"] = [{"model": model, "reasoning_effort": effort}]
    preset["compatible_workflow_protocols"] = ["workflow-role/1.31.0"]
    preset["retrieval_policy"].update(
        allowed_corpus_keys=[binding.requirement.corpus_key],
        allowed_source_classes=["TEXTBOOK"],
        access_policy_revision_id=binding.publication.access_policy_revision_id,
        access_policy_sha256=binding.publication.access_policy_sha256,
    )
    capacity = capacity_value()
    capacity["capacity_policy_revision_id"] = preset["capacity_policy_revision_id"]
    capacity["pools"] = [
        {
            "pool_key": "customer-support",
            "roles": ["support"],
            "slot_keys": ["slot01", "slot02", "slot03", "slot04", "slot05"],
            "max_active": 4,
        }
    ]
    capacity = SharedWorkerCapacityPolicy.model_validate(capacity).model_dump(mode="json")
    rehash(capacity, "content_sha256")
    rehash(preset, "content_sha256")

    class Session(FakeSession):
        def get(self, model, identity):
            if model is WorkerCapacityPolicyRevisionRecord:
                assert identity == capacity["capacity_policy_revision_id"]
                return SimpleNamespace(**capacity, canonical_document=capacity)
            return super().get(model, identity)

    session = Session(preset_document=preset)
    parameters = dict(
        workflow_id="workflow_" + "1" * 32,
        workflow_definition_version="1.4.0",
        workflow_definition_sha256="sha256:" + "2" * 64,
        workflow_role_schema_version="workflow-role/1.31.0",
        review_request=review,
        textbook_evidence=binding,
        resolved_at=NOW,
    )
    plan = resolve_pdf_document_review_plan(session, **parameters)
    return plan, session, parameters


@pytest.mark.parametrize("effort", ("minimal", "low", "medium", "high", "xhigh"))
def test_single_review_uses_selected_model_and_replay_never_resolves_latest(effort):
    plan, session, parameters = resolved_single(effort=effort)
    assert isinstance(plan, SharedSingleReviewPlan)
    assert plan.steps[0].model == "approved-model" and plan.steps[0].reasoning_effort == effort
    validate_control_contract("resolved-execution-plan-v38", plan.model_dump(mode="json"))
    session.preset_logical = None
    assert resolve_pdf_document_review_plan(session, **parameters) == plan


def test_review_dispatch_requires_evidence_flag_only_for_the_family_that_defines_it():
    single, _, _ = resolved_single()
    document = single.model_dump(mode="json")
    for version in (25, 38):
        assert (
            _plan_step_evidence_access(
                document | {"schema_version": f"resolved-execution-plan/{version}.0"},
                document["steps"][0],
            )
            is None
        )
    for version in (26, 39):
        assert (
            _plan_step_evidence_access(
                {"schema_version": f"resolved-execution-plan/{version}.0"},
                {"evidence_access": "EVIDENCE_CONTEXT"},
            )
            == "EVIDENCE_CONTEXT"
        )


@pytest.mark.parametrize(
    "model,version",
    ((SharedCustomerSupportPlan, 37), (SharedSingleReviewPlan, 38), (SharedPairedReviewPlan, 39)),
)
def test_new_support_families_preserve_boundary_and_exact_hash(model, version):
    single, _, _ = resolved_single()
    document = single.model_dump(mode="json")
    document.update(
        schema_version=f"resolved-execution-plan/{version}.0", resolver_version=f"{version}.0.0"
    )
    if version == 37:
        for name in ("document", "textbook_evidence", "review_request_sha256"):
            document.pop(name)
        document.update(
            workflow_definition_key="customer-support", support_case_sha256="sha256:" + "f" * 64
        )
        document["steps"][0].update(step_key="diagnose", timeout_seconds=900)
    elif version == 39:
        review = _paired_worker_input().request.review_request
        document.pop("document")
        document.update(
            documents=[v.model_dump(mode="json") for v in review.documents],
            workflow_definition_version="1.5.0",
            review_request_sha256=review.request_sha256,
        )
        document["steps"][0]["evidence_access"] = "EVIDENCE_CONTEXT"
        document["textbook_evidence"]["review_input_sha256"] = review.request_sha256
        rehash(document["textbook_evidence"], "binding_sha256")
    rehash(document)
    validate_control_contract(f"resolved-execution-plan-v{version}", document)
    assert model.model_validate(document).steps[0].model == "approved-model"
    for change in (
        {"network": "enabled"},
        {"sandbox": "workspace-write"},
        {"timeout_seconds": 30},
        {"worker_pool_key": "other-pool"},
    ):
        wrong = deepcopy(document)
        wrong["steps"][0].update(change)
        rehash(wrong)
        with pytest.raises(ValueError):
            model.model_validate(wrong)


@pytest.mark.parametrize("paired", (False, True))
def test_selected_review_plan_reaches_verified_textbook_commit_receipt(
    monkeypatch, tmp_path, paired
):
    plan, _, _ = resolved_single()
    document = plan.model_dump(mode="json")
    if paired:
        worker_value = _paired_worker_input().model_dump(mode="json")
        worker_value["protocol_version"] = "workflow-role/1.32.0"
        output = _result_v4()
        binding_value = _binding()
        binding_value["review_input_sha256"] = worker_value["request"]["review_request"][
            "request_sha256"
        ]
        binding_value["textbook_evidence_ids"] = [
            citation["evidence_id"] for citation in output["output"]["evidence_usage"]["citations"]
        ]
        binding = ReviewTextbookEvidence.model_validate(rehash(binding_value, "binding_sha256"))
        worker_value["request"]["textbook_evidence"] = binding.model_dump(mode="json")
        worker = RoleWorkerInput.model_validate(worker_value)
        review = worker.request.review_request
        output["output"].update(
            review_request_sha256=review.request_sha256,
            documents=[
                dict(
                    role=v.role,
                    document_id=v.document.document_id,
                    document_revision_id=v.document.document_revision_id,
                    source_pdf_sha256=v.document.source_pdf.sha256,
                )
                for v in review.documents
            ],
            preset_key=review.preset.preset_key,
            preset_revision_id=review.preset.preset_revision_id,
            preset_sha256=review.preset.preset_sha256,
            additional_guidance_sha256=review.additional_guidance_sha256,
        )
        page_hashes = {
            (v.role, p.page_number): p.page_image.sha256
            for v in review.documents
            for p in v.document.pages
        }

        def bind_fixture_anchors(value):
            if isinstance(value, dict):
                if "page_image_sha256" in value:
                    value["page_image_sha256"] = page_hashes[
                        (value["document_role"], value["page_number"])
                    ]
                for child in value.values():
                    bind_fixture_anchors(child)
            elif isinstance(value, list):
                for child in value:
                    bind_fixture_anchors(child)

        bind_fixture_anchors(output["output"])
        publication = binding.publication
        usage = output["output"]["evidence_usage"]
        usage.update(
            evidence_bundle_id=publication.evidence_bundle_id,
            evidence_bundle_revision_id=publication.evidence_bundle_revision_id,
            retrieval_request_id=publication.retrieval_request_id,
            graph_snapshot_revision_id=publication.graph_snapshot.graph_snapshot_revision_id,
            manifest_sha256=publication.manifest_sha256,
            context_sha256=publication.context_artifact.sha256,
        )
        textbook_usage = _usage(binding)
        textbook_usage["citations"] = [
            dict(
                textbook_usage["citations"][0],
                evidence_id=citation["evidence_id"],
                anchor_ids=citation["anchor_ids"],
                conclusion_paths=[
                    "/verification_targets/2/conclusion",
                    "/verification_targets/6/conclusion",
                ],
            )
            for citation in usage["citations"]
        ]
        output["output"]["textbook_usage"] = rehash(textbook_usage, "usage_sha256")
        kind = PairedDocumentReviewRoleResultV4
        document.pop("document")
        document.update(
            schema_version="resolved-execution-plan/39.0",
            resolver_version="39.0.0",
            workflow_definition_version="1.5.0",
            documents=[v.model_dump(mode="json") for v in worker.request.review_request.documents],
        )
        document["steps"][0]["evidence_access"] = "EVIDENCE_CONTEXT"
        commit = admission.validate_paired_document_textbook_for_commit
    else:
        worker = RoleWorkerInput.model_validate(_input_v5())
        binding = worker.request.textbook_evidence
        output = _result_v5()
        kind = PdfDocumentReviewRoleResultV5
        document["document"] = worker.request.review_request.document.model_dump(mode="json")
        commit = admission.validate_single_document_textbook_for_commit
    output.update(
        job_id=worker.job_id, workflow_id=worker.workflow_id, step_run_id=worker.step_run_id
    )
    result = kind.model_validate(output)
    document.update(
        workflow_id=worker.workflow_id,
        review_request_sha256=worker.request.review_request.request_sha256,
        textbook_evidence=binding.model_dump(mode="json"),
    )
    rehash(document)
    record = SimpleNamespace(canonical_document=document, plan_sha256=document["plan_sha256"])
    session = SimpleNamespace(get=lambda *_args: record)
    manifest_value = dict(_manifest(binding).__dict__)
    if paired:
        manifest_value["entries"] = tuple(
            SimpleNamespace(
                evidence_id=c["evidence_id"],
                anchor_ids=tuple(c["anchor_ids"]),
                source=SimpleNamespace(source_class="TEXTBOOK"),
                use="GROUNDING",
            )
            for c in output["output"]["evidence_usage"]["citations"]
        )
    # Bundle material resolution is tested separately; this checks the exact new
    # plan family all the way through usage validation and immutable receipt.
    manifest = EvidenceBundleManifestV4.model_construct(**manifest_value)
    monkeypatch.setattr(
        admission, "authorized_execution_artifact_revisions", lambda *_a, **_k: frozenset()
    )
    monkeypatch.setattr(
        admission,
        "resolve_textbook_review_materials",
        lambda *_a, **_k: SimpleNamespace(manifest=manifest),
    )
    receipt = commit(
        session,
        plan_id=document["plan_id"],
        worker_input=worker,
        result=result,
        result_artifact_id="artifact_" + "1" * 32,
        result_artifact_revision_id="rev_" + "2" * 32,
        result_content_sha256="sha256:" + "3" * 64,
        canonical_artifact_root=tmp_path,
    )
    assert receipt.plan_sha256 == record.plan_sha256
    assert receipt.binding_sha256 == binding.binding_sha256
