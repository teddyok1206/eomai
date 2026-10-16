"""Shared checked input only; no operating source, native or model admission."""

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from eom_api.services.command_adapter import _workflow_request_from_api
from eom_api_contracts.workflows import WorkflowStartRequest
from eom_operator_identity import ActorContext, ActorSource, ActorType, PermissionKey
from eom_workflow import compile_definition
from eom_workflow_runner.models import WorkflowDefinitionRecord

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_item_similarity_preparation import preparation_case

ROOT = Path(__file__).resolve().parents[2]


def start_source(tmp_path, monkeypatch, *, ordinary=False):
    source = preparation_case(tmp_path, monkeypatch, ordinary=ordinary)
    compiled = compile_definition(
        ROOT / "config/workflows/generic-item-development.v1.16.yaml",
        {"authoring", "image", "review", "item_management"},
    )
    brief = source.request.item_brief.model_dump(mode="json")
    brief.pop("curriculum_scope")
    brief["curriculum_selected_unit_key"] = "eom.is.middle.1-1"
    retrieval = source.request.educational_retrieval.model_dump(mode="json")
    if ordinary:
        # Public clients select a unit; only the adapter resolves its canonical graph root.
        retrieval["curriculum_root_key"] = None
    request = WorkflowStartRequest.model_validate(
        {
            "definition_key": compiled.definition.definition_key,
            "definition_version": compiled.definition.definition_version,
            "request_name": source.request.request_name,
            "image_mode": source.request.image_mode,
            "pack_key": source.request.content_pack.pack_key,
            "environment": source.request.content_pack.environment,
            "execution_preset_key": source.request.execution_preset_key,
            "item_brief": brief,
            "educational_retrieval": retrieval,
        }
    )
    source.request = _workflow_request_from_api(request)
    body = source.preset.model_dump(mode="json")
    for role in ("image", "item_management"):
        policy = deepcopy(body["role_policies"][0])
        policy.update(role=role, worker_pool_key=role, evidence_access="NONE")
        body["role_policies"].append(policy)
    source.preset = type(source.preset).model_validate(seal(body, "content_sha256"))
    source.resolution = source.resolution.model_copy(
        update={
            "workflow_definition_sha256": compiled.sha256,
            "execution_preset_content_sha256": source.preset.content_sha256,
        }
    )
    actor = ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id=source.caller.operator_id,
        session_id="apisession_" + "8" * 32,
        request_id="request_" + "9" * 32,
        authentication_time=datetime(2026, 10, 14, tzinfo=UTC),
        permissions=frozenset(PermissionKey),
        source=ActorSource.APPLICATION_API,
    )
    runtime = deepcopy(source.value.workflow.runtime_context)
    runtime.pop("execution_plan")
    runtime["content_pack"]["source_tree_sha256"] = (
        source.resolution.content_pack_source_tree_sha256
    )
    definition = WorkflowDefinitionRecord(
        definition_id="wfdef_" + "c" * 32,
        definition_key=compiled.definition.definition_key,
        definition_version=compiled.definition.definition_version,
        definition_hash=compiled.sha256,
        schema_version=compiled.definition.schema_version,
        canonical_definition=compiled.as_dict(),
        source_path=compiled.source_path,
        active=True,
    )
    return SimpleNamespace(
        source=source,
        compiled=compiled,
        request=request,
        actor=actor,
        runtime=runtime,
        definition=definition,
    )
