"""Synthetic fixed25 source/row observations; not live or educational acceptance."""

from __future__ import annotations

import json
from dataclasses import replace
from itertools import combinations

import pytest
from eom_catalog_contracts.assessment_assembly import build_mock_exam_assembly_cohort
from eom_catalog_contracts.embedding_reference_query import ReferenceQuerySpaces
from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_contracts.exam_similarity_observation import (
    ExamSimilarityObservation,
    parse_exam_observation_request,
    parse_exam_similarity_observation,
)
from eom_catalog_contracts.inference_transfer_experiment import VIEWS, StagedExperimentEntry
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_catalog_contracts.similarity_context import SimilarityIndexPin, SimilarityViewSelection
from eom_catalog_contracts.validation import load_schema
from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow
from eom_catalog_service.embedding_registry_ports import (
    AuthorizedEmbeddingReadProfile,
    EmbeddingRegistryLookup,
    EmbeddingRegistryRead,
    MaterializedEmbeddingReadRow,
    ResolvedPinnedEmbeddingIndex,
)
from eom_catalog_service.exam_similarity_observation import compose_exam_similarity_observation
from eom_catalog_service.similarity_context_ports import (
    PreparedSimilaritySource,
    SimilarityContextReadError,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import (
    PARTITION,
    embedding_entry,
    embedding_space,
    index_manifest,
    index_pointer,
    seal,
    source_binding,
)
from tests.unit.inference_transfer_fixtures import sha


def exam_entries(*, distinct_content: bool = False) -> tuple[StagedExperimentEntry, ...]:
    entries = []
    for position in range(1, 26):
        value = embedding_entry().model_dump(mode="json")
        seed = f"{position:032x}"
        profile = value["profile"]
        profile["source_basis"]["source"].update(
            item_id="item_" + seed, item_revision_id="itemrev_" + seed
        )
        profile.update(
            profile_id="inferenceprofile_" + seed,
            profile_revision_id="inferenceprofilerev_" + seed,
        )
        value["profile"] = seal(profile, "profile_sha256")
        if distinct_content:
            value["content"]["text"] += f" 합성 표본 {position}."
            value["content"]["text_sha256"] = content_sha256(value["content"]["text"])
        entries.append(StagedExperimentEntry.model_validate(value))
    return tuple(entries)


def exam_case(*, available: int = 25, indexes: bool = True, distinct_content: bool = False):
    entries = exam_entries(distinct_content=distinct_content)
    prepared = tuple(
        PreparedSimilaritySource(
            entry.profile.source_basis.source,
            InferenceTransferProfilePointer.from_profile(entry.profile)
            if position < available
            else None,
            entry.profile.source_basis.solution_evidence if position < available else None,
        )
        for position, entry in enumerate(entries)
    )
    selections, reads = [], []
    for view, seed in zip(VIEWS, "123", strict=True):
        bindings = tuple(source_binding(entry, view=view) for entry in entries[:available])
        # An empty index pin is still a real fixture manifest, not a missing binding fallback.
        index = index_manifest(
            *(bindings or (source_binding(entries[0], view=view),)), view=view, revision_seed=seed
        )
        selection = SimilarityViewSelection(
            view=view,
            recipe=index.recipe,
            index=SimilarityIndexPin(
                index_id=index.index_id,
                index_revision_id=index.index_revision_id,
                index_manifest=index_pointer(index, seed),
                index_sha256=index.index_sha256,
                storage_partition=PARTITION,
                spaces=ReferenceQuerySpaces(
                    document=index.space, query=embedding_space(purpose="QUERY")
                ),
            )
            if indexes
            else None,
        )
        selections.append(selection)
        if not indexes:
            continue
        numeric = {
            binding.encoding.encoding_sha256: MaterializedEmbeddingReadRow(
                RegisteredEmbeddingRow(binding.encoding, binding.row_ref),
                (1.0,) + (0.0,) * (index.space.model_spec.dimension - 1),
            )
            for binding in bindings
        }
        reads.append(
            ResolvedPinnedEmbeddingIndex(
                EmbeddingRegistryRead(
                    EmbeddingRegistryLookup(
                        "corpus_" + "1" * 32,
                        EmbeddingIndexNamespace(
                            storage_partition=PARTITION,
                            space_sha256=index.space.space_sha256,
                            view=view,
                            recipe_sha256=index.recipe.recipe_sha256,
                            population_scope="ALL_ADMITTED_GRAPH_ITEMS",
                        ),
                        entries[0].profile.source_basis.graph_snapshot,
                        "accessrev_" + "d" * 32,
                        sha("d"),
                        25,
                    ),
                    selection,
                ),
                tuple(value.source for value in prepared),
                tuple(
                    AuthorizedEmbeddingReadProfile(value.source.item_revision_id, value.profile)
                    for value in prepared
                    if value.profile is not None
                ),
                bindings,
                tuple(numeric.values()),
            )
        )
    body = {
        "schema_version": "system-rag-exam-observation-request/1.0",
        "consumer_purpose": "MOCK_EXAM_OBSERVATION",
        "cohort": build_mock_exam_assembly_cohort(
            tuple(value.source.item_revision_id for value in prepared)
        ).model_dump(mode="json"),
        "graph_snapshot": entries[0].profile.source_basis.graph_snapshot.model_dump(mode="json"),
        "policy_revision_id": "accessrev_" + "d" * 32,
        "policy_sha256": sha("d"),
        "source_classes": ["PAST_EXAM"],
        "views": [selection.model_dump(mode="json") for selection in selections],
    }
    return parse_exam_observation_request(seal(body, "request_sha256")), prepared, tuple(reads)


def test_fixed25_all900_pairs_are_ordered_and_shared_encoding_is_not_duplicated():
    request, sources, reads = exam_case()
    result = compose_exam_similarity_observation(request, sources, reads)
    assert result.status == "READY"
    assert len(result.members) == 25 and len(result.views) == 3
    for observation, read in zip(result.views, reads, strict=True):
        assert len(observation.rows) == 25 and len(observation.pairs) == 300
        assert tuple((p.left_position, p.right_position) for p in observation.pairs) == tuple(
            combinations(range(1, 26), 2)
        )
        assert {p.cosine_millionths for p in observation.pairs} == {1000000}
        assert len(read.numerical_rows) == 1  # canonical identical encodings are reused
    assert parse_exam_similarity_observation(json.loads(canonical_json_bytes(result))) == result
    assert len(canonical_json_bytes(result)) < 1024 * 1024


@pytest.mark.parametrize("available", (0, 1, 2, 12, 24))
def test_exact_partial_denominators_never_become_fake_zero_vectors(available):
    request, sources, reads = exam_case(available=available)
    result = compose_exam_similarity_observation(request, sources, reads)
    assert result.status == ("PARTIAL" if available >= 2 else "EMPTY")
    assert sum(m.reference.profile is not None for m in result.members) == available
    assert all(len(v.rows) == available for v in result.views)
    assert all(len(v.pairs) == available * (available - 1) // 2 for v in result.views)


def test_unprepared_indexes_are_explicit_and_no_query_is_invented():
    request, sources, reads = exam_case(indexes=False)
    result = compose_exam_similarity_observation(request, sources, reads)
    assert result.status == "EMPTY" and reads == ()
    assert all(
        v.status == "INDEX_NOT_PREPARED" and not v.rows and not v.pairs for v in result.views
    )
    assert b"query_execution" not in canonical_json_bytes(result)


def test_negative_and_orthogonal_document_pairs_do_not_become_probabilities():
    request, sources, reads = exam_case(distinct_content=True)
    rows = reads[0].numerical_rows
    negative = (-1.0, *rows[1].values[1:])
    orthogonal = (0.0, 1.0, *rows[2].values[2:])
    changed = (
        rows[0],
        replace(rows[1], values=negative),
        replace(rows[2], values=orthogonal),
        *rows[3:],
    )
    reads = (replace(reads[0], numerical_rows=changed), *reads[1:])
    result = compose_exam_similarity_observation(request, sources, reads)
    first = result.views[0].pairs
    assert (first[0].left_position, first[0].right_position, first[0].cosine_millionths) == (
        1,
        2,
        -1000000,
    )
    assert first[1].cosine_millionths == 0
    assert {p.cosine_millionths for p in result.views[1].pairs} == {1000000}


@pytest.mark.parametrize("fault", ("source", "duplicate", "binding", "norm", "nan", "dimension"))
def test_untrusted_materialized_values_fail_closed(fault):
    request, sources, reads = exam_case()
    if fault == "source":
        sources = sources[:-1]
    elif fault == "duplicate":
        sources = sources[:-1] + sources[:1]
    elif fault == "binding":
        reads = (replace(reads[0], bindings=reads[0].bindings + reads[0].bindings[:1]), *reads[1:])
    else:
        row = reads[0].numerical_rows[0]
        values = (
            (2.0, *row.values[1:])
            if fault == "norm"
            else (float("nan"), *row.values[1:])
            if fault == "nan"
            else row.values[:-1]
        )
        reads = (replace(reads[0], numerical_rows=(replace(row, values=values),)), *reads[1:])
    with pytest.raises(SimilarityContextReadError):
        compose_exam_similarity_observation(request, sources, reads)


@pytest.mark.parametrize("fault", ("hash", "order", "extra", "pair", "member", "coverage"))
def test_protocol_rejects_forged_result_even_with_recomputed_hash(fault):
    request, sources, reads = exam_case()
    result = compose_exam_similarity_observation(request, sources, reads)
    body = result.model_dump(mode="json")
    if fault == "hash":
        body["result_sha256"] = sha("f")
    elif fault == "order":
        body["views"].reverse()
    elif fault == "extra":
        body["approval"] = "APPROVED"
    elif fault == "pair":
        body["views"][0]["pairs"].pop()
    elif fault == "member":
        body["members"][0], body["members"][1] = body["members"][1], body["members"][0]
    else:
        body["status"] = "PARTIAL"
    if fault != "hash":
        body = seal(body, "result_sha256")
    with pytest.raises((ValueError, SchemaError)):
        ExamSimilarityObservation.model_validate(body)


def test_schema_202012_is_registered_and_request_cannot_claim_authority():
    Draft202012Validator.check_schema(load_schema("system-rag-exam-observation"))
    request, _, _ = exam_case()
    body = request.model_dump(mode="json") | {"operator_id": "admin"}
    with pytest.raises((ValueError, SchemaError)):
        parse_exam_observation_request(seal(body, "request_sha256"))
