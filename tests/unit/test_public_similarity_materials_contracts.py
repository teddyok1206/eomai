"""Pure bounded context3/4 association, not IAM or actual QUERY execution proof."""

from functools import lru_cache
from pathlib import Path

import pytest
from eom_catalog_contracts.inference_transfer_experiment import CanonicalExperimentItemText
from eom_catalog_contracts.public_similarity_materials import (
    PUBLIC_SIMILARITY_MATERIAL_LIMITATIONS,
    PublicQuestionAvailable,
    PublicQuestionUnavailable,
    PublicSolutionReferenceMaterial,
    build_public_similarity_materials,
    parse_public_similarity_materials,
    validate_public_similarity_materials,
)
from eom_catalog_contracts.registered_public_solution_similarity import (
    parse_supported_public_solution_similarity_context,
)
from eom_catalog_contracts.similarity_materials import parse_similarity_materials
from eom_catalog_contracts.similarity_materials_v2 import parse_similarity_materials_v2
from eom_catalog_contracts.validation import load_schema, validate_contract
from eom_identifiers import content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_public_solution_similarity_contracts import public_similarity_case
from tests.unit.test_registered_public_solution_similarity_contracts import (
    registered_similarity_case,
)


@lru_cache(maxsize=2)
def material_case(registered=False):
    if registered:
        _, context, ai, _, _, data = registered_similarity_case()
        entries = (*data[0], ai)
    else:
        _, context, _, _, data = public_similarity_case()
        entries = data[0]
    lookup = {entry.source.item_revision_id: entry for entry in entries}

    def material(reference):
        entry = lookup[reference.source.item_revision_id]
        return PublicSolutionReferenceMaterial(
            entry=entry, question=PublicQuestionUnavailable(reason="SCHEMA_UNSUPPORTED")
        )

    value = build_public_similarity_materials(
        context,
        anchor=material(context.request.anchor),
        entries=tuple(material(candidate) for candidate in context.candidates),
    )
    return context, value


@pytest.mark.parametrize("registered", (False, True))
def test_closed_public_materials_keep_exact_source_reports_order_and_numeric_text(registered):
    context, value = material_case(registered)
    assert validate_public_similarity_materials(value, context) == value
    assert parse_public_similarity_materials(value.model_dump(mode="json")) == value
    assert value.limitations == PUBLIC_SIMILARITY_MATERIAL_LIMITATIONS
    assert tuple(material.entry.source for material in value.entries) == tuple(
        candidate.source for candidate in context.candidates
    )
    assert value.anchor.entry.public_solution.text == value.entries[0].entry.public_solution.text
    if registered:
        assert (
            value.entries[1].entry.public_solution.text
            == value.entries[0].entry.public_solution.text
        )
        assert value.entries[1].entry.evidence.kind == "ACCEPTED_REGISTERED_SOLUTION_ANALYSIS"
    assert value.anchor.entry.evidence.kind == "REGISTERED_CREATIVE_SOURCE_REPORT"
    assert value.entries[0].entry.evidence.kind == "ACCEPTED_SOLUTION_ANALYSIS"
    validate_contract("system-rag-similarity-materials-v3", value.model_dump(mode="json"))


@pytest.mark.parametrize("registered", (False, True))
@pytest.mark.parametrize("status", ("PARTIAL", "EMPTY"))
def test_materials_do_not_upgrade_partial_or_empty_to_complete_coverage(registered, status):
    context, value = material_case(registered)
    raw = context.model_dump(mode="json")
    raw["status"] = status
    raw["population"]["authorized_source_count"] += 1
    raw["limitations"].append("PARTIAL_REPORT_COVERAGE")
    if status == "EMPTY":
        raw["population"]["scored_count"] = 0
        raw["candidates"] = []
    context = parse_supported_public_solution_similarity_context(seal(raw, "context_sha256"))
    materialized = build_public_similarity_materials(
        context, anchor=value.anchor, entries=() if status == "EMPTY" else value.entries
    )
    assert materialized.context_sha256 == context.context_sha256
    assert len(materialized.entries) == len(context.candidates)
    assert context.status == status


