"""Common exact public plan/material values; no current IAM or native QUERY proof."""

from eom_catalog_contracts.public_similarity_materials import (
    PublicQuestionUnavailable,
    PublicSolutionReferenceMaterial,
    build_public_similarity_materials,
)
from eom_catalog_contracts.public_solution_delivery import parse_public_solution_similarity_delivery
from eom_catalog_contracts.registered_public_solution_embedding import (
    parse_public_solution_encoding_entry,
)
from eom_catalog_contracts.registered_public_solution_similarity import (
    parse_supported_public_solution_similarity_context,
    public_solution_reference_for_entry,
)
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.public_similarity_materialization import (
    PublicSimilarityMaterializationContext,
)
from eom_orchestrator.similarity_materialization import SimilarityWorkspaceMaterials
from eom_workflow.public_similarity_control import bind_public_similarity_execution_plan

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.public_similarity_plan_fixtures import public_plan_case
from tests.unit.test_public_similarity_materials_contracts import material_case
from tests.unit.test_public_solution_delivery import public_delivery_body


def public_materialization_case(tmp_path, monkeypatch, *, ordinary=False, registered=False):
    case = public_plan_case(tmp_path, monkeypatch, ordinary=ordinary, registered=registered)
    _, old_materials = material_case(registered)
    lookup = {
        material.entry.source.item_revision_id: material.entry
        for material in (old_materials.anchor, *old_materials.entries)
    }
    lookup[case["public_anchor"].source.item_revision_id] = case["public_anchor"]
    raw = case["context"].model_dump(mode="json")
    materials = []
    for reference in (raw["request"]["anchor"], *raw["candidates"]):
        entry = lookup[reference["source"]["item_revision_id"]]
        entry = parse_public_solution_encoding_entry(
            seal(
                entry.model_dump(mode="json")
                | {
                    "graph_snapshot": raw["request"]["graph_snapshot"],
                    "policy_revision_id": raw["request"]["policy_revision_id"],
                    "policy_sha256": raw["request"]["policy_sha256"],
                },
                "entry_sha256",
            )
        )
        reference.update(public_solution_reference_for_entry(entry).model_dump(mode="json"))
        materials.append(
            PublicSolutionReferenceMaterial(
                entry=entry, question=PublicQuestionUnavailable(reason="SCHEMA_UNSUPPORTED")
            )
        )
    raw["request"] = seal(raw["request"], "request_sha256")
    context = parse_supported_public_solution_similarity_context(seal(raw, "context_sha256"))
    references = build_public_similarity_materials(
        context, anchor=materials[0], entries=tuple(materials[1:])
    )
    delivery = parse_public_solution_similarity_delivery(public_delivery_body(context))
    plan = bind_public_similarity_execution_plan(case["base"], delivery, context)
    payload = SimilarityWorkspaceMaterials(
        canonical_json_bytes(context), canonical_json_bytes(references)
    )
    calls = []

    class Reader:
        def resolve(self, session, **arguments):
            calls.append((session, arguments))
            return payload

    bound = PublicSimilarityMaterializationContext(
        workflow_id=plan.workflow_id,
        operator_id="operator_" + "a" * 32,
        request=context.request,
        reader=Reader(),
    )
    return case | dict(
        context=context,
        references=references,
        delivery=delivery,
        plan=plan,
        payload=payload,
        bound=bound,
        resolution_calls=calls,
    )
