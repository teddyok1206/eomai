"""Deterministic contract projection. Emit for review or check; never edit old schema bytes."""

import argparse
import json
from pathlib import Path

from eom_catalog_contracts.public_solution_embedding_index import (
    PublicSolutionEmbeddingIndex,
    PublicSolutionEmbeddingSourceBinding,
    PublicSolutionIndexNamespace,
    PublicSolutionProfilePointer,
)
from eom_catalog_contracts.public_solution_embedding_registry import (
    PublicSolutionIndexRegistrationResult,
    RegisterPublicSolutionIndexCommand,
)
from pydantic import TypeAdapter

ROOT = Path(__file__).resolve().parents[2]
NAME = "knowledge/public-solution-embedding-index-v3.schema.json"


def schema(*, registry: bool = False) -> dict:
    value = TypeAdapter(
        RegisterPublicSolutionIndexCommand | PublicSolutionIndexRegistrationResult
        if registry
        else PublicSolutionEmbeddingIndex
        | PublicSolutionEmbeddingSourceBinding
        | PublicSolutionIndexNamespace
        | PublicSolutionProfilePointer
    ).json_schema()
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "eom://schemas/knowledge/public-solution-embedding-"
        + ("registry" if registry else "index")
        + "/3.0",
        "title": "Exact public-solution bindings over existing numerical shards",
        **value,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    families = parser.add_mutually_exclusive_group()
    families.add_argument("--registry", action="store_true")
    families.add_argument("--plan", action="store_true")
    families.add_argument("--policy", action="store_true")
    families.add_argument("--request", action="store_true")
    families.add_argument("--ownership", action="store_true")
    families.add_argument("--completion", action="store_true")
    families.add_argument("--coordinator", action="store_true")
    families.add_argument("--query", action="store_true")
    arguments = parser.parse_args()
    value = schema(registry=arguments.registry)
    name = NAME.replace("index", "registry") if arguments.registry else NAME
    if arguments.plan:
        from eom_workflow.local_embedding_source_plan_v3 import LocalEmbeddingSourcePlanV3

        value = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "eom://schemas/workflow/local-embedding-source-plan/3.0",
            **LocalEmbeddingSourcePlanV3.model_json_schema(),
        }
        name = "workflow/local-embedding-source-plan-v3.schema.json"
    if arguments.policy:
        from eom_catalog_contracts.public_solution_indexing_policy import (
            PublicSolutionIndexingAccessPolicy,
        )

        value = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "eom://schemas/knowledge/education-retrieval-access-policy/1.4",
            **PublicSolutionIndexingAccessPolicy.model_json_schema(),
        }
        name = "knowledge/education-retrieval-access-policy-v1.4.schema.json"
    if arguments.request:
        from eom_workflow.local_embedding_request_v3 import LocalEmbeddingWorkflowRequestV3

        value = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "eom://schemas/workflow/local-embedding-workflow-request/3.0",
            **LocalEmbeddingWorkflowRequestV3.model_json_schema(),
        }
        name = "workflow/local-embedding-workflow-request-v3.schema.json"
    if arguments.ownership:
        from eom_workflow.local_embedding_encoding_ownership_v3 import (
            EmbeddingEncodingOwnershipMessageV3,
        )

        value = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "eom://schemas/workflow/embedding-encoding-ownership/3.0",
            **TypeAdapter(EmbeddingEncodingOwnershipMessageV3).json_schema(),
        }
        name = "workflow/embedding-encoding-ownership-v3.schema.json"
    if arguments.completion:
        from eom_workflow.local_embedding_workflow_receipt_v3 import (
            LocalEmbeddingStepOutputV3,
            LocalEmbeddingWorkflowReceiptV3,
        )

        value = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "eom://schemas/workflow/local-embedding-completion/3.0",
            **TypeAdapter(
                LocalEmbeddingStepOutputV3 | LocalEmbeddingWorkflowReceiptV3
            ).json_schema(),
        }
        name = "workflow/local-embedding-completion-v3.schema.json"
    if arguments.coordinator:
        from eom_workflow.native_embedding_coordinator_v3 import (
            NativeEmbeddingCoordinatorCheckpointV3,
        )

        value = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "eom://schemas/workflow/native-embedding-coordinator/3.0",
            **NativeEmbeddingCoordinatorCheckpointV3.model_json_schema(),
        }
        name = "workflow/native-embedding-coordinator-v3.schema.json"
    if arguments.query:
        from eom_catalog_contracts.public_solution_query import (
            PublicSolutionQueryExecutionPointer,
            PublicSolutionQueryInput,
            PublicSolutionQueryResult,
        )

        value = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "eom://schemas/knowledge/public-solution-query/2.0",
            **TypeAdapter(
                PublicSolutionQueryInput
                | PublicSolutionQueryResult
                | PublicSolutionQueryExecutionPointer
            ).json_schema(),
        }
        name = "knowledge/public-solution-query-v2.schema.json"
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    if not arguments.check:
        print(payload.decode(), end="")
        return
    resource = (
        ROOT / "packages/workflow/eom_workflow/resources" / Path(name).name
        if arguments.plan
        or arguments.request
        or arguments.ownership
        or arguments.completion
        or arguments.coordinator
        else ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources" / name
    )
    for path in (ROOT / "schemas" / name, resource):
        if path.read_bytes() != payload:
            raise SystemExit("PUBLIC_SOLUTION_INDEX_SCHEMA_DRIFT")


if __name__ == "__main__":
    main()
