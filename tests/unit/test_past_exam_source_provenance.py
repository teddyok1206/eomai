from __future__ import annotations

from collections import Counter
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_catalog_contracts import (
    AssessmentLayoutObservation,
    LegacyItemExtractionAcceptance,
    LegacyItemExtractionBatchManifestV2,
    LegacyItemExtractionResult,
    validate_contract,
)
from eom_catalog_service import knowledge_analysis_sources as sources
from eom_catalog_service import past_exam_source_provenance as provenance
from eom_catalog_service.artifacts import CatalogArtifactReader
from eom_catalog_service.legacy_assessment_models import (
    AssessmentLayoutObservationRecord,
    AssessmentSourceBundleRevisionRecord,
    LegacyItemExtractionAcceptanceRecord,
    LegacyItemExtractionDecisionRecord,
)
from eom_catalog_service.legacy_item_extraction_batch_models import (
    LegacyItemExtractionBatchRecord,
    LegacyItemExtractionBatchWorkUnitRecord,
)
from eom_catalog_service.models import ItemComponentRecord, ItemRevisionRecord
from eom_catalog_service.past_exam_source_provenance import (
    PastExamProvenanceMember,
    PastExamSourceResolutionCache,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import ValidationError as SchemaError
from sqlalchemy.orm import Session

from tests.unit.test_legacy_assessment_contracts import _acceptance, _result
from tests.unit.test_legacy_extraction_batch_contracts import _manifest_v2


def _rehash(value: dict[str, Any], field: str) -> dict[str, Any]:
    return {
        **value,
        field: content_sha256({key: row for key, row in value.items() if key != field}),
    }


def _documents() -> dict[str, dict[str, Any]]:
    batch = _manifest_v2().model_dump(mode="json")
    request = batch["work_units"][0]["request"]
    layout = _rehash(
        {
            "schema_version": "assessment-layout-observation/1.0",
            "assessment_layout_observation_id": request["layout_observation"][
                "assessment_layout_observation_id"
            ],
            "bundle": request["bundle"],
            "pages": [
                {
                    "page": page,
                    "observation_state": "OBSERVED",
                    "visible_item_numbers": [1],
                }
                for page in request["page_inputs"]
            ],
            "item_boundaries": [
                {
                    "boundary_id": "itemboundary_" + "1" * 32,
                    "item_number": 1,
                    "segments": [
                        {
                            "page_input_id": request["page_inputs"][0]["page_input_id"],
                            "bounding_box": {"left": 0, "top": 0, "right": 9000, "bottom": 9000},
                            "reading_ordinal": 1,
                        }
                    ],
                    "continues_across_pages": False,
                    "confidence_milli": 1000,
                }
            ],
            "expected_item_numbers": [1],
            "conflicts": [],
            "created_at": "2026-09-01T00:00:00Z",
        },
        "observation_sha256",
    )
    request["layout_observation"]["observation_sha256"] = layout["observation_sha256"]
    request["layout_observation"]["artifact"]["sha256"] = sha256_bytes(canonical_json_bytes(layout))
    request = _rehash(request, "request_sha256")
    batch["work_units"][0]["request"] = request
    batch = _rehash(batch, "manifest_sha256")
    result = cast(dict[str, Any], _result())
    result["extraction_request_id"] = request["extraction_request_id"]
    result["request_sha256"] = request["request_sha256"]
    result["observed_page_input_ids"] = [page["page_input_id"] for page in request["page_inputs"]]
    for anchor in result["items"][0]["source_anchors"]:
        anchor["source"] = request["page_inputs"][0]["image"]
        anchor["source_role"] = "PROBLEM_DOCUMENT"
    result = _rehash(result, "result_sha256")
    accepted = _acceptance(LegacyItemExtractionResult.model_validate(result)).model_dump(
        mode="json"
    )
    accepted["extraction_result"]["artifact"]["sha256"] = sha256_bytes(canonical_json_bytes(result))
    # Keep result and layout Artifact identities distinct in the owner fixture.
    accepted["extraction_result"]["artifact"]["artifact_id"] = "artifact_" + "a" * 32
    accepted["extraction_result"]["artifact"]["artifact_revision_id"] = "rev_" + "a" * 32
    accepted = _rehash(accepted, "acceptance_sha256")
    return {
        "batch.json": batch,
        "acceptance.json": accepted,
        "result.json": result,
        "layout.json": layout,
    }


def _member(name: str, document: dict[str, Any]) -> PastExamProvenanceMember:
    refs = {
        "batch.json": "eom://schemas/legacy-knowledge/legacy-item-extraction-batch/1.1",
        "acceptance.json": "eom://schemas/legacy-assessment/legacy-item-extraction-acceptance/1.0",
        "result.json": "eom://schemas/legacy-assessment/legacy-item-extraction-result/1.0",
        "layout.json": "eom://schemas/legacy-assessment/assessment-layout-observation/1.0",
    }
    seed = {"batch.json": "b", "acceptance.json": "c", "result.json": "a", "layout.json": "4"}[name]
    return PastExamProvenanceMember(
        artifact_id="artifact_" + seed * 32,
        artifact_revision_id="rev_" + seed * 32,
        member_path=name,
        sha256=sha256_bytes(canonical_json_bytes(document)),
        schema_ref=refs[name],
        media_type="application/json",
        max_bytes=sources.MAX_DOCUMENT_JSON_BYTES,
    )


class _Reader:
    def __init__(self, documents: dict[str, dict[str, Any]]) -> None:
        self.payloads = {name: canonical_json_bytes(value) for name, value in documents.items()}
        self.calls: list[dict[str, Any]] = []
        self.fail_next = False
        self.settings = cast(Any, SimpleNamespace())

    def read_member(self, **kwargs: Any) -> bytes:
        self.calls.append(kwargs)
        if self.fail_next:
            self.fail_next = False
            raise ValueError("invalid member")
        raw = self.payloads[kwargs["member_path"]]
        if sha256_bytes(raw) != kwargs["sha256"] or len(raw) > kwargs["max_bytes"]:
            raise ValueError("member hash/size differs")
        return raw

    def verify_member(self, **_kwargs: Any) -> None:
        pass


def _decode_all(
    cache: PastExamSourceResolutionCache, reader: _Reader, documents: dict[str, Any]
) -> tuple[Any, ...]:
    port = cast(CatalogArtifactReader, reader)
    return (
        cache.batch(port, _member("batch.json", documents["batch.json"])),
        cache.acceptance(port, _member("acceptance.json", documents["acceptance.json"])),
        cache.result(port, _member("result.json", documents["result.json"])),
        cache.layout(port, _member("layout.json", documents["layout.json"])),
    )


def test_exact_shared_members_decode_once_and_indexes_preserve_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    documents = _documents()
    reader = _Reader(documents)
    cache = PastExamSourceResolutionCache()
    validations: Counter[str] = Counter()
    original = validate_contract

    def validate(name: str, value: dict[str, Any]) -> None:
        validations[name] += 1
        original(name, value)

    monkeypatch.setattr(provenance, "validate_contract", validate)
    values = _decode_all(cache, reader, documents)
    for _ in range(520):
        assert _decode_all(cache, reader, documents) == values
    assert len(reader.calls) == 4
    assert set(validations.values()) == {1}
    batch, acceptance, result, layout = values
    assert batch.work_units_by_id[batch.value.work_units[0].work_unit_id] == batch.value.work_units
    item = result.value.items[0]
    identity = (item.item_proposal_id, item.item_number)
    assert acceptance.decisions_by_item[identity] == acceptance.value.item_decisions
    assert result.proposals_by_item[identity] == result.value.items
    assert layout.boundaries_by_item[item.item_number] == layout.value.item_boundaries
    with pytest.raises(TypeError):
        batch.work_units_by_id["fake"] = ()


@pytest.mark.parametrize(
    "field,new_value",
    [
        ("artifact_id", "artifact_" + "d" * 32),
        ("artifact_revision_id", "rev_" + "d" * 32),
        ("member_path", "alias.json"),
        ("schema_ref", "eom://schemas/alias/1.0"),
        ("media_type", "application/json; charset=utf-8"),
        ("max_bytes", sources.MAX_DOCUMENT_JSON_BYTES - 1),
    ],
)
def test_member_key_keeps_every_pointer_field(field: str, new_value: Any) -> None:
    documents = _documents()
    reader = _Reader(documents)
    reader.payloads["alias.json"] = reader.payloads["batch.json"]
    cache = PastExamSourceResolutionCache()
    member = _member("batch.json", documents["batch.json"])
    cache.batch(cast(CatalogArtifactReader, reader), member)
    cache.batch(cast(CatalogArtifactReader, reader), replace(member, **{field: new_value}))
    assert len(reader.calls) == 2


def test_changed_hash_and_decoder_kind_cannot_hit_existing_value() -> None:
    documents = _documents()
    reader = _Reader(documents)
    cache = PastExamSourceResolutionCache()
    member = _member("batch.json", documents["batch.json"])
    cache.batch(cast(CatalogArtifactReader, reader), member)
    with pytest.raises(ValueError, match="hash"):
        cache.batch(
            cast(CatalogArtifactReader, reader), replace(member, sha256="sha256:" + "0" * 64)
        )
    with pytest.raises(SchemaError):
        cache.acceptance(cast(CatalogArtifactReader, reader), member)
    assert len(reader.calls) == 3


def test_failed_read_and_failed_validation_are_not_cached() -> None:
    documents = _documents()
    reader = _Reader(documents)
    cache = PastExamSourceResolutionCache()
    member = _member("batch.json", documents["batch.json"])
    reader.fail_next = True
    with pytest.raises(ValueError):
        cache.batch(cast(CatalogArtifactReader, reader), member)
    assert cache.batch(cast(CatalogArtifactReader, reader), member).value.work_units
    invalid = {**documents["batch.json"], "manifest_sha256": "sha256:" + "0" * 64}
    reader.payloads["bad.json"] = canonical_json_bytes(invalid)
    bad = replace(member, member_path="bad.json", sha256=sha256_bytes(reader.payloads["bad.json"]))
    for _ in range(2):
        with pytest.raises(ValueError, match="manifest hash"):
            cache.batch(cast(CatalogArtifactReader, reader), bad)
    assert len(reader.calls) == 4


@pytest.mark.parametrize(
    "budget",
    [
        {"max_source_bytes": 0},
        {"max_members": 0},
        {"max_index_rows": 0},
    ],
)
def test_budget_overflow_returns_complete_validated_uncached_value(budget: dict[str, int]) -> None:
    documents = _documents()
    reader = _Reader(documents)
    cache = PastExamSourceResolutionCache(**budget)
    first = _decode_all(cache, reader, documents)
    second = _decode_all(cache, reader, documents)
    assert first == second
    assert len(reader.calls) == 8
    assert first[0].value == LegacyItemExtractionBatchManifestV2.model_validate(
        documents["batch.json"]
    )


def test_distinct_owner_requests_cannot_reuse_member_validation() -> None:
    documents = _documents()
    reader = _Reader(documents)
    assert _decode_all(PastExamSourceResolutionCache(), reader, documents) == _decode_all(
        PastExamSourceResolutionCache(), reader, documents
    )
    assert len(reader.calls) == 8


@pytest.mark.parametrize("bad_budget", [-1, True, 1.5])
def test_invalid_budget_is_rejected(bad_budget: Any) -> None:
    with pytest.raises(ValueError, match="budgets"):
        PastExamSourceResolutionCache(max_members=bad_budget)


@pytest.mark.parametrize(
    "kind,field",
    [
        ("batch", "work_units"),
        ("acceptance", "item_decisions"),
        ("result", "items"),
        ("layout", "item_boundaries"),
    ],
)
def test_duplicate_provenance_is_not_hidden_by_dict_index(kind: str, field: str) -> None:
    documents = _documents()
    name = {
        "batch": "batch.json",
        "acceptance": "acceptance.json",
        "result": "result.json",
        "layout": "layout.json",
    }[kind]
    value = documents[name]
    value[field].append(value[field][0])
    reader = _Reader(documents)
    cache = PastExamSourceResolutionCache()
    loader = getattr(cache, kind)
    for _ in range(2):
        with pytest.raises((ValueError, SchemaError)):
            loader(cast(CatalogArtifactReader, reader), _member(name, value))
    assert len(reader.calls) == 2


def test_layout_position_collision_keeps_existing_last_wins_meaning() -> None:
    documents = _documents()
    layout = documents["layout.json"]
    second = {**layout["pages"][0], "page": dict(layout["pages"][0]["page"])}
    second["page"]["page_input_id"] = "assessmentpage_" + "f" * 32
    second["page"]["workspace_relative_path"] = "source/pages/assessmentpage_" + "f" * 32 + ".png"
    layout["pages"].append(second)
    documents["layout.json"] = _rehash(layout, "observation_sha256")
    reader = _Reader(documents)
    result = PastExamSourceResolutionCache().layout(
        cast(CatalogArtifactReader, reader), _member("layout.json", documents["layout.json"])
    )
    assert result.pages_by_position[("PROBLEM_DOCUMENT", 1)] == result.value.pages[-1].page
    assert len(result.pages_by_id) == 2


class _SourceSession:
    def __init__(
        self, records: dict[type[Any], Any], component: Any, decision: Any, unit: Any
    ) -> None:
        self.records, self.component, self.decision, self.unit = records, component, decision, unit

    def get(self, model: type[Any], _identifier: str) -> Any:
        return self.records.get(model)

    def scalars(self, statement: Any) -> tuple[Any, ...]:
        entity = statement.column_descriptions[0]["entity"]
        if entity is LegacyItemExtractionDecisionRecord:
            return (self.decision,)
        if entity is LegacyItemExtractionBatchWorkUnitRecord:
            return (self.unit,)
        if entity is ItemComponentRecord:
            # The media correction lookup requests OTHER, not ITEM_CONTENT.
            return () if "component_type" not in str(statement) else (self.component,)
        raise AssertionError("unexpected fake query")


def _source_fixture(monkeypatch: pytest.MonkeyPatch) -> tuple[Session, _Reader, dict[str, Any]]:
    documents = _documents()
    reader = _Reader(documents)
    batch = LegacyItemExtractionBatchManifestV2.model_validate(documents["batch.json"])
    unit = batch.work_units[0]
    request = unit.request
    result = LegacyItemExtractionResult.model_validate(documents["result.json"])
    acceptance = LegacyItemExtractionAcceptance.model_validate(documents["acceptance.json"])
    layout = AssessmentLayoutObservation.model_validate(documents["layout.json"])
    proposal = result.items[0]
    item_revision_id = "itemrev_" + "7" * 32
    component = SimpleNamespace(
        required=True,
        media_type="application/json",
        schema_ref="eom.assessment.item-content/1.0",
        artifact_id="artifact_" + "7" * 32,
        artifact_revision_id="rev_" + "7" * 32,
        logical_name="assessment-item-content.json",
        sha256=content_sha256(proposal.item_content.model_dump(mode="json")),
    )
    revision = SimpleNamespace(
        item_id="item_" + "7" * 32,
        item_revision_id=item_revision_id,
        revision_state="APPROVED",
        metadata_json={
            "source_kind": "PAST_EXAM",
            "extraction_acceptance_id": acceptance.acceptance_id,
            "extraction_result_id": result.extraction_result_id,
            "item_proposal_id": proposal.item_proposal_id,
            "item_number": proposal.item_number,
        },
    )
    accepted_record = SimpleNamespace(
        acceptance_id=acceptance.acceptance_id,
        state=acceptance.state,
        coverage_state=acceptance.coverage_state,
        extraction_result_id=result.extraction_result_id,
        result_sha256=result.result_sha256,
        acceptance_sha256=acceptance.acceptance_sha256,
    )
    for prefix, name in (("acceptance", "acceptance.json"), ("result", "result.json")):
        pointer = _member(name, documents[name])
        for field, value in {
            "id": pointer.artifact_id,
            "revision_id": pointer.artifact_revision_id,
            "member_path": pointer.member_path,
            "schema_ref": pointer.schema_ref,
            "media_type": pointer.media_type,
            "sha256": pointer.sha256,
        }.items():
            setattr(accepted_record, prefix + "_artifact_" + field, value)
    batch_record = SimpleNamespace(
        extraction_batch_id=batch.extraction_batch_id, manifest_sha256=batch.manifest_sha256
    )
    batch_pointer = _member("batch.json", documents["batch.json"])
    layout_pointer = _member("layout.json", documents["layout.json"])
    for field, value in {
        "id": batch_pointer.artifact_id,
        "revision_id": batch_pointer.artifact_revision_id,
        "member_path": batch_pointer.member_path,
        "schema_ref": batch_pointer.schema_ref,
        "media_type": batch_pointer.media_type,
        "sha256": batch_pointer.sha256,
    }.items():
        setattr(batch_record, "manifest_artifact_" + field, value)
    layout_record = SimpleNamespace(
        assessment_layout_observation_id=layout.assessment_layout_observation_id
    )
    for field, value in {
        "id": layout_pointer.artifact_id,
        "revision_id": layout_pointer.artifact_revision_id,
        "member_path": layout_pointer.member_path,
        "schema_ref": layout_pointer.schema_ref,
        "media_type": layout_pointer.media_type,
        "sha256": layout_pointer.sha256,
    }.items():
        setattr(layout_record, "artifact_" + field, value)
    work_unit = SimpleNamespace(
        work_unit_id=unit.work_unit_id,
        extraction_batch_id=batch.extraction_batch_id,
        extraction_request_id=request.extraction_request_id,
        request_sha256=request.request_sha256,
        assessment_source_bundle_id=request.bundle.assessment_source_bundle_id,
        assessment_source_bundle_revision_id=request.bundle.assessment_source_bundle_revision_id,
        bundle_manifest_sha256=request.bundle.bundle_manifest_sha256,
        result_sha256=result.result_sha256,
        acceptance_sha256=acceptance.acceptance_sha256,
    )
    decision = SimpleNamespace(decision="ACCEPT")
    bundle = SimpleNamespace(**request.bundle.model_dump(), state="REVIEWED")
    fake = _SourceSession(
        {
            ItemRevisionRecord: revision,
            LegacyItemExtractionAcceptanceRecord: accepted_record,
            LegacyItemExtractionBatchRecord: batch_record,
            AssessmentSourceBundleRevisionRecord: bundle,
            AssessmentLayoutObservationRecord: layout_record,
        },
        component,
        decision,
        work_unit,
    )
    # Only current Artifact metadata reads are mocked; exact JSON bytes, schema,
    # self hashes and the complete source-chain comparisons are real pure code.
    approved = {"value": True}

    def resolve_member(_session: Session, **kwargs: Any) -> tuple[Any, Any, dict[str, Any]]:
        if not approved["value"]:
            raise sources.KnowledgeAnalysisSourceError(
                "KNOWLEDGE_ANALYSIS_SOURCE_STALE", "unapproved"
            )
        return SimpleNamespace(), SimpleNamespace(content_bytes=512), {"bytes": 512}

    monkeypatch.setattr(sources, "_resolve_artifact_member", resolve_member)
    monkeypatch.setattr(
        sources, "expected_promoted_legacy_item_content", lambda *_a, **_k: proposal.item_content
    )
    return (
        cast(Session, fake),
        reader,
        {
            "revision": revision,
            "acceptance": accepted_record,
            "decision": decision,
            "unit": work_unit,
            "approved": approved,
            "item_revision_id": item_revision_id,
        },
    )


def test_cached_source_output_matches_uncached_and_rechecks_current_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, reader, state = _source_fixture(monkeypatch)
    kwargs = {
        "artifacts": cast(CatalogArtifactReader, reader),
        "item_revision_id": state["item_revision_id"],
        "source_class": "PAST_EXAM",
    }
    uncached = sources.resolve_historically_approved_item_source(session, **kwargs)
    cache = PastExamSourceResolutionCache()
    cached = sources.resolve_historically_approved_item_source(
        session, past_exam_cache=cache, **kwargs
    )
    assert cached == uncached
    assert (
        sources.resolve_historically_approved_item_source(session, past_exam_cache=cache, **kwargs)
        == cached
    )
    assert len(reader.calls) == 8
    state["decision"].decision = "REJECT"
    with pytest.raises(sources.KnowledgeAnalysisSourceError):
        sources.resolve_historically_approved_item_source(session, past_exam_cache=cache, **kwargs)
    state["decision"].decision = "ACCEPT"
    state["acceptance"].coverage_state = "INCOMPLETE"
    with pytest.raises(sources.KnowledgeAnalysisSourceError):
        sources.resolve_historically_approved_item_source(session, past_exam_cache=cache, **kwargs)
    state["acceptance"].coverage_state = "COMPLETE"
    state["approved"]["value"] = False
    with pytest.raises(sources.KnowledgeAnalysisSourceError):
        sources.resolve_historically_approved_item_source(session, past_exam_cache=cache, **kwargs)
    state["approved"]["value"] = True
    state["revision"].revision_state = "DRAFT"
    with pytest.raises(sources.KnowledgeAnalysisSourceError):
        sources.resolve_historically_approved_item_source(session, past_exam_cache=cache, **kwargs)
    state["revision"].revision_state = "APPROVED"
    original_request_hash = state["unit"].request_sha256
    state["unit"].request_sha256 = "sha256:" + "0" * 64
    with pytest.raises(sources.KnowledgeAnalysisSourceError):
        sources.resolve_historically_approved_item_source(session, past_exam_cache=cache, **kwargs)
    state["unit"].request_sha256 = original_request_hash
    assert (
        sources.resolve_historically_approved_item_source(session, past_exam_cache=cache, **kwargs)
        == cached
    )
    assert len(reader.calls) == 8


def test_new_snapshot_source_cache_always_has_its_own_provenance_cache() -> None:
    from eom_catalog_service.knowledge_retrieval_service import (
        _RequestScopedArtifactValidationCache,
        _SnapshotSourceResolutionCache,
    )

    reader = cast(CatalogArtifactReader, _Reader(_documents()))
    first = _SnapshotSourceResolutionCache({}, {}, _RequestScopedArtifactValidationCache(reader))
    second = _SnapshotSourceResolutionCache({}, {}, _RequestScopedArtifactValidationCache(reader))
    assert first.past_exam_provenance is not second.past_exam_provenance


@pytest.mark.parametrize("units", [8, 64])
def test_shared_batch_validation_cost_tracks_unique_member_not_item_count(
    units: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = _documents()["batch.json"]
    template = document["work_units"][0]
    work_units = []
    for ordinal in range(units):
        # Rebuild valid reviewed requests, not model_construct/fake schema grants.
        request = dict(template["request"])
        request["work_unit_ordinal"] = ordinal
        request["extraction_request_id"] = "itemextractreq_" + f"{ordinal + 1:032x}"
        work_units.append(
            {
                **template,
                "work_unit_id": "legacyworkunit_" + f"{ordinal + 1:032x}",
                "ordinal": ordinal,
                "request": _rehash(request, "request_sha256"),
            }
        )
    document["work_units"] = work_units
    document = _rehash(document, "manifest_sha256")
    reader = _Reader({"batch.json": document})
    member = _member("batch.json", document)
    full_validations = 0

    def validate(name: str, value: dict[str, Any]) -> None:
        nonlocal full_validations
        full_validations += 1
        validate_contract(name, value)

    monkeypatch.setattr(provenance, "validate_contract", validate)
    cache = PastExamSourceResolutionCache()
    for unit in work_units:
        decoded = cache.batch(cast(CatalogArtifactReader, reader), member)
        assert decoded.work_units_by_id[unit["work_unit_id"]][0].ordinal == unit["ordinal"]
    assert full_validations == 1
    assert len(reader.calls) == 1
    assert len(decoded.work_units_by_id) == units


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b"[]"])
def test_ambiguous_or_nonobject_json_does_not_create_cache_entry(raw: bytes) -> None:
    documents = _documents()
    reader = _Reader(documents)
    reader.payloads["batch.json"] = raw
    member = replace(_member("batch.json", documents["batch.json"]), sha256=sha256_bytes(raw))
    cache = PastExamSourceResolutionCache()
    for _ in range(2):
        with pytest.raises(ValueError):
            cache.batch(cast(CatalogArtifactReader, reader), member)
    assert len(reader.calls) == 2
