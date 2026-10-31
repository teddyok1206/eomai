"""Synthetic exact plan associations; no current IAM, actual index or QUERY proof."""

from eom_catalog_contracts.public_solution_delivery import parse_public_solution_similarity_delivery
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingEntry
from eom_catalog_contracts.public_solution_reference import PublicSolutionSourceReference
from eom_catalog_contracts.registered_public_solution_similarity import (
    parse_supported_public_solution_similarity_context,
)
from eom_workflow.public_similarity_control import bind_public_similarity_execution_plan

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.similarity_plan_fixtures import ordinary_similarity_case, similarity_case
from tests.unit.test_public_solution_delivery import public_delivery_body
from tests.unit.test_public_solution_similarity_contracts import public_similarity_case
from tests.unit.test_registered_public_solution_similarity_contracts import (
    registered_similarity_case,
)


def public_plan_case(tmp_path, monkeypatch, *, ordinary=False, registered=False):
    case = (ordinary_similarity_case if ordinary else similarity_case)(tmp_path, monkeypatch)
    base = case["base"]
    if registered:
        _, context, _, _, _, data = registered_similarity_case()
    else:
        _, context, _, _, data = public_similarity_case()
    raw = context.model_dump(mode="json")
    past = next(entry for entry in data[0] if entry.source.source_class == "PAST_EXAM")
    creative = next(entry for entry in data[0] if entry.source.source_class != "PAST_EXAM")
    entry_raw = past.model_dump(mode="json")
    entry_raw.update(
        source=case["original_source"],
        graph_snapshot=base.graph_snapshot.model_dump(mode="json"),
        policy_revision_id=base.access_policy_revision_id,
        policy_sha256=base.access_policy_sha256,
    )
    past = PublicSolutionEmbeddingEntry.model_validate(seal(entry_raw, "entry_sha256"))
    raw["request"].update(
        anchor=PublicSolutionSourceReference.from_entry(past).model_dump(mode="json"),
        consumer_purpose="ITEM_AUTHORING" if ordinary else "PAST_EXAM_VARIATION",
        graph_snapshot=base.graph_snapshot.model_dump(mode="json"),
        policy_revision_id=base.access_policy_revision_id,
        policy_sha256=base.access_policy_sha256,
    )
    raw["request"] = seal(raw["request"], "request_sha256")
    raw["candidates"][0].update(
        PublicSolutionSourceReference.from_entry(creative).model_dump(mode="json")
    )
    context = parse_supported_public_solution_similarity_context(seal(raw, "context_sha256"))
    pin = parse_public_solution_similarity_delivery(public_delivery_body(context))
    case.update(
        legacy_plan=case["plan"],
        legacy_context=case["context"],
        legacy_delivery=case["delivery"],
        context=context,
        delivery=pin,
        plan=bind_public_similarity_execution_plan(base, pin, context),
        public_anchor=past,
    )
    return case
