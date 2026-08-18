from pathlib import Path

from eom_workflow import WorkflowRequest, compile_definition
from eom_workflow_runner.models import WorkflowDefinitionRecord
from eom_workflow_runner.repository import workflow_business_fingerprint

ROLE_SLOTS = {"authoring", "review", "image", "item_management", "support"}


def _definition() -> WorkflowDefinitionRecord:
    compiled = compile_definition(
        Path("config/workflows/generic-item-development.v1.yaml"), ROLE_SLOTS
    )
    return WorkflowDefinitionRecord(
        definition_id="wfdef_0123456789abcdef0123456789abcdef",
        definition_key=compiled.definition.definition_key,
        definition_version=compiled.definition.definition_version,
        schema_version=compiled.definition.schema_version,
        canonical_definition=compiled.as_dict(),
        definition_hash=compiled.sha256,
        active=True,
        source_path=compiled.source_path,
    )


def test_workflow_business_fingerprint_is_deterministic_and_input_sensitive() -> None:
    definition = _definition()
    first_request = WorkflowRequest(request_name="PLACEHOLDER_REQUEST", image_mode="skip")
    same_request = WorkflowRequest(request_name="PLACEHOLDER_REQUEST", image_mode="skip")
    changed_request = WorkflowRequest(request_name="PLACEHOLDER_REQUEST", image_mode="required")

    first = workflow_business_fingerprint(definition, first_request)

    assert first == workflow_business_fingerprint(definition, same_request)
    assert first != workflow_business_fingerprint(definition, changed_request)
    assert first.startswith("sha256:")


def test_active_business_fingerprint_index_is_partial_and_unique() -> None:
    active = next(
        index
        for index in WorkflowDefinitionRecord.metadata.tables["workflow_instances"].indexes
        if index.name == "uq_workflow_active_request_hash"
    )
    assert any(
        index.name == "ix_workflow_instances_request_hash"
        for index in WorkflowDefinitionRecord.metadata.tables["workflow_instances"].indexes
    )
    assert active.unique
    predicate = str(active.dialect_options["postgresql"]["where"])
    for state in (
        "REQUESTED",
        "RUNNING",
        "AWAITING_HUMAN_APPROVAL",
        "REWORK_REQUESTED",
        "APPROVED",
        "REGISTERING",
    ):
        assert state in predicate
    for state in ("COMPLETED", "FAILED", "CANCELLED"):
        assert state not in predicate
