"""Closed usage/print shapes and original-vs-registered identity correlation."""

from types import SimpleNamespace

import pytest
from eom_catalog_contracts.content_planning import ContentEditionCompositionV1
from eom_catalog_contracts.content_planning_queries import parse_content_planning_query
from eom_catalog_contracts.content_planning_rpc import (
    ContentPlanningPrintRequest,
    ContentPlanningReply,
    check_content_planning_reply,
    parse_content_planning_reply,
    parse_content_planning_request,
)
from eom_catalog_contracts.content_print_commands import (
    ContentPrintMutationResult,
    RecordContentPrint,
    parse_content_print_command,
)
from eom_catalog_contracts.content_print_record import ContentPrintRecordV1
from eom_catalog_contracts.content_usage import (
    PriorUsagePage,
    ReadContentUsage,
    ReadPriorContentUsage,
)
from eom_catalog_contracts.content_usage_filter import ContentUsageFilter
from eom_catalog_contracts.curated_document_slots import RegisteredSlotTarget
from eom_catalog_contracts.validation import validate_contract
from eom_catalog_service.content_planning_layout import select_print_scope
from eom_catalog_service.content_usage_identity import content_usage_identity_matches
from eom_identifiers import content_sha256
from eom_operator_identity import PermissionKey
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit.content_planning_fixtures import SHA, TIME, composition, identifier, item_target
from tests.unit.test_curated_document_assembly_resolution import _actor


def test_prior_usage_contract_does_not_invent_a_year_or_graph_pin():
    from eom_web_gui.content_planning_contracts import PLANNING_RESULT, PlanningQuery
    from pydantic import TypeAdapter

    request = dict(
        query_kind="PRIOR_USAGE", targets=[item_target()], academic_year="ALL", after=None, limit=10
    )
    query = parse_content_planning_query(request)
    assert isinstance(query, ReadPriorContentUsage)
    assert TypeAdapter(PlanningQuery).validate_python(request).model_dump(mode="json") == request
    result = PriorUsagePage(
        query_sha256=content_sha256(request),
        next_after=None,
        rows=(
            {
                "ledger": "USAGE",
                "usage_record_id": identifier("usagerecord"),
                "deliverable_id": identifier("deliverable"),
                "deliverable_revision_id": identifier("delivrev"),
                "title": "옛" * 256,
                "section": "1회",
                "position": 1,
                "target": {
                    key: item_target()[key]
                    for key in ("item_id", "item_revision_id", "item_manifest_sha256")
                },
                "recorded_at": TIME,
                "publication_revision_id": None,
            },
        ),
    ).model_dump(mode="json")
    validate_contract("content-planning-query-result-v1", result)
    assert PLANNING_RESULT.validate_python(result).model_dump(mode="json") == result
    with pytest.raises((ValidationError, SchemaError)):
        parse_content_planning_query({**request, "academic_year": 2026})


@pytest.mark.parametrize("year", [None, 2026, 3000])
def test_annual_usage_filter_preserves_nullable_year_and_closed_shape(year):
    value = {"state": "UNUSED", "academic_year": year}
    validate_contract("content-usage-filter-v1", value)
    assert ContentUsageFilter.model_validate(value).model_dump(mode="json") == value
    with pytest.raises(ValidationError):
        ContentUsageFilter.model_validate({**value, "implicit_latest": True})


@pytest.mark.parametrize("year", [True, 1899, 3001, "2026"])
def test_annual_usage_filter_rejects_ambiguous_year(year):
    value = {"state": "USED", "academic_year": year}
    with pytest.raises(ValidationError):
        ContentUsageFilter.model_validate(value)
    with pytest.raises(SchemaError):
        validate_contract("content-usage-filter-v1", value)


