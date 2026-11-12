"""Model-configurable successors; all historical review constraints remain intact."""

from typing import Literal, Self

from eom_identifiers import content_sha256
from pydantic import model_validator

from eom_workflow.control_plane import (
    ResolvedExecutionPlanV10,
    ResolvedExecutionPlanV25,
    ResolvedExecutionPlanV26,
)


def _validate_support_plan(
    plan: ResolvedExecutionPlanV10 | ResolvedExecutionPlanV25 | ResolvedExecutionPlanV26,
    *,
    diagnosis: bool,
) -> None:
    step = plan.steps[0]
    if (
        step.step_key != ("diagnose" if diagnosis else "review_document")
        or step.role != "support"
        or step.worker_pool_key != "customer-support"
        or step.reference_bundle is not None
        or step.timeout_seconds != (900 if diagnosis else 3600)
        or step.sandbox != "read-only"
        or step.network != "disabled"
        or step.general_knowledge_mode != "ALLOWED_WITH_PROVENANCE"
    ):
        raise ValueError("shared support plan changed isolation or purpose")
    if plan.plan_sha256 != content_sha256(plan.model_dump(mode="json", exclude={"plan_sha256"})):
        raise ValueError("shared support plan hash differs")


class SharedCustomerSupportPlan(ResolvedExecutionPlanV10):
    schema_version: Literal["resolved-execution-plan/37.0"] = "resolved-execution-plan/37.0"  # type: ignore[assignment]
    resolver_version: Literal["37.0.0"] = "37.0.0"  # type: ignore[assignment]

    @model_validator(mode="after")
    def one_customer_support_step_and_exact_hash(self) -> Self:
        _validate_support_plan(self, diagnosis=True)
        return self


class SharedSingleReviewPlan(ResolvedExecutionPlanV25):
    schema_version: Literal["resolved-execution-plan/38.0"] = "resolved-execution-plan/38.0"  # type: ignore[assignment]
    resolver_version: Literal["38.0.0"] = "38.0.0"  # type: ignore[assignment]

    @model_validator(mode="after")
    def one_pdf_document_review_step_and_exact_hash(self) -> Self:
        _validate_support_plan(self, diagnosis=False)
        return self


class SharedPairedReviewPlan(ResolvedExecutionPlanV26):
    schema_version: Literal["resolved-execution-plan/39.0"] = "resolved-execution-plan/39.0"  # type: ignore[assignment]
    resolver_version: Literal["39.0.0"] = "39.0.0"  # type: ignore[assignment]

    @model_validator(mode="after")
    def one_paired_document_review_step_and_exact_hash(self) -> Self:
        _validate_support_plan(self, diagnosis=False)
        if tuple(v.role for v in self.documents) != ("QUESTION", "SOLUTION"):
            raise ValueError("paired review requires QUESTION then SOLUTION")
        return self
