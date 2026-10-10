"""Synthetic wire/hash closure tests; no database, model or source authority."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.inference_transfer_experiment import (
    CanonicalExperimentItemText,
    StagedExperimentEntry,
    SuppliedGraphBaseline,
)
from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotAuthorizeRequest,
    InferenceTransferSnapshotAuthorizeResult,
    InferenceTransferSnapshotChunkBudget,
    InferenceTransferSnapshotHeader,
    InferenceTransferSnapshotIndexEntry,
    InferenceTransferSnapshotPrepareRequest,
    InferenceTransferSnapshotPrepareResult,
    InferenceTransferSnapshotReadRequest,
    InferenceTransferSnapshotReadResult,
    InferenceTransferSnapshotRecord,
    parse_snapshot_request,
    parse_snapshot_result,
    snapshot_baseline_set_sha256,
    snapshot_entry_set_sha256,
    validate_snapshot_authorize_result,
    validate_snapshot_prepare_result,
    validate_snapshot_read_result,
    validate_snapshot_records,
)
from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferProfile,
    InferenceTransferProfilePointer,
)
from eom_catalog_contracts.knowledge import ApprovedPastExamItemKnowledgeSourceV3
from eom_catalog_contracts.validation import (
    CATALOG_SCHEMA_RESOURCES,
    load_schema,
    validate_contract,
)
from eom_identifiers import content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from tests.unit.inference_transfer_fixtures import sha
from tests.unit.inference_transfer_snapshot_fixtures import (
    hashed,
    snapshot_header,
    snapshot_prepare,
    snapshot_prepare_result,
    snapshot_read_request,
    snapshot_read_result,
    snapshot_records,
    snapshot_v3_record,
)


def rehash(body: dict[str, Any], name: str) -> dict[str, Any]:
    body = {key: value for key, value in body.items() if key != name}
    return body | {name: content_sha256(body)}


def authorize_pair() -> tuple[
    InferenceTransferSnapshotAuthorizeRequest, InferenceTransferSnapshotAuthorizeResult
]:
    read = snapshot_read_result()
    request = hashed(
        InferenceTransferSnapshotAuthorizeRequest,
        "authorization_sha256",
        header=snapshot_header(),
        staged_entry_set_sha256=snapshot_entry_set_sha256(
            tuple(row.staged_entry for row in read.records if row.staged_entry is not None)
        ),
        staged_baseline_set_sha256=snapshot_baseline_set_sha256(read.baselines),
    )
    result = hashed(
        InferenceTransferSnapshotAuthorizeResult,
        "result_sha256",
        header_sha256=request.header.header_sha256,
        authorization_sha256=request.authorization_sha256,
        source_count=request.header.source_count,
        profile_count=request.header.profile_count,
        missing_report_count=request.header.missing_report_count,
        staged_entry_set_sha256=request.staged_entry_set_sha256,
        staged_baseline_set_sha256=request.staged_baseline_set_sha256,
    )
    return request, result


def test_schema_first_resource_mirror_and_identity_are_exact() -> None:
    root = Path(__file__).resolve().parents[2]
    entry = CATALOG_SCHEMA_RESOURCES["item-inference-transfer-snapshot"]
    canonical = (root / entry.canonical_path).read_bytes()
    resource = (
        root / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
    ).read_bytes()
    assert canonical == resource
    assert sha256_bytes(canonical) == entry.sha256
    schema = load_schema("item-inference-transfer-snapshot")
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == "eom://schemas/knowledge/item-inference-transfer-snapshot/1.0"


def test_all_three_phases_schema_and_pydantic_round_trip() -> None:
    prepared = snapshot_prepare_result()
    read_request = snapshot_read_request(prepared)
    read_result = snapshot_read_result(request=read_request)
    authorize_request, authorize_result = authorize_pair()
    for request in (prepared.header.prepare, read_request, authorize_request):
        assert parse_snapshot_request(request.model_dump(mode="json")) == request
    for result in (prepared, read_result, authorize_result):
        assert parse_snapshot_result(result.model_dump(mode="json")) == result
    validate_snapshot_prepare_result(prepared.header.prepare, prepared)
    validate_snapshot_read_result(read_request, read_result, index=prepared.index)
    validate_snapshot_records(prepared.header, prepared.index, read_result.records)
    validate_snapshot_authorize_result(authorize_request, authorize_result)


@pytest.mark.parametrize(
    "field,value",
    [
        ("actor_id", "ADMIN"),
        ("role", "ADMIN"),
        ("permissions", ["ITEM_READ"]),
        ("path", "/mnt/nas/private"),
        ("latest", True),
    ],
)
def test_prepare_public_input_cannot_supply_authority_path_or_latest(
    field: str, value: Any
) -> None:
    body = snapshot_prepare().model_dump(mode="json") | {field: value}
    with pytest.raises(SchemaValidationError):
        parse_snapshot_request(body)
    with pytest.raises(ValidationError):
        InferenceTransferSnapshotPrepareRequest.model_validate(body)


@pytest.mark.parametrize("phase", ["READ", "AUTHORIZE"])
def test_later_public_input_has_no_separate_actor_permission_fields(phase: str) -> None:
    request = snapshot_read_request() if phase == "READ" else authorize_pair()[0]
    body = request.model_dump(mode="json") | {"actor_id": "forged-admin"}
    with pytest.raises(SchemaValidationError):
        parse_snapshot_request(body)


@pytest.mark.parametrize(
    "mutated",
    [
        {"source_classes": ("PAST_EXAM", "APPROVED_ITEM")},
        {"source_classes": ("PAST_EXAM", "PAST_EXAM")},
        {"query_item_revision_ids": ("itemrev_" + "b" * 32, "itemrev_" + "a" * 32)},
        {"query_item_revision_ids": ("itemrev_" + "a" * 32,) * 2},
        {"max_sources": True},
    ],
)
def test_prepare_canonical_order_bounds_and_scope(mutated: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        snapshot_prepare(**mutated)


def test_prepare_graph_pointer_hash_is_not_interchangeable() -> None:
    body = snapshot_prepare().model_dump(mode="json")
    body["graph_snapshot"]["manifest_sha256"] = sha("f")
    with pytest.raises(ValidationError, match="Graph artifact"):
        InferenceTransferSnapshotPrepareRequest.model_validate(rehash(body, "prepare_sha256"))


@pytest.mark.parametrize("field", ["prepare_sha256", "header_sha256", "result_sha256"])
def test_prepare_phase_rejects_hash_tampering(field: str) -> None:
    value = {
        "prepare_sha256": snapshot_prepare(),
        "header_sha256": snapshot_header(),
        "result_sha256": snapshot_prepare_result(),
    }[field]
    body = value.model_dump(mode="json") | {field: sha("0")}
    with pytest.raises(ValidationError, match=field):
        type(value).model_validate(body)


def test_counts_close_and_preserve_missing_reports_in_denominator() -> None:
    records = snapshot_records(missing_seed="b")
    prepared = snapshot_prepare_result(records)
    assert (
        prepared.header.source_count,
        prepared.header.profile_count,
        prepared.header.missing_report_count,
    ) == (3, 2, 1)
    assert prepared.index[1].profile is None
    assert records[1].staged_entry is None
    assert records[1].source.item_revision_id.endswith("b" * 32)
    validate_snapshot_records(prepared.header, prepared.index, records)
    body = prepared.header.model_dump(mode="json")
    body["missing_report_count"] = 0
    with pytest.raises(ValidationError, match="counts"):
        InferenceTransferSnapshotHeader.model_validate(rehash(body, "header_sha256"))


@pytest.mark.parametrize("profile_present", [True, False])
def test_index_report_presence_is_closed_in_schema_and_model(profile_present: bool) -> None:
    record = snapshot_records(missing_seed=None if profile_present else "a")[0]
    body = record.index_entry.model_dump(mode="json")
    body["solution_evidence_pointer_sha256"] = None if profile_present else sha("0")
    with pytest.raises(ValidationError, match="presence"):
        InferenceTransferSnapshotIndexEntry.model_validate(body)
    prepared = snapshot_prepare_result().model_dump(mode="json")
    prepared["index"][0] = body
    with pytest.raises(SchemaValidationError):
        validate_contract("item-inference-transfer-snapshot", prepared)


@pytest.mark.parametrize(
    "kind", ["reverse", "duplicate_base", "duplicate_item", "duplicate_profile"]
)
def test_index_order_and_three_identity_uniqueness_rules(kind: str) -> None:
    body = snapshot_prepare_result().model_dump(mode="json")
    rows = body["index"]
    if kind == "reverse":
        rows.reverse()
    elif kind == "duplicate_base":
        rows[1]["base_analysis_run_id"] = rows[0]["base_analysis_run_id"]
    elif kind == "duplicate_item":
        rows[1]["source_item_revision_id"] = rows[0]["source_item_revision_id"]
    else:
        rows[1]["profile"] = rows[0]["profile"]
    with pytest.raises(ValidationError):
        InferenceTransferSnapshotPrepareResult.model_validate(rehash(body, "result_sha256"))


@pytest.mark.parametrize("field", ["index_sha256", "eligible_profile_set_sha256"])
def test_index_closure_cannot_be_fixed_by_only_outer_hash(field: str) -> None:
    body = snapshot_prepare_result().model_dump(mode="json")
    body["header"][field] = sha("0")
    body["header"] = rehash(body["header"], "header_sha256")
    with pytest.raises(ValidationError, match="hash"):
        InferenceTransferSnapshotPrepareResult.model_validate(rehash(body, "result_sha256"))


def test_exact_query_item_must_exist_but_missing_query_report_remains_explicit() -> None:
    prepare = snapshot_prepare(query_item_revision_ids=("itemrev_" + "d" * 32,))
    with pytest.raises(ValidationError, match="outside"):
        snapshot_prepare_result(header=snapshot_header(prepare=prepare))
    records = snapshot_records(missing_seed="a")
    prepared = snapshot_prepare_result(records)
    request = snapshot_read_request(prepared)
    result = snapshot_read_result(records, request=request)
    assert result.baselines == ()
    validate_snapshot_read_result(request, result, index=prepared.index)
    result = hashed(
        InferenceTransferSnapshotReadResult,
        "result_sha256",
        **(result.model_dump(mode="json", exclude={"result_sha256"}) | {"limitations": ()}),
    )
    with pytest.raises(ValueError, match="unavailable requested"):
        validate_snapshot_read_result(request, result, index=prepared.index)


@pytest.mark.parametrize("field", ["read_sha256", "header_sha256"])
def test_read_response_is_bound_to_exact_header_and_chunk_request(field: str) -> None:
    prepared = snapshot_prepare_result()
    request = snapshot_read_request(prepared)
    result = snapshot_read_result(request=request)
    result = hashed(
        InferenceTransferSnapshotReadResult,
        "result_sha256",
        **(result.model_dump(mode="json", exclude={"result_sha256"}) | {field: sha("0")}),
    )
    with pytest.raises(ValueError, match="different header/request"):
        validate_snapshot_read_result(request, result, index=prepared.index)


def test_selected_entry_membership_and_response_exactness_use_maps_not_names() -> None:
    prepared = snapshot_prepare_result()
    request = snapshot_read_request(prepared, selected_index_entries=prepared.index[:1])
    result = snapshot_read_result(request=request)
    with pytest.raises(ValueError, match="exact selected chunk"):
        validate_snapshot_read_result(request, result, index=prepared.index)
    foreign = prepared.index[0].model_copy(update={"source_value_sha256": sha("0")})
    forged = hashed(
        InferenceTransferSnapshotReadRequest,
        "read_sha256",
        header=prepared.header,
        selected_index_entries=(foreign,),
    )
    with pytest.raises(ValueError, match="foreign index"):
        validate_snapshot_read_result(forged, result, index=prepared.index)


@pytest.mark.parametrize(
    "field",
    [
        "source_value_sha256",
        "source_item_id",
        "base_analysis_run_id",
        "solution_evidence_pointer_sha256",
    ],
)
def test_record_full_source_and_accepted_report_closure(field: str) -> None:
    body = snapshot_records()[0].model_dump(mode="json")
    value = (
        sha("0")
        if field.endswith("sha256")
        else ("item_" + "0" * 32 if field == "source_item_id" else "analysisrun_" + "0" * 32)
    )
    body["index_entry"][field] = value
    with pytest.raises(ValidationError):
        InferenceTransferSnapshotRecord.model_validate(body)


def test_record_missing_report_cannot_fabricate_a_profile() -> None:
    body = snapshot_records(missing_seed="a")[0].model_dump(mode="json")
    body["staged_entry"] = snapshot_records()[0].staged_entry.model_dump(mode="json")  # type: ignore[union-attr]
    with pytest.raises(ValidationError, match="presence"):
        InferenceTransferSnapshotRecord.model_validate(body)
    response = snapshot_read_result().model_dump(mode="json")
    response["records"][0] = body
    with pytest.raises(SchemaValidationError):
        validate_contract("item-inference-transfer-snapshot", response)


def test_complete_population_hash_cannot_be_proven_by_compact_index_alone() -> None:
    records = snapshot_records()
    header = snapshot_header(records, population_sha256=sha("0"))
    prepared = snapshot_prepare_result(records, header=header)
    with pytest.raises(ValueError, match="full population hash"):
        validate_snapshot_records(header, prepared.index, records)
    with pytest.raises(ValueError, match="complete frozen index"):
        validate_snapshot_records(snapshot_header(records), prepared.index, records[:2])


def test_baseline_query_and_candidates_are_exact_pinned_eligible_members() -> None:
    prepared = snapshot_prepare_result()
    request = snapshot_read_request(prepared)
    result = snapshot_read_result(request=request)
    original = result.baselines[0]
    foreign = original.ordered_candidates[0].model_copy(update={"profile_sha256": sha("0")})
    baseline = hashed(
        SuppliedGraphBaseline,
        "result_sha256",
        query=original.query,
        command_sha256=original.command_sha256,
        ordered_candidates=(foreign,),
    )
    result = hashed(
        InferenceTransferSnapshotReadResult,
        "result_sha256",
        **(result.model_dump(mode="json", exclude={"result_sha256"}) | {"baselines": (baseline,)}),
    )
    with pytest.raises(ValueError, match="outside exact eligible"):
        validate_snapshot_read_result(request, result, index=prepared.index)


def test_empty_and_unmaterialized_official_baselines_need_explicit_limitations() -> None:
    prepared = snapshot_prepare_result()
    request = snapshot_read_request(prepared)
    original = snapshot_read_result(request=request)
    with pytest.raises(ValueError, match="unavailable requested"):
        validate_snapshot_read_result(
            request,
            snapshot_read_result(request=request, baselines=(), limitations=()),
            index=prepared.index,
        )
    empty = hashed(
        SuppliedGraphBaseline,
        "result_sha256",
        query=original.baselines[0].query,
        command_sha256=sha("1"),
        ordered_candidates=(),
    )
    with pytest.raises(ValidationError, match="empty official"):
        snapshot_read_result(request=request, baselines=(empty,), limitations=())


def test_chunk_entry_and_actual_encoded_byte_limits_reject_without_truncation() -> None:
    budget = InferenceTransferSnapshotChunkBudget(max_entries=1, max_encoded_bytes=3 * 1024**2)
    prepared = snapshot_prepare_result(
        header=snapshot_header(prepare=snapshot_prepare(chunk_budget=budget))
    )
    with pytest.raises(ValidationError, match="entry budget"):
        snapshot_read_request(prepared)
    budget = InferenceTransferSnapshotChunkBudget(max_entries=64, max_encoded_bytes=8000)
    prepared = snapshot_prepare_result(
        header=snapshot_header(prepare=snapshot_prepare(chunk_budget=budget))
    )
    request = snapshot_read_request(prepared)
    result = snapshot_read_result(request=request)
    with pytest.raises(ValueError, match="byte budget"):
        validate_snapshot_read_result(request, result, index=prepared.index)


def test_model_copy_cannot_bypass_request_nested_profile_or_response_hash_revalidation() -> None:
    prepared = snapshot_prepare_result()
    request = snapshot_read_request(prepared)
    result = snapshot_read_result(request=request)
    with pytest.raises(ValueError, match="read_sha256"):
        validate_snapshot_read_result(
            request.model_copy(update={"read_sha256": sha("0")}), result, index=prepared.index
        )
    with pytest.raises(ValueError, match="result_sha256"):
        validate_snapshot_read_result(
            request, result.model_copy(update={"result_sha256": sha("0")}), index=prepared.index
        )
    staged = result.records[0].staged_entry
    assert staged is not None
    forged = staged.model_copy(
        update={"profile": staged.profile.model_copy(update={"profile_sha256": sha("0")})}
    )
    records = (result.records[0].model_copy(update={"staged_entry": forged}), *result.records[1:])
    with pytest.raises(ValueError, match="profile_sha256"):
        validate_snapshot_records(prepared.header, prepared.index, records)


@pytest.mark.parametrize(
    "field",
    [
        "authorization_sha256",
        "header_sha256",
        "staged_entry_set_sha256",
        "staged_baseline_set_sha256",
    ],
)
def test_authorization_result_is_not_a_generic_bearer_token(field: str) -> None:
    request, result = authorize_pair()
    changed = hashed(
        InferenceTransferSnapshotAuthorizeResult,
        "result_sha256",
        **(result.model_dump(mode="json", exclude={"result_sha256"}) | {field: sha("0")}),
    )
    with pytest.raises(ValueError, match="exact assembled request"):
        validate_snapshot_authorize_result(request, changed)


def test_entry_and_baseline_set_hashes_bind_full_values_not_only_profile_pointer() -> None:
    records = snapshot_records()
    entries = tuple(row.staged_entry for row in records if row.staged_entry is not None)
    assert snapshot_entry_set_sha256(entries) == snapshot_entry_set_sha256(tuple(reversed(entries)))
    original = entries[0]
    text = "음수가 아니다. 질량은 2 kg이다."
    changed = original.model_copy(
        update={
            "content": CanonicalExperimentItemText(
                text=text,
                original_source=original.profile.source_basis.source.artifact_member,
                text_sha256=content_sha256(text),
            )
        }
    )
    assert snapshot_entry_set_sha256(entries) != snapshot_entry_set_sha256((changed, *entries[1:]))
    baseline = snapshot_read_result().baselines[0]
    changed_baseline = hashed(
        SuppliedGraphBaseline,
        "result_sha256",
        query=baseline.query,
        command_sha256=baseline.command_sha256,
        ordered_candidates=tuple(reversed(baseline.ordered_candidates)),
    )
    assert snapshot_baseline_set_sha256((baseline,)) != snapshot_baseline_set_sha256(
        (changed_baseline,)
    )


def test_empty_population_is_explicit_without_invented_profiles() -> None:
    prepare = snapshot_prepare(query_item_revision_ids=())
    header = snapshot_header((), prepare=prepare)
    prepared = snapshot_prepare_result((), header=header)
    assert (header.source_count, header.profile_count, header.missing_report_count) == (0, 0, 0)
    validate_snapshot_records(header, prepared.index, ())


def test_v3_full_page_chain_and_profile_core_v2_are_both_preserved() -> None:
    record = snapshot_v3_record()
    assert isinstance(record.source, ApprovedPastExamItemKnowledgeSourceV3)
    assert record.staged_entry is not None
    assert record.source != record.staged_entry.profile.source_basis.source
    records = (record, *snapshot_records()[1:])
    prepared = snapshot_prepare_result(records)
    request = snapshot_read_request(prepared)
    result = snapshot_read_result(records, request=request)
    validate_contract("item-inference-transfer-snapshot", result.model_dump(mode="json"))
    validate_snapshot_read_result(request, result, index=prepared.index)
    validate_snapshot_records(prepared.header, prepared.index, records)
    source = result.records[0].source
    assert isinstance(source, ApprovedPastExamItemKnowledgeSourceV3)
    assert source.page_image_count == 1
    assert source.extraction_acceptance_sha256 == sha("f")
    changed = record.model_dump(mode="json")
    changed["source"]["extraction_acceptance_sha256"] = sha("0")
    with pytest.raises(ValidationError, match="full source"):
        InferenceTransferSnapshotRecord.model_validate(changed)


def test_profile_core_cannot_reference_different_original_source_even_with_fresh_hash() -> None:
    record = snapshot_records()[0]
    assert record.staged_entry is not None
    body = record.staged_entry.model_dump(mode="json")
    profile_body = body["profile"]
    profile_body["source_basis"]["source"]["item_id"] = "item_" + "0" * 32
    profile_body = rehash(profile_body, "profile_sha256")
    profile = InferenceTransferProfile.model_validate(profile_body)
    body["profile"] = profile.model_dump(mode="json")
    staged = StagedExperimentEntry.model_validate(body)
    index = record.index_entry.model_copy(
        update={"profile": InferenceTransferProfilePointer.from_profile(profile)}
    )
    with pytest.raises(ValidationError, match="core source"):
        InferenceTransferSnapshotRecord(
            index_entry=index, source=record.source, staged_entry=staged
        )


def test_source_class_and_graph_are_checked_against_pinned_header_context() -> None:
    records = snapshot_records()
    prepared = snapshot_prepare_result(records)
    body = prepared.header.prepare.model_dump(mode="json")
    body["population_scope"] = "ALL_ADMITTED_GRAPH_ITEMS"
    body["source_classes"] = ["APPROVED_ITEM"]
    prepare = InferenceTransferSnapshotPrepareRequest.model_validate(rehash(body, "prepare_sha256"))
    header = snapshot_header(records, prepare=prepare)
    with pytest.raises(ValueError, match="source class"):
        validate_snapshot_records(header, prepared.index, records)
    body = prepared.header.prepare.model_dump(mode="json")
    body["graph_snapshot"]["graph_snapshot_revision_id"] = "graphrev_" + "0" * 32
    prepare = InferenceTransferSnapshotPrepareRequest.model_validate(rehash(body, "prepare_sha256"))
    header = snapshot_header(records, prepare=prepare)
    with pytest.raises(ValueError, match="exact prepared Graph"):
        validate_snapshot_records(header, prepared.index, records)


def test_projection_successor_is_not_silently_reinterpreted_by_method_label() -> None:
    original = snapshot_records()[0]
    assert original.staged_entry is not None
    body = original.staged_entry.model_dump(mode="json")
    body["profile"]["extraction"]["extractor_version"] = "unapproved-projection/99.0"
    body["profile"] = rehash(body["profile"], "profile_sha256")
    staged = StagedExperimentEntry.model_validate(body)
    index = original.index_entry.model_copy(
        update={"profile": InferenceTransferProfilePointer.from_profile(staged.profile)}
    )
    changed = InferenceTransferSnapshotRecord(
        index_entry=index, source=original.source, staged_entry=staged
    )
    records = (changed, *snapshot_records()[1:])
    prepared = snapshot_prepare_result(records)
    with pytest.raises(ValueError, match="exact projection version"):
        validate_snapshot_records(prepared.header, prepared.index, records)


def test_global_actual_utf8_frame_bound_is_not_a_character_count() -> None:
    records = []
    for record in snapshot_records():
        assert record.staged_entry is not None
        text = "🚗" * 262144
        content = CanonicalExperimentItemText(
            text=text,
            original_source=record.source.artifact_member,
            text_sha256=content_sha256(text),
        )
        staged = record.staged_entry.model_copy(update={"content": content})
        records.append(record.model_copy(update={"staged_entry": staged}))
    with pytest.raises(ValidationError, match="byte budget"):
        snapshot_read_result(tuple(records))


def test_contract_module_has_no_infrastructure_or_worker_runtime_dependencies() -> None:
    import eom_catalog_contracts.inference_transfer_snapshot as module

    assert module.__file__ is not None
    tree = ast.parse(Path(module.__file__).read_text())
    imports = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not any(
        name.split(".")[0]
        in {
            "sqlalchemy",
            "subprocess",
            "socket",
            "pathlib",
            "eom_catalog_service",
            "eom_orchestrator",
            "transformers",
            "torch",
            "requests",
        }
        for name in imports
    )
