"""Synthetic approved-reference projections; no current source permission or model run."""

from __future__ import annotations

from pathlib import Path

import pytest
from eom_catalog_contracts.inference_transfer_experiment import StagedExperimentEntry
from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferProfilePointer,
)
from eom_catalog_contracts.similarity_context import parse_similarity_context
from eom_catalog_contracts.similarity_materials import (
    MAX_SIMILARITY_MATERIALS_BYTES,
    build_similarity_materials,
    parse_similarity_materials,
    validate_similarity_materials,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import embedding_entry, seal
from tests.unit.test_similarity_context_contracts import context_body

ROOT = Path(__file__).resolve().parents[2]
ERRORS = (ValueError, SchemaError)


def materials_case(*, count=1, missing_anchor=False):
    raw = context_body(ready=False, missing_report=missing_anchor)
    entries = tuple(embedding_entry(seed) for seed in ("b", "c")[:count])
    if count == 2:
        second = raw["candidates"][0].copy()
        second.update(
            source=entries[1].profile.source_basis.source.model_dump(mode="json"),
            profile=InferenceTransferProfilePointer.from_profile(entries[1].profile).model_dump(
                mode="json"
            ),
            solution_evidence=entries[1].profile.source_basis.solution_evidence.model_dump(
                mode="json"
            ),
            observations=[{"channel": "GRAPH_LEXICAL", "rank": 2, "graph_relevance_milli": 1700}],
        )
        raw["candidates"].append(second)
        raw["population"]["authorized_source_count"] = 3
        raw["population"]["accepted_profile_count"] += 1
    context = parse_similarity_context(seal(raw, "context_sha256"))
    anchor = None if missing_anchor else embedding_entry().profile
    return context, anchor, entries


def test_closed_packaged_materials_schema_keeps_exact_existing_projection_refs() -> None:
    resource = CATALOG_SCHEMA_RESOURCES["system-rag-similarity-materials"]
    raw = (ROOT / resource.canonical_path).read_bytes()
    assert (
        raw
        == (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    assert (
        sha256_bytes(raw)
        == resource.sha256
        == "sha256:a81f556811c74a93faf8635e492ec92a5791948428f9995179b27dea77bc640b"
    )
    Draft202012Validator.check_schema(load_schema("system-rag-similarity-materials"))


@pytest.mark.parametrize("missing_anchor", (False, True))
def test_original_profile_and_ordered_candidates_are_immutable_exact_projections(missing_anchor):
    context, anchor, entries = materials_case(count=2, missing_anchor=missing_anchor)
    materials = build_similarity_materials(context, anchor_profile=anchor, entries=entries)
    assert parse_similarity_materials(materials) == materials
    assert validate_similarity_materials(materials, context) == materials
    assert materials.anchor_profile == anchor
    assert materials.entries == entries
    assert materials.entries[0].content.text.startswith("마찰이 없는 물체 B")
    assert materials.materials_sha256 != sha256_bytes(
        canonical_json_bytes(materials.model_dump(mode="json"))
    )
    assert all(entry.limitations for entry in materials.entries)
    with pytest.raises(ValueError):
        materials.context_sha256 = "sha256:" + "0" * 64


@pytest.mark.parametrize(
    "fault", ("hash", "extra", "duplicate", "too_many", "copied_extra", "nested_bool", "missing")
)
def test_invalid_raw_materials_are_not_normalized_or_repaired(fault):
    context, anchor, entries = materials_case()
    materials = build_similarity_materials(context, anchor_profile=anchor, entries=entries)
    raw = materials.model_dump(mode="json")
    if fault == "hash":
        raw["materials_sha256"] = "sha256:" + "0" * 64
    elif fault == "extra":
        raw["permission"] = "ADMIN"
    elif fault == "duplicate":
        raw["entries"] *= 2
        raw = seal(raw, "materials_sha256")
    elif fault == "too_many":
        raw["entries"] *= 9
        raw = seal(raw, "materials_sha256")
    elif fault == "copied_extra":
        raw = materials.model_copy(update={"role": "WORKER"})
    elif fault == "nested_bool":
        raw["entries"][0]["profile"]["claims"][0]["inferred"] = 1
    else:
        raw.pop("anchor_profile")
    with pytest.raises(ERRORS):
        parse_similarity_materials(raw)


@pytest.mark.parametrize(
    "fault",
    (
        "context",
        "request",
        "order",
        "missing_entry",
        "missing_anchor",
        "wrong_anchor",
        "candidate_graph",
        "candidate_claim",
    ),
)
def test_valid_but_foreign_projection_cannot_satisfy_context_closure(fault):
    context, anchor, entries = materials_case(count=2)
    materials = build_similarity_materials(context, anchor_profile=anchor, entries=entries)
    raw = materials.model_dump(mode="json")
    if fault == "context":
        raw["context_sha256"] = "sha256:" + "0" * 64
    elif fault == "request":
        raw["request_sha256"] = "sha256:" + "0" * 64
    elif fault == "order":
        raw["entries"].reverse()
    elif fault == "missing_entry":
        raw["entries"].pop()
    elif fault == "missing_anchor":
        raw["anchor_profile"] = None
    elif fault == "wrong_anchor":
        raw["anchor_profile"]["source_basis"]["source"]["item_revision_id"] = "itemrev_" + "0" * 32
        raw["anchor_profile"] = seal(raw["anchor_profile"], "profile_sha256")
    else:
        profile = raw["entries"][0]["profile"]
        if fault == "candidate_graph":
            profile["source_basis"]["graph_snapshot"]["graph_snapshot_revision_id"] = (
                "graphrev_" + "0" * 32
            )
        else:
            profile["claims"][0]["text"] += " 다른 조건"
        raw["entries"][0]["profile"] = seal(profile, "profile_sha256")
    foreign = parse_similarity_materials(seal(raw, "materials_sha256"))
    with pytest.raises(ValueError, match="MISMATCH"):
        validate_similarity_materials(foreign, context)


def test_missing_decisive_claim_and_absent_text_are_not_fabricated():
    context, anchor, entries = materials_case()
    body = entries[0].model_dump(mode="json")
    body["profile"]["claims"] = []
    body["profile"]["limitations"].append("핵심 착상 근거 부족: 비교할 추론을 확인하지 못함")
    body["profile"] = seal(body["profile"], "profile_sha256")
    body["content"] = None
    entry = StagedExperimentEntry.model_validate(body)
    raw = context.model_dump(mode="json")
    raw["candidates"][0]["profile"] = InferenceTransferProfilePointer.from_profile(
        entry.profile
    ).model_dump(mode="json")
    context = parse_similarity_context(seal(raw, "context_sha256"))
    material = build_similarity_materials(context, anchor_profile=anchor, entries=(entry,))
    assert material.entries[0].content is None
    assert not material.entries[0].profile.claims
    assert material.entries[0].profile.limitations[-1].startswith("핵심 착상 근거 부족")


def test_materials_byte_budget_is_checked_before_untrusted_nested_validation():
    with pytest.raises(ValueError, match="byte budget"):
        parse_similarity_materials({"untrusted": "x" * MAX_SIMILARITY_MATERIALS_BYTES})