def print_example():
    edition = ContentEditionCompositionV1.model_validate(composition())
    scope = select_print_scope(edition, (identifier("section"),))
    value = dict(
        schema_version="content-print-record/1.0",
        print_record_id=identifier("print"),
        deliverable_revision_id=edition.deliverable_revision_id,
        composition_sha256=edition.composition_sha256,
        scope=scope.model_dump(mode="json"),
        origin="USER_RECORDED",
        intent="INITIAL",
        predecessor_print_record_id=None,
        printed_on=None,
        recorded_at=TIME,
        recorded_by=identifier("operator"),
        note="",
        output=None,
    )
    record = ContentPrintRecordV1.model_validate({**value, "record_sha256": content_sha256(value)})
    command = RecordContentPrint(
        command_kind="RECORD_PRINT",
        edition_id=edition.edition_id,
        revision_id=edition.deliverable_revision_id,
        composition_sha256=edition.composition_sha256,
        section_ids=(identifier("section"),),
        intent="INITIAL",
        predecessor_print_record_id=None,
        printed_on=None,
        note="",
    )
    return command, ContentPrintMutationResult(
        disposition="RECORDED", replayed=False, record=record
    )


def test_print_rpc_roundtrip_does_not_accept_an_unrelated_edition():
    command, result = print_example()
    request = ContentPlanningPrintRequest(
        actor_id=identifier("operator"),
        session_id=identifier("apisession"),
        request_id="print-test",
        authentication_time=TIME,
        idempotency_key="print-test-key-1234",
        command=command,
    )
    reply = ContentPlanningReply(operation=request.operation, status="OK", result=result)
    assert parse_content_planning_request(request.model_dump(mode="json")) == request
    assert parse_content_planning_reply(reply.model_dump(mode="json")) == reply
    check_content_planning_reply(request, reply)
    with pytest.raises(ValueError, match="edition differs"):
        check_content_planning_reply(
            request.model_copy(
                update={
                    "command": command.model_copy(update={"edition_id": identifier("edition", 2)})
                }
            ),
            reply,
        )


@pytest.mark.parametrize(
    "update",
    [
        {"intent": "REPRINT"},
        {"intent": "CORRECTION"},
        {"intent": "CORRECTION", "predecessor_print_record_id": identifier("print")},
        {"predecessor_print_record_id": identifier("print")},
    ],
)
def test_print_intent_schema_and_model_reject_implicit_or_unexplained_changes(update):
    command, _ = print_example()
    value = {**command.model_dump(mode="json"), **update}
    with pytest.raises(SchemaError):
        validate_contract("content-print-command-v1", value)
    with pytest.raises(ValidationError):
        RecordContentPrint.model_validate(value)
    with pytest.raises((SchemaError, ValidationError)):
        parse_content_print_command(value)


@pytest.mark.parametrize(
    "update",
    [
        {"targets": [{"placement_kind": "EMPTY"}]},
        {"targets": [item_target(), item_target()]},
        {"academic_year": True},
        {"limit": 201},
        {"actor_id": identifier("operator")},
    ],
)
def test_usage_query_is_closed_and_actual_target_only(update):
    value = dict(
        query_kind="USAGE", targets=[item_target()], academic_year="ALL", after=None, limit=200
    )
    value.update(update)
    with pytest.raises((SchemaError, ValidationError)):
        parse_content_planning_query(value)


def test_usage_source_equivalence_is_complete_without_order_dependent_pair_propagation():
    target = RegisteredSlotTarget.model_validate(item_target(2))
    pairs = [
        (identifier("extitem"), identifier("item", 1)),
        (identifier("extitem"), identifier("item", 2)),
    ]
    session = SimpleNamespace(execute=lambda _stmt: SimpleNamespace(all=lambda: pairs))
    matches = content_usage_identity_matches(
        session, (target,), _actor(PermissionKey.CONTENT_INTAKE_READ)
    )
    assert matches == {
        ("SOURCE", identifier("extitem")): {0},
        ("ITEM", identifier("item", 1)): {0},
        ("ITEM", identifier("item", 2)): {0},
    }
    no_source_access = content_usage_identity_matches(
        None, (target,), _actor(PermissionKey.ITEM_READ)
    )
    assert no_source_access == {("ITEM", identifier("item", 2)): {0}}


def test_usage_result_page_hash_is_bound_to_full_query():
    query = ReadContentUsage(
        query_kind="USAGE",
        targets=(RegisteredSlotTarget.model_validate(item_target()),),
        academic_year=2027,
        after=None,
        limit=20,
    )
    assert parse_content_planning_query(query.model_dump(mode="json")) == query
    assert query.model_copy(update={"academic_year": None}).academic_year is None
    assert query.targets[0].item_manifest_sha256 == SHA
