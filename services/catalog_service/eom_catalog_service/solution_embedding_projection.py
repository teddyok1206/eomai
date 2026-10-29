"""Format-neutral public reasoning; callers retain the exact source proof separately.

This successor projection does not replace any released embedding view. The
incremental owner must select the matching successor recipe for BOTH queries
and candidates before publishing bindings; old encoding pins remain untouched.
"""

from eom_catalog_contracts.external_item_learning_result import ExternalItemLearningResult
from eom_catalog_contracts.external_item_learning_result_v2 import ExternalItemLearningResultV2
from eom_catalog_contracts.knowledge import KnowledgeAnalysisSolutionReport
from eom_catalog_contracts.public_solution_text import (
    PublicSolutionText,
    build_public_solution_text,
)

type PublicSolutionReport = (
    KnowledgeAnalysisSolutionReport | ExternalItemLearningResult | ExternalItemLearningResultV2
)


def project_public_solution_text(report: PublicSolutionReport) -> PublicSolutionText:
    """Normalize only actual public solution fields, not JSON/IDs/editorial guesses.

    Canonical Item/source/report Artifact authorization, acceptance or registered
    lineage belongs to the existing Catalog read owner. Shape validation here
    cannot confer those permissions. An independent review's conclusions alone
    are deliberately not accepted as a full public solution report.
    """
    if type(report) is KnowledgeAnalysisSolutionReport:
        checked = KnowledgeAnalysisSolutionReport.model_validate(report.model_dump(mode="json"))
        return build_public_solution_text(
            tuple(
                value for step in checked.solution_steps for value in (step.rationale, step.outcome)
            )
        )
    if type(report) is ExternalItemLearningResultV2:
        checked_v2 = ExternalItemLearningResultV2.model_validate(report.model_dump(mode="json"))
        return build_public_solution_text(
            tuple(step.reasoning_summary for step in checked_v2.solution_report.solution_steps)
        )
    if type(report) is ExternalItemLearningResult:
        # V1 hashes the submitted shape, including which optional defaults were
        # absent. Re-encoding injected defaults is not its historical input.
        checked_v1 = ExternalItemLearningResult.model_validate(
            report.model_dump(mode="json", exclude_unset=True)
        )
        return build_public_solution_text(
            tuple(step.reasoning_summary for step in checked_v1.proposal.solution_steps)
            if checked_v1.proposal is not None
            else ()
        )
    raise ValueError("PUBLIC_SOLUTION_REPORT_FAMILY_UNAVAILABLE")
