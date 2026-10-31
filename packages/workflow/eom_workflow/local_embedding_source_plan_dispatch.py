"""Closed metadata family dispatch, without execution policy or source authority."""

from eom_catalog_contracts.embedding_contract_values import raw_public_solution_contract_value

from eom_workflow.local_embedding_source_plan import (
    LocalEmbeddingSourcePlan,
    parse_local_embedding_source_plan,
)
from eom_workflow.local_embedding_source_plan_v2 import (
    LocalEmbeddingSourcePlanV2,
    parse_local_embedding_source_plan_v2,
)
from eom_workflow.local_embedding_source_plan_v3 import (
    LocalEmbeddingSourcePlanV3,
    parse_local_embedding_source_plan_v3,
)
from eom_workflow.local_embedding_source_plan_v4 import (
    LocalEmbeddingSourcePlanV4,
    parse_local_embedding_source_plan_v4,
)

type SupportedLocalEmbeddingSourcePlan = (
    LocalEmbeddingSourcePlan
    | LocalEmbeddingSourcePlanV2
    | LocalEmbeddingSourcePlanV3
    | LocalEmbeddingSourcePlanV4
)


def parse_supported_local_embedding_source_plan(value: object) -> SupportedLocalEmbeddingSourcePlan:
    document = raw_public_solution_contract_value(value)
    if isinstance(document, dict):
        match document.get("schema_version"):
            case "local-embedding-source-plan/1.0":
                return parse_local_embedding_source_plan(document)
            case "local-embedding-source-plan/2.0":
                return parse_local_embedding_source_plan_v2(document)
            case "local-embedding-source-plan/3.0":
                return parse_local_embedding_source_plan_v3(document)
            case "local-embedding-source-plan/4.0":
                return parse_local_embedding_source_plan_v4(document)
    raise ValueError("LOCAL_EMBEDDING_SOURCE_PLAN_FAMILY_MISMATCH")
