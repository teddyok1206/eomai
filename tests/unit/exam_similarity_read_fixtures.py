"""Immutable synthetic Assembly/read values; no actual source or identity admission."""

from functools import lru_cache

from eom_catalog_contracts import (
    MockExamAssemblyManifestV1,
    MockExamAssemblyManifestV2,
    MockExamAssemblyManifestV3,
    build_mock_exam_assembly_cohort,
    build_mock_exam_assembly_plan,
    load_integrated_science_mock_exam_layout_policy,
    load_integrated_science_mock_exam_policy,
    load_integrated_science_mock_exam_rating_policy,
    validate_mock_exam_placements,
)
from eom_catalog_contracts.exam_similarity_observation import parse_exam_observation_request
from eom_catalog_contracts.exam_similarity_read import (
    ExamObservationReadReply,
    ExamObservationReadRequest,
    ExamObservationReadSelection,
)
from eom_catalog_service.exam_similarity_observation import compose_exam_similarity_observation
from eom_identifiers import content_sha256

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.test_exam_similarity_observation import exam_case
from tests.unit.test_mock_exam_assembly_contracts import (
    _placements,
    _planning_candidates,
    _planning_candidates_v2,
    _usage_snapshot,
)


@lru_cache(maxsize=3)
def read_case(version: int = 1):
    request, prepared, reads = exam_case(available=3)
    policy = load_integrated_science_mock_exam_policy()
    body = {
        "schema_version": f"mock-exam-assembly-manifest/{version}.0",
        "assessment_assembly_revision_id": "assemblyrev_" + "1" * 32,
        "assessment_assembly_id": "assembly_" + "2" * 32,
        "assessment_form_id": "form_" + "3" * 32,
        "assessment_form_revision_id": "formrev_" + "4" * 32,
        "deliverable_id": "deliverable_" + "5" * 32,
        "deliverable_revision_id": "delivrev_" + "6" * 32,
        "revision_state": "RELEASED",
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "created_by": "operator_" + "7" * 32,
    }
    if version == 1:
        placements = _placements()
        body |= {
            "policy_revision_id": policy.policy_revision_id,
            "policy_sha256": content_sha256(policy.model_dump(mode="json")),
            "outline_key": policy.outline_key,
            "outline_revision": policy.outline_revision,
            "outline_sha256": policy.outline_sha256,
            "graph_snapshot_revision_id": request.graph_snapshot.graph_snapshot_revision_id,
            "graph_snapshot_sha256": request.graph_snapshot.manifest_sha256,
            "placements": [p.model_dump(mode="json") for p in placements],
            "validation": validate_mock_exam_placements(placements, policy).model_dump(mode="json"),
        }
        manifest = MockExamAssemblyManifestV1.model_validate(seal(body, "manifest_sha256"))
    else:
        candidates = _planning_candidates() if version == 2 else _planning_candidates_v2()
        plan = build_mock_exam_assembly_plan(
            policy=policy,
            layout_policy=load_integrated_science_mock_exam_layout_policy(),
            rating_policy=load_integrated_science_mock_exam_rating_policy(),
            graph_snapshot_revision_id=request.graph_snapshot.graph_snapshot_revision_id,
            graph_snapshot_sha256=request.graph_snapshot.manifest_sha256,
            usage_snapshot=_usage_snapshot(
                captured_at=NOW, candidate_revision_count=len(candidates)
            ),
            resolved_candidate_count=len(candidates),
            candidates=candidates,
            planned_at=NOW,
        )
        body |= {"plan": plan.model_dump(mode="json"), "form_key": "main", "display_label": "test"}
        model = MockExamAssemblyManifestV2 if version == 2 else MockExamAssemblyManifestV3
        manifest = model.model_validate(seal(body, "manifest_sha256"))
        request = parse_exam_observation_request(
            seal(
                request.model_dump(mode="json")
                | {
                    "cohort": build_mock_exam_assembly_cohort(
                        tuple(p.item_revision_id for p in plan.placements)
                    ).model_dump(mode="json")
                },
                "request_sha256",
            )
        )
    result = compose_exam_similarity_observation(request, prepared, reads)
    read = ExamObservationReadRequest(
        schema_version="system-rag-exam-observation-read-request/1.0",
        operation="READ_EXAM_SIMILARITY_OBSERVATION",
        actor_id="operator_" + "8" * 32,
        selection=ExamObservationReadSelection(
            assembly_revision_id=manifest.assessment_assembly_revision_id,
            assembly_manifest_sha256=manifest.manifest_sha256,
            observation_request=request,
        ),
    )
    reply = ExamObservationReadReply(
        schema_version="system-rag-exam-observation-read-reply/1.0",
        operation="READ_EXAM_SIMILARITY_OBSERVATION",
        status="SUCCESS",
        actor_id=read.actor_id,
        request_sha256=content_sha256(read.model_dump(mode="json")),
        result=result,
        error_code=None,
    )
    return read, reply, manifest