@pytest.mark.parametrize(
    "fault",
    (
        "hash",
        "request",
        "context",
        "order",
        "duplicate",
        "missing",
        "graph",
        "policy",
        "recipe",
        "extra",
        "question",
        "text_hash",
        "overflow",
    ),
)
def test_rehashed_forgery_is_not_source_or_context_resolution(fault):
    context, value = material_case(True)
    body = value.model_dump(mode="json")
    if fault in {"request", "context"}:
        body[fault + "_sha256"] = "sha256:" + "0" * 64
    elif fault == "hash":
        body["materials_sha256"] = "sha256:" + "0" * 64
    elif fault == "order":
        body["entries"].reverse()
    elif fault == "duplicate":
        body["entries"][1] = body["entries"][0]
    elif fault == "missing":
        body["entries"].pop()
    elif fault in {"graph", "policy", "recipe", "text_hash"}:
        entry = body["entries"][0]["entry"]
        if fault == "graph":
            entry["graph_snapshot"]["graph_snapshot_revision_id"] = "rev_" + "0" * 32
        elif fault == "policy":
            entry["policy_sha256"] = "sha256:" + "0" * 64
        elif fault == "recipe":
            entry["recipe"]["facets"] = "EXACT_PROFILE_CLAIMS"
        else:
            entry["public_solution"]["text"] += " NOT_THE_SAME_INPUT"
        body["entries"][0]["entry"] = seal(entry, "entry_sha256")
    elif fault == "question":
        source = value.entries[0].entry.source.artifact_member
        content = CanonicalExperimentItemText(
            text="질문", original_source=source, text_sha256=content_sha256("질문")
        ).model_dump(mode="json")
        body["anchor"]["question"] = {"status": "AVAILABLE", "content": content}
        body["anchor"]["question"]["content"]["original_source"]["sha256"] = "sha256:" + "0" * 64
    elif fault == "overflow":
        body["entries"] *= 5
    else:
        body["authority"] = "ADMIN"
    if fault != "hash":
        body = seal(body, "materials_sha256")
    with pytest.raises((ValueError, SchemaError)):
        validate_public_similarity_materials(parse_public_similarity_materials(body), context)


def test_available_question_is_exact_source_bound_not_a_full_solution_claim():
    context, value = material_case()
    entry = value.anchor.entry
    content = CanonicalExperimentItemText(
        text="관측 자료를 해석하시오.",
        original_source=entry.source.artifact_member,
        text_sha256=content_sha256("관측 자료를 해석하시오."),
    )
    anchor = PublicSolutionReferenceMaterial(
        entry=entry, question=PublicQuestionAvailable(content=content)
    )
    observed = build_public_similarity_materials(context, anchor=anchor, entries=value.entries)
    assert observed.anchor.question.content == content
    assert observed.anchor.entry.public_solution == entry.public_solution


def test_constructed_nested_unknown_fields_and_corrupt_text_cannot_be_erased():
    context, value = material_case()
    corrupt = value.anchor.entry.model_copy(update={"authority": "ADMIN"})
    forged = value.model_copy(update={"anchor": value.anchor.model_copy(update={"entry": corrupt})})
    with pytest.raises((ValueError, SchemaError)):
        validate_public_similarity_materials(forged, context)


def test_unknown_huge_payload_fails_bounded_before_schema_interpretation():
    _, value = material_case()
    raw = value.model_dump(mode="json") | {"unexpected": "x" * (4 * 1024 * 1024)}
    with pytest.raises(ValueError, match="byte budget"):
        parse_public_similarity_materials(raw)


@pytest.mark.parametrize("parser", (parse_similarity_materials, parse_similarity_materials_v2))
def test_common_solution_materials_do_not_reinterpret_old_profile_contracts(parser):
    _, value = material_case(True)
    with pytest.raises((ValueError, SchemaError)):
        parser(value.model_dump(mode="json"))


def test_schema_resource_is_identical_and_predecessor_bytes_remain_frozen():
    schema = load_schema("system-rag-similarity-materials-v3")
    Draft202012Validator.check_schema(schema)
    root = Path(__file__).resolve().parents[2]
    name = "system-rag-similarity-materials-v3.schema.json"
    source = (root / "schemas/knowledge" / name).read_bytes()
    mirror = (
        root / "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge" / name
    ).read_bytes()
    assert source == mirror
    assert (
        sha256_bytes(source)
        == "sha256:3d7b20af32890a02aeada3bb5727bfa1b7db15365d0c6021e848dc1e73ab5780"
    )
    for version, expected in (
        (1, "a81f556811c74a93faf8635e492ec92a5791948428f9995179b27dea77bc640b"),
        (2, "c22b5907a5b4d9be22b710da89973e445485a89c858a6758d9c568301daaaf40"),
    ):
        assert (
            sha256_bytes(
                (
                    root
                    / f"schemas/knowledge/system-rag-similarity-materials-v{version}.schema.json"
                ).read_bytes()
            )
            == "sha256:" + expected
        )
