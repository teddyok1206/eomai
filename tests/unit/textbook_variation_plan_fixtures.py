"""Synthetic successor controls; not a textbook retrieval or current authority proof."""

from eom_catalog_contracts import resolve_integrated_science_curriculum_scope
from eom_identifiers import content_sha256
from eom_workflow.control_plane import ResolvedExecutionPlanV19, ResolvedExecutionPlanV35

from tests.unit.inference_transfer_embedding_fixtures import seal


def textbook_variation_base(base: ResolvedExecutionPlanV19) -> ResolvedExecutionPlanV35:
    body = base.model_dump(mode="json")
    requirement = body["retrieval_requirement"]
    requirement.update(
        schema_version="educational-retrieval-requirement/3.0",
        curriculum_root_key=resolve_integrated_science_curriculum_scope(
            "eom.is.middle.1-1"
        ).graph_root_stable_key,
        source_classes=["PAST_EXAM", "TEXTBOOK"],
    )
    body.update(
        schema_version="resolved-execution-plan/35.0",
        resolver_version="35.0.0",
        retrieval_requirement_sha256=content_sha256(requirement),
    )
    return ResolvedExecutionPlanV35.model_validate(seal(body, "plan_sha256"))
