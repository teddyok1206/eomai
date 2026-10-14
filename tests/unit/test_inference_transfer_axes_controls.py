"""Source-only exact successor controls. No real DB, credentials, model or NAS."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator import inference_transfer_bootstrap as bootstrap
from eom_orchestrator import inference_transfer_control_invocation as invocation
from eom_orchestrator import inference_transfer_resolution as resolution
from eom_orchestrator.control_models import ExecutionPresetRevisionRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.inference_transfer_bootstrap import (
    PreparedInferenceTransferControls,
    ReleasedInferenceTransferControls,
)
from eom_orchestrator.models import ProtocolVersionRecord
from eom_workflow import compile_definition
from eom_workflow.control_plane import ExecutionPresetRevision
from eom_workflow.control_schemas import CONTROL_SCHEMA_RESOURCES, load_control_schema
from eom_workflow.inference_transfer_bootstrap_contract import (
    validate_inference_transfer_bootstrap_manifest,
    validate_inference_transfer_bootstrap_manifest_v11,
    validate_inference_transfer_reviewed_instruction,
)
from eom_workflow.inference_transfer_control import ResolvedExecutionPlanV22
from eom_workflow.inference_transfer_control_invocation import (
    parse_inference_transfer_prepared_receipt,
    parse_inference_transfer_prepared_receipt_v11,
    parse_inference_transfer_release_request,
    parse_inference_transfer_release_result_v11,
    validate_inference_transfer_release_result_context_v11,
)
from eom_workflow_runner.models import WorkflowDefinitionRecord
from eomctl import inference_transfer_controls as cli
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError
from typer.testing import CliRunner

from tests.unit.inference_transfer_axes_control_fixtures import (
    bootstrap_manifest_v11,
    prepared_receipt_v11,
    rehash,
    release_request_v11,
    release_result_v11,
    workflow_request_v11,
)
from tests.unit.inference_transfer_bootstrap_fixtures import (
    PLATFORM_BYTES,
    RUBRIC_BYTES,
    bootstrap_manifest,
)
from tests.unit.test_inference_transfer_bootstrap import fixture as bootstrap_fixture
from tests.unit.test_inference_transfer_control_owner_invocation import _ACTOR, _owner
from tests.unit.test_inference_transfer_resolution import fixture as resolution_fixture


@pytest.mark.parametrize(
    "family",
    ["inference-transfer-control-bootstrap-v1.1", "inference-transfer-control-invocation-v1.1"],
)
def test_additive_schema_exact_registered_mirror(family: str) -> None:
    entry = CONTROL_SCHEMA_RESOURCES[family]
    root = Path(__file__).resolve().parents[2]
    payload = (root / entry.canonical_path).read_bytes()
    assert payload == (root / "packages/workflow/eom_workflow" / entry.resource_path).read_bytes()
    assert sha256_bytes(payload) == entry.sha256
    Draft202012Validator.check_schema(load_control_schema(family))


def test_successor_manifest_and_receipt_preserve_exact_raw_hash_and_pins() -> None:
    manifest = bootstrap_manifest_v11()
    assert (
        validate_inference_transfer_bootstrap_manifest_v11(manifest.model_dump(mode="json"))
        == manifest
    )
    validate_inference_transfer_reviewed_instruction(
        manifest, layer="PLATFORM", payload=PLATFORM_BYTES
    )
    validate_inference_transfer_reviewed_instruction(manifest, layer="ROLE", payload=RUBRIC_BYTES)
    receipt = prepared_receipt_v11()
    assert parse_inference_transfer_prepared_receipt_v11(receipt.model_dump(mode="json")) == receipt
    assert receipt.bootstrap_artifact.sha256 == sha256_bytes(
        canonical_json_bytes(manifest.model_dump(mode="json")) + b"\n"
    )
    request = release_request_v11()
    result = release_result_v11(request)
    assert parse_inference_transfer_release_result_v11(result.model_dump(mode="json")) == result
    validate_inference_transfer_release_result_context_v11(request, result)
    assert result.scientific_evaluation == result.human_transfer_evaluation == "NOT_EVALUATED"


@pytest.mark.parametrize(
    "parser,value",
    [
        (validate_inference_transfer_bootstrap_manifest, bootstrap_manifest_v11),
        (validate_inference_transfer_bootstrap_manifest_v11, bootstrap_manifest),
        (parse_inference_transfer_prepared_receipt, prepared_receipt_v11),
        (parse_inference_transfer_release_request, release_request_v11),
    ],
)
def test_old_and_successor_entrypoints_never_implicitly_upgrade(parser: Any, value: Any) -> None:
    with pytest.raises(SchemaValidationError):
        parser(value().model_dump(mode="json"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("workflow_definition_version", "1.0.0"),
        ("workflow_role_schema_version", "workflow-role/1.29.0"),
        ("result_schema", "item-inference-transfer-pair-result@1.0"),
        ("release_approved", True),
        ("content_pack", "fabricated"),
    ],
)
def test_successor_bootstrap_rejects_mixed_versions_and_authority(field: str, value: Any) -> None:
    body = bootstrap_manifest_v11().model_dump(mode="json") | {field: value}
    with pytest.raises((SchemaValidationError, ValidationError)):
        validate_inference_transfer_bootstrap_manifest_v11(rehash(body, "manifest_sha256"))


@pytest.mark.parametrize(
    "mutation", ["OLD_BOOTSTRAP_SCHEMA", "OLD_PRESET_PROTOCOL", "RAW_SHA", "MODEL_SWAP"]
)
def test_successor_receipt_rejects_mixed_exact_inputs(mutation: str) -> None:
    body = prepared_receipt_v11().model_dump(mode="json")
    if mutation == "OLD_BOOTSTRAP_SCHEMA":
        body["bootstrap_artifact"]["schema_ref"] = (
            "eom://schemas/workflow/inference-transfer-control-bootstrap/1.0"
        )
    elif mutation == "OLD_PRESET_PROTOCOL":
        body["draft"]["compatible_workflow_protocols"] = ["workflow-role/1.29.0"]
        body["draft"] = rehash(body["draft"], "content_sha256")
    elif mutation == "RAW_SHA":
        body["bootstrap_artifact"]["sha256"] = body["manifest"]["manifest_sha256"]
    else:
        body["draft"]["role_policies"][0]["model_candidates"][0]["model"] = "other-model"
        body["draft"] = rehash(body["draft"], "content_sha256")
    with pytest.raises((SchemaValidationError, ValidationError)):
        parse_inference_transfer_prepared_receipt_v11(rehash(body, "receipt_sha256"))


def axes_bootstrap_fixture(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    value = bootstrap_fixture(monkeypatch)
    compiled = compile_definition(
        Path("config/workflows/item-inference-transfer-comparison.v1_1.yaml"), {"support"}
    )
    value.session.definition = WorkflowDefinitionRecord(
        definition_key=compiled.definition.definition_key,
        definition_version=compiled.definition.definition_version,
        schema_version=compiled.definition.schema_version,
        active=True,
        canonical_definition=compiled.as_dict(),
        source_path="installed://synthetic-v11",
        definition_hash=compiled.sha256,
    )
    value.manifest = bootstrap_manifest_v11(workflow_definition_sha256=compiled.sha256)
    return value


def prepare_axes(value: SimpleNamespace) -> PreparedInferenceTransferControls:
    return bootstrap.prepare_inference_transfer_controls_v11(
        value.sessions,
        value.publisher,
        manifest=value.manifest,
        platform_payload=PLATFORM_BYTES,
        rubric_payload=RUBRIC_BYTES,
        operator_id=value.operator,
        observed_at=value.manifest.source.reviewed_at + timedelta(minutes=1),
        authorize_control_change=value.authorize,
    )


def test_authorized_axes_prepare_registers_exact_protocol_once_and_replays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = axes_bootstrap_fixture(monkeypatch)
    prepared = prepare_axes(value)
    assert prepared.draft.state == "DRAFT"
    assert value.session.logical.preset_key == bootstrap.AXES_PRESET_KEY
    assert prepared.instruction_bundle.bundle_id != bootstrap._BUNDLE_ID
    assert prepared.bootstrap_artifact.schema_ref.endswith("/1.1")
    assert value.session.protocol_additions[0].version == "workflow-role/1.30.0"
    assert prepare_axes(value) == prepared
    assert len(value.session.protocol_additions) == 1 and value.draft_creations == 1
    released = bootstrap.release_inference_transfer_controls_v11(
        value.sessions,
        value.publisher,
        prepared=prepared,
        operator_id=value.operator,
        released_at=value.manifest.source.reviewed_at + timedelta(minutes=2),
        authorize_control_change=value.authorize,
    )
    assert released.preset.compatible_workflow_protocols == ("workflow-role/1.30.0",)
    assert released.scientific_evaluation == "NOT_EVALUATED"
    assert prepare_axes(value) == prepared
    assert len(value.session.protocol_additions) == 1


@pytest.mark.parametrize("case", ["REVOKED", "HASH_CONFLICT", "OLD_DEFINITION"])
def test_axes_preflight_failure_has_no_publication_or_protocol_mutation(
    monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    value = axes_bootstrap_fixture(monkeypatch)
    if case == "REVOKED":
        value.revoked = True
    elif case == "HASH_CONFLICT":
        value.session.records[(ProtocolVersionRecord, "workflow-role/1.30.0")] = SimpleNamespace(
            schema_sha256="sha256:" + "0" * 64
        )
    else:
        value.session.definition.definition_hash = "sha256:" + "0" * 64
    with pytest.raises(ControlPlaneError):
        prepare_axes(value)
    assert not value.publisher.calls and not value.session.protocol_additions


def test_authenticated_axes_owner_selects_only_explicit_successor_leaves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, reader, session = _owner(monkeypatch)
    receipt = prepared_receipt_v11()
    calls: list[str] = []

    def prepare(*_args: Any, **kwargs: Any) -> PreparedInferenceTransferControls:
        calls.append("PREPARE")
        kwargs["authorize_control_change"](_ACTOR, "PREPARE")
        return PreparedInferenceTransferControls(
            receipt.manifest, receipt.bootstrap_artifact, receipt.instruction_bundle, receipt.draft
        )

    def release(*_args: Any, **kwargs: Any) -> ReleasedInferenceTransferControls:
        calls.append("RELEASE")
        kwargs["authorize_control_change"](_ACTOR, "RELEASE")
        result = release_result_v11()
        return ReleasedInferenceTransferControls(
            result.preset, result.evaluation_id, result.evaluation_artifact, result.executed_cases
        )

    monkeypatch.setattr(invocation, "prepare_inference_transfer_controls_v11", prepare)
    monkeypatch.setattr(invocation, "release_inference_transfer_controls_v11", release)
    monkeypatch.setattr(
        invocation,
        "prepare_inference_transfer_controls",
        lambda *_args, **_kwargs: pytest.fail("legacy leaf"),
    )
    monkeypatch.setattr(
        invocation,
        "release_inference_transfer_controls",
        lambda *_args, **_kwargs: pytest.fail("legacy leaf"),
    )
    assert (
        owner.prepare_v11(
            receipt.manifest, platform_payload=PLATFORM_BYTES, rubric_payload=RUBRIC_BYTES
        )
        == receipt
    )
    assert owner.release_v11(release_request_v11(receipt)) == release_result_v11()
    assert calls == ["PREPARE", "RELEASE"] and reader.calls == 4 and session.calls == 2


def axes_resolution_fixture(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    value = resolution_fixture(monkeypatch)
    request = workflow_request_v11()
    body = value.preset.model_dump(mode="json")
    body["compatible_workflow_protocols"] = ["workflow-role/1.30.0"]
    value.preset = ExecutionPresetRevision.model_validate(rehash(body, "content_sha256"))
    value.preset_row = SimpleNamespace(
        **value.preset.model_dump(), canonical_document=value.preset.model_dump(mode="json")
    )
    value.session.records[(ExecutionPresetRevisionRecord, value.preset.preset_revision_id)] = (
        value.preset_row
    )
    value.session.records[(ProtocolVersionRecord, "workflow-role/1.30.0")] = SimpleNamespace(
        version="workflow-role/1.30.0"
    )
    value.logical.preset_key = resolution.AXES_PRESET_KEY
    value.request = request
    value.kwargs.update(
        workflow_request=request,
        workflow_definition_version="1.1.0",
        workflow_role_schema_version="workflow-role/1.30.0",
    )
    return value


def test_axes_resolver_exact_v22_plan_step_replay_and_historical_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = axes_resolution_fixture(monkeypatch)
    plan = resolution.resolve_inference_transfer_execution_plan_v11(value.session, **value.kwargs)
    assert isinstance(plan, ResolvedExecutionPlanV22) and plan.resolver_version == "22.0.0"
    assert plan.workflow_definition_key == "item-inference-transfer-comparison"
    assert len(value.session.added) == 2
    value.logical.current_revision_id = "execpresetrev_" + "9" * 32
    value.session.added.clear()
    assert (
        resolution.resolve_inference_transfer_execution_plan_v11(value.session, **value.kwargs)
        == plan
    )
    assert not value.session.added
    assert (
        resolution.read_inference_transfer_execution_plan_v11(
            value.session,
            plan_id=plan.plan_id,
            workflow_id=plan.workflow_id,
            workflow_definition_sha256=plan.workflow_definition_sha256,
            workflow_request=value.request,
            core_prompt_sha256=plan.core_prompt_sha256,
            prompt_sha256=plan.prompt_sha256,
        )
        == plan
    )
    value.session.step_rows[0].model = "mutated-row"
    with pytest.raises(ControlPlaneError, match="projection"):
        resolution.read_inference_transfer_execution_plan_v11(
            value.session,
            plan_id=plan.plan_id,
            workflow_id=plan.workflow_id,
            workflow_definition_sha256=plan.workflow_definition_sha256,
            workflow_request=value.request,
            core_prompt_sha256=plan.core_prompt_sha256,
            prompt_sha256=plan.prompt_sha256,
        )


@pytest.mark.parametrize(
    "field,bad",
    [
        ("workflow_definition_version", "1.0.0"),
        ("workflow_role_schema_version", "workflow-role/1.29.0"),
        ("core_prompt_sha256", "sha256:" + "9" * 64),
        ("prompt_sha256", "sha256:" + "9" * 64),
    ],
)
def test_axes_resolver_replay_rejects_changed_pins(
    monkeypatch: pytest.MonkeyPatch, field: str, bad: str
) -> None:
    value = axes_resolution_fixture(monkeypatch)
    resolution.resolve_inference_transfer_execution_plan_v11(value.session, **value.kwargs)
    with pytest.raises(ControlPlaneError):
        resolution.resolve_inference_transfer_execution_plan_v11(
            value.session, **(value.kwargs | {field: bad})
        )


def test_axes_cli_prepare_release_are_explicit_and_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = prepared_receipt_v11()
    files = {
        "manifest": canonical_json_bytes(receipt.manifest.model_dump(mode="json")),
        "platform": PLATFORM_BYTES,
        "rubric": RUBRIC_BYTES,
        "receipt": canonical_json_bytes(receipt.model_dump(mode="json")),
    }
    paths = {}
    for name, payload in files.items():
        paths[name] = tmp_path / name
        paths[name].write_bytes(payload)
        paths[name].chmod(0o600)
    events: list[str] = []
    monkeypatch.setattr(
        cli, "require_inference_transfer_control_owner", lambda: events.append("UID")
    )

    def prepare(manifest: Any, **kwargs: Any) -> Any:
        assert manifest == receipt.manifest
        assert kwargs == {"platform_payload": PLATFORM_BYTES, "rubric_payload": RUBRIC_BYTES}
        events.append("PREPARE")
        return receipt

    def release(request: Any) -> Any:
        assert request.receipt == receipt
        events.append("RELEASE")
        return release_result_v11(request)

    def owner(_fd: Any) -> Any:
        return SimpleNamespace(dispose=lambda: events.append("DISPOSE")), SimpleNamespace(
            prepare_v11=prepare, release_v11=release
        )

    monkeypatch.setattr(cli, "_owner", owner)
    runner = CliRunner()
    result = runner.invoke(
        cli.inference_transfer_control_app,
        [
            "prepare-axes",
            "--manifest-file",
            str(paths["manifest"]),
            "--platform-file",
            str(paths["platform"]),
            "--rubric-file",
            str(paths["rubric"]),
            "--access-token-fd",
            "9",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == receipt.model_dump(mode="json")
    assert events == ["UID", "PREPARE", "DISPOSE"]
    events.clear()
    result = runner.invoke(
        cli.inference_transfer_control_app,
        ["release-axes", "--receipt-file", str(paths["receipt"]), "--access-token-fd", "9"],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["scientific_evaluation"] == "NOT_EVALUATED"
    assert events == ["UID", "RELEASE", "DISPOSE"]


def test_v1_bootstrap_cannot_write_successor_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    value = axes_bootstrap_fixture(monkeypatch)
    with pytest.raises(ControlPlaneError) as caught:
        bootstrap.prepare_inference_transfer_controls(
            value.sessions,
            value.publisher,
            manifest=value.manifest,
            platform_payload=PLATFORM_BYTES,
            rubric_payload=RUBRIC_BYTES,
            operator_id=value.operator,
            observed_at=value.manifest.source.reviewed_at,
            authorize_control_change=value.authorize,
        )
    assert caught.value.code == "CONTROL_BOOTSTRAP_INVALID"
    assert not value.authorizations and not value.publisher.calls


def test_successor_release_does_not_repair_missing_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = axes_bootstrap_fixture(monkeypatch)
    prepared = prepare_axes(value)
    del value.session.records[(ProtocolVersionRecord, "workflow-role/1.30.0")]
    prior = len(value.publisher.calls)
    with pytest.raises(ControlPlaneError) as caught:
        bootstrap.release_inference_transfer_controls_v11(
            value.sessions,
            value.publisher,
            prepared=prepared,
            operator_id=value.operator,
            released_at=value.manifest.source.reviewed_at + timedelta(minutes=2),
            authorize_control_change=value.authorize,
        )
    assert caught.value.code == "CONTROL_PROTOCOL_POINTER_MISSING"
    assert len(value.publisher.calls) == prior and len(value.session.protocol_additions) == 1
    assert value.release_calls == 0


def test_successor_resolver_forged_wrapper_has_stable_error_before_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = axes_resolution_fixture(monkeypatch)
    forged = value.request.model_copy(update={"requester_permissions_sha256": "sha256:" + "9" * 64})
    with pytest.raises(ControlPlaneError) as caught:
        resolution.resolve_inference_transfer_execution_plan_v11(
            value.session, **(value.kwargs | {"workflow_request": forged})
        )
    assert caught.value.code == "CONTROL_TRANSFER_CONTEXT_INVALID"
    assert not value.session.statements and not value.session.added


def test_successor_replay_rejects_legacy_preset_key_without_latest_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = axes_resolution_fixture(monkeypatch)
    resolution.resolve_inference_transfer_execution_plan_v11(value.session, **value.kwargs)
    value.logical.preset_key = resolution.PRESET_KEY
    value.session.statements.clear()
    value.session.added.clear()
    with pytest.raises(ControlPlaneError) as caught:
        resolution.resolve_inference_transfer_execution_plan_v11(value.session, **value.kwargs)
    assert caught.value.code == "CONTROL_PRESET_POINTER_INVALID"
    assert not value.session.added


@pytest.mark.parametrize("command", ["prepare-axes", "release-axes"])
def test_successor_cli_rejects_legacy_inputs_before_auth_or_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    from tests.unit.inference_transfer_control_invocation_fixtures import prepared_receipt

    receipt = prepared_receipt()
    value = receipt.manifest if command == "prepare-axes" else receipt
    path = tmp_path / "legacy.json"
    path.write_bytes(canonical_json_bytes(value.model_dump(mode="json")))
    path.chmod(0o600)
    monkeypatch.setattr(cli, "require_inference_transfer_control_owner", lambda: None)
    monkeypatch.setattr(cli, "_owner", lambda *_args: pytest.fail("must not authenticate"))
    args = (
        [
            command,
            "--manifest-file",
            str(path),
            "--platform-file",
            str(path),
            "--rubric-file",
            str(path),
        ]
        if command == "prepare-axes"
        else [command, "--receipt-file", str(path)]
    )
    result = CliRunner().invoke(cli.inference_transfer_control_app, args)
    assert result.exit_code == 1
    assert json.loads(result.output)["status"] == "FAILED"
    assert "Traceback" not in result.output
