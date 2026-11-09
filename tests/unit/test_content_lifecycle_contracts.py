"""Shelving wire is additive, actor-free and correlated to its exact target."""

import pytest
from eom_catalog_contracts.content_lifecycle import (
    ChangeContentLifecycle,
    ContentLifecycleEntry,
    ContentLifecycleMutation,
    ContentLifecycleTarget,
    ReadContentLifecycle,
    parse_content_lifecycle_action,
    parse_content_lifecycle_result,
)
from eom_catalog_contracts.content_planning_rpc import (
    ContentPlanningLifecycleRequest,
    ContentPlanningReply,
    check_content_planning_reply,
    parse_content_planning_reply,
    parse_content_planning_request,
)
from eom_catalog_contracts.validation import validate_contract
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit.content_planning_fixtures import TIME, identifier


def target():
    return ContentLifecycleTarget(target_kind="CONTENT", target_id=identifier("deliverable"))


def action():
    return ChangeContentLifecycle(
        action_kind="CHANGE_LIFECYCLE",
        target=target(),
        expected_state="ACTIVE",
        expected_version=0,
        desired_state="ARCHIVED",
        reason="올해 편집 종료",
    )


def request(value=None, key="content-lifecycle:fixture"):
    return ContentPlanningLifecycleRequest(
        actor_id=identifier("operator"),
        session_id=identifier("apisession"),
        request_id="lifecycle-test",
        authentication_time=TIME,
        action=value or action(),
        idempotency_key=key,
    )


def mutation():
    return ContentLifecycleMutation(
        entry=ContentLifecycleEntry(
            target=target(),
            deliverable_id=identifier("deliverable"),
            title="예제",
            lifecycle_state="ARCHIVED",
            version=1,
            current_revision_id=None,
            parent_archived=False,
        ),
        replayed=False,
        disposition="CHANGED",
    )


def test_additive_schema_and_models_roundtrip_without_reinterpreting_v1():
    value = request().model_dump(mode="json")
    assert parse_content_planning_request(value).model_dump(mode="json") == value
    assert parse_content_lifecycle_action(value["action"]) == action()
    with pytest.raises(SchemaError):
        validate_contract("catalog-content-planning-request-v1", value)
    reply = ContentPlanningReply(
        operation="CONTENT_PLANNING_LIFECYCLE", status="OK", result=mutation()
    )
    assert parse_content_planning_reply(reply.model_dump(mode="json")) == reply
    assert parse_content_lifecycle_result(mutation().model_dump(mode="json")) == mutation()
    check_content_planning_reply(request(), reply)
    with pytest.raises(SchemaError):
        validate_contract("catalog-content-planning-response-v1", reply.model_dump(mode="json"))


@pytest.mark.parametrize(
    "update",
    [
        {"expected_version": True},
        {"reason": " "},
        {"actor_id": identifier("operator")},
        {"expected_state": "DELETED"},
    ],
)
def test_lifecycle_rejects_implicit_authority_or_malformed_state(update):
    with pytest.raises((ValidationError, SchemaError)):
        parse_content_lifecycle_action({**action().model_dump(mode="json"), **update})


def test_reads_have_no_mutation_key_and_writes_require_one():
    read = ReadContentLifecycle(action_kind="READ_LIFECYCLE", target=target())
    parse_content_planning_request(request(read, None).model_dump(mode="json"))
    with pytest.raises(ValidationError):
        request(read)
    with pytest.raises(ValidationError):
        request(key=None)


@pytest.mark.parametrize(
    "field,value",
    [
        (
            "target",
            ContentLifecycleTarget(target_kind="CONTENT", target_id=identifier("deliverable", 2)),
        ),
        ("lifecycle_state", "ACTIVE"),
    ],
)
def test_reply_cannot_silently_target_other_content_or_another_state(field, value):
    result = mutation()
    altered = result.model_copy(update={"entry": result.entry.model_copy(update={field: value})})
    reply = ContentPlanningReply(
        operation="CONTENT_PLANNING_LIFECYCLE", status="OK", result=altered
    )
    with pytest.raises(ValueError):
        check_content_planning_reply(request(), reply)
