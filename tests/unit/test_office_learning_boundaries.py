"""The native successor stays within the existing source, execution and publication owners."""

import io
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.creative_learning_cohort import (
    OFFICE_CREATIVE_COHORT_SCHEMA_REF,
    OfficeCreativeLearningCohort,
)
from eom_catalog_contracts.creative_learning_continuation import CreativeOfficeExecutionScope
from eom_catalog_service import office_item_learning_input as input_owner
from eom_catalog_service.creative_learning_cohort import read_creative_execution_scope
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator import creative_source_controls as control_owner
from eom_orchestrator.control_models import ExecutionPresetRecord
from eom_orchestrator.control_service import ControlPlaneError

from tests.unit.test_creative_learning_cohort import cohort_value
from tests.unit.test_creative_source_controls import fixture as controls_fixture
from tests.unit.test_office_item_learning import office_case


def office_cohort():
    body = {
        "schema_version": "creative-learning-cohort/2.0",
        "cohort": cohort_value(),
        "workflow_definition_version": "3.0.0",
        "extraction_preset_key": "creative-office-learning",
    }
    return OfficeCreativeLearningCohort.model_validate(
        {**body, "manifest_sha256": content_sha256(body)}
    )


def test_office_cohort_is_explicit_and_reader_never_reinterprets_old_cohort():
    office = office_cohort()
    data = canonical_json_bytes(office.model_dump(mode="json"))
    published = NS(
        primary_file="office-cohort.json",
        primary_sha256=sha256_bytes(data),
        artifact_id="artifact_" + "1" * 32,
        artifact_revision_id="rev_" + "2" * 32,
    )
    publisher = Mock()
    publisher.read_published_revision.return_value = published
    artifacts = Mock()
    artifacts.read_member.return_value = data
    scope, actual = read_creative_execution_scope(
        artifacts, publisher, published.artifact_revision_id
    )
    assert isinstance(scope, CreativeOfficeExecutionScope)
    assert scope.cohort == office.cohort and actual == published
    assert scope.workflow_definition_version == "3.0.0"
    assert scope.extraction_preset_key == "creative-office-learning"
    assert scope.history_scopes == (scope,) and scope.continuation is None
    artifacts.read_member.assert_called_once()
    assert artifacts.read_member.call_args.kwargs["schema_ref"] == OFFICE_CREATIVE_COHORT_SCHEMA_REF
    root = Path(__file__).resolve().parents[2]
    name = "external-item/creative-learning-cohort-v2.schema.json"
    assert (root / "schemas" / name).read_bytes() == (
        root / "packages/catalog_contracts/eom_catalog_contracts/resources" / name
    ).read_bytes()
    with pytest.raises(ValueError, match="SCOPE_MISMATCH"):
        CreativeOfficeExecutionScope(
            office.cohort.model_copy(update={"source_commit": "0" * 40}), office=office
        )


def test_native_registration_pack_preserves_metadata_and_supports_new_workflow():
    from eom_catalog_service.content_pack_files import compile_pack

    root = Path(__file__).resolve().parents[2] / "content/packs/external-creative-item"
    pack = compile_pack(root / "1.2.0")
    assert pack.manifest.compatibility.workflow_definitions[0].versions == (
        "1.0.0",
        "2.0.0",
        "3.0.0",
    )
    for name in (
        "metadata-schemas/item-metadata.schema.json",
        "item-types/external-creative-multiple-choice.yaml",
    ):
        assert (root / "1.2.0" / name).read_bytes() == (root / "1.1.0" / name).read_bytes()


def test_native_workflow_admission_retains_the_real_source_owner_and_office_pointer():
    from eom_workflow.compiler import compile_definition
    from eom_workflow.models import WorkflowRequest
    from eom_workflow_runner.models import WorkflowDefinitionRecord
    from eom_workflow_runner.repository import (
        create_workflow_instance,
        load_persisted_workflow_request,
    )

    from tests.unit.test_external_item_learning_workflow_admission import OPERATOR, _owner, _session

    work, *_ = office_case()
    compiled = compile_definition(
        Path(__file__).resolve().parents[2] / "config/workflows/external-item-learning.v3.yaml",
        {"support"},
    )
    definition = WorkflowDefinitionRecord(
        definition_id="wfdef_" + "c" * 32,
        definition_key="external-item-learning",
        definition_version="3.0.0",
        schema_version="1.0",
        canonical_definition=compiled.as_dict(),
        definition_hash=compiled.sha256,
        source_path=compiled.source_path,
        active=True,
    )
    request = WorkflowRequest(
        request_name="EXTERNAL_ITEM_LEARNING_REQUEST",
        image_mode="skip",
        execution_preset_key="creative-office-learning",
        external_item_learning_work=work,
    )
    owner = _owner(request)
    workflow, created = create_workflow_instance(
        _session(),
        definition=definition,
        request=request,
        actor_type="human",
        actor_id=OPERATOR,
        idempotency_key="synthetic-native-admission",
        external_item_learning_authorizer=owner,
    )
    assert created and workflow.role_schema_version == "workflow-role/1.36.0"
    assert load_persisted_workflow_request(workflow.initial_request) == request
    assert owner.reauthorize.call_count == 2
    assert workflow.created_actor_id == OPERATOR


def test_completed_native_proposal_resolves_exact_workflow_plan_and_role_family(monkeypatch):
    from eom_catalog_service.creative_learning_proposal import (
        resolve_completed_creative_learning_proposal,
    )
    from eom_workflow.control_plane import parse_creative_learning_execution_plan
    from eom_workflow.models import WorkflowRequest

    from tests.unit.test_creative_proposal_resolution_v2 import _case

    case = _case(monkeypatch)
    work, result, _catalog, bindings = office_case()
    raw = case.row.canonical_document
    raw.update(
        schema_version="resolved-execution-plan/32.0",
        workflow_definition_version="3.0.0",
        resolver_version="32.0.0",
        work_input=work.model_dump(mode="json"),
    )
    raw["plan_sha256"] = content_sha256({k: v for k, v in raw.items() if k != "plan_sha256"})
    from eom_workflow.control_schemas import validate_control_contract

    validate_control_contract("resolved-execution-plan-v32", raw)
    plan = parse_creative_learning_execution_plan(raw)
    case.row.plan_sha256, case.row.resolver_version = plan.plan_sha256, plan.resolver_version
    case.selection = case.selection.model_copy(
        update={
            "plan_sha256": plan.plan_sha256,
            "work_input_sha256": work.request_sha256,
        }
    )
    request = WorkflowRequest(
        request_name="EXTERNAL_ITEM_LEARNING_REQUEST",
        image_mode="skip",
        execution_preset_key="creative-office-learning",
        external_item_learning_work=work,
    ).model_dump(mode="json")
    case.workflow.definition_version, case.workflow.role_schema_version = (
        "3.0.0",
        "workflow-role/1.36.0",
    )
    case.workflow.initial_request, case.workflow.request_payload = request, request
    case.workflow.runtime_context["execution_plan"]["plan_sha256"] = plan.plan_sha256
    case.role["protocol_version"] = "workflow-role/1.36.0"
    case.role["output"] = {
        "learning_result": result.model_dump(mode="json"),
        "office_visuals": bindings.model_dump(mode="json"),
    }
    case.step.result_schema = "external-item-learning-result@3.0"
    case.artifact.manifest["files"][0]["schema_ref"] = case.step.result_schema
    resolved = resolve_completed_creative_learning_proposal(
        case.session, case.artifacts, case.selection
    )
    assert resolved.work == work
    assert resolved.role.output.learning_result == result
    assert resolved.role.output.office_visuals == bindings
    assert resolved.pointer.schema_ref == case.step.result_schema


def native_controls(monkeypatch):
    case = controls_fixture(monkeypatch)
    baseline = case.released
    case.baseline = baseline
    case.released = baseline.model_copy(
        update={"compatible_workflow_protocols": ("workflow-role/1.36.0",)}
    )
    case.logical.preset_key = "creative-source-learning-parallel"
    case.session.get.side_effect = lambda model, key: (
        case.logical
        if model is ExecutionPresetRecord
        else case.baseline
        if key == case.baseline.preset_revision_id
        else case.released
    )
    case.session.scalar.return_value = None
    case.sessions.begin.side_effect = lambda: nullcontext(case.session)
    case.args.update(
        baseline_revision_id=baseline.preset_revision_id,
        reviewed_at=datetime(2026, 11, 3, tzinfo=UTC),
    )
    return case


def test_office_controls_keep_capacity_models_and_isolation_exactly(monkeypatch):
    case = native_controls(monkeypatch)
    create = Mock(return_value=case.released.model_copy(update={"state": "DRAFT"}))
    release = Mock(return_value=case.released)
    monkeypatch.setattr(control_owner, "create_execution_preset_draft", create)
    monkeypatch.setattr(control_owner, "record_execution_preset_evaluation", Mock())
    monkeypatch.setattr(control_owner, "release_execution_preset", release)
    case.publisher.publish_bytes.return_value = NS(pointer=object())
    result = control_owner.release_creative_office_controls(
        case.sessions, case.publisher, **case.args
    )
    assert result == case.released
    assert create.call_args.kwargs["preset_key"] == "creative-office-learning"
    assert create.call_args.kwargs["compatible_workflow_protocols"] == ["workflow-role/1.36.0"]
    assert (
        create.call_args.kwargs["capacity_policy_revision_id"]
        == case.baseline.capacity_policy_revision_id
    )
    assert create.call_args.kwargs["role_policies"] == [
        case.baseline.role_policies[0]
        .model_copy(update={"instruction_bundle": case.instruction})
        .model_dump(mode="json")
    ]
    assert case.bundle.call_args.kwargs["bundle_key"] == "creative-office-learning-instructions"
    assert case.bundle.call_args.kwargs["reviewed_at"] == case.args["reviewed_at"]


@pytest.mark.parametrize("change", ["network", "sandbox", "protocol", "purpose"])
def test_invalid_native_baseline_never_publishes_instruction_or_changes_capacity(
    monkeypatch, change
):
    case = native_controls(monkeypatch)
    if change in {"network", "sandbox"}:
        policy = case.baseline.role_policies[0].model_copy(update={change: "invalid"})
        case.baseline = case.baseline.model_copy(update={"role_policies": (policy,)})
    elif change == "protocol":
        case.baseline = case.baseline.model_copy(
            update={"compatible_workflow_protocols": ("workflow-role/1.33.0",)}
        )
    else:
        case.logical.preset_key = "unrelated"
    with pytest.raises(ControlPlaneError, match="source-analysis baseline differs"):
        control_owner.release_creative_office_controls(case.sessions, case.publisher, **case.args)
    case.bundle.assert_not_called()


@pytest.mark.parametrize("fault", [None, "hash", "revision", "media", "source-revoked"])
def test_native_intake_closes_original_stream_and_reauthorizes_before_publish(
    monkeypatch, tmp_path, fault
):
    work, _result, _catalog, _bindings = office_case()
    source = work.source
    expected = source.preview_manifest
    payload = b"synthetic Office file, never parsed in unit tests"
    # Keep every original identity fixed; hash/size are explicit fixture values.
    source = source.model_copy(
        update={
            "preview_manifest": expected.model_copy(
                update={
                    "source_sha256": sha256_bytes(payload),
                    "source_bytes": len(payload),
                }
            )
        }
    )
    expected = source.preview_manifest
    stream = io.BytesIO(payload + (b"changed" if fault == "hash" else b""))
    document = NS(
        source_file_id=expected.source_file_id,
        artifact_id=expected.source_artifact_id,
        artifact_revision_id=expected.source_artifact_revision_id,
        member_path=expected.source_member_path,
        media_type=expected.source_media_type,
        member=NS(stream=stream, sha256=expected.source_sha256, content_length=len(payload)),
    )
    if fault == "revision":
        document.artifact_revision_id = "rev_" + "0" * 32
    elif fault == "media":
        document.media_type = "image/png"
    reader = Mock()
    reader.open.return_value = document
    monkeypatch.setattr(input_owner, "ExternalItemDocumentMediaService", Mock(return_value=reader))
    extract, publish, authorize = Mock(), Mock(return_value=work.office_artifact), Mock()
    if fault == "source-revoked":
        authorize.side_effect = [None, ValueError("SOURCE_REVOKED")]
    monkeypatch.setattr(input_owner, "extract_office_picture_use_input", extract)
    monkeypatch.setattr(input_owner, "publish_office_picture_catalog", publish)
    arguments = dict(
        source=source,
        publisher=Mock(),
        source_commit="a" * 40,
        settings=NS(office_image_tool_root=Path("/opt/eom/test-only"), staging_root=tmp_path),
        authorize_source=authorize,
    )
    if fault:
        with pytest.raises(ValueError):
            input_owner.prepare_office_item_learning_input(Mock(), **arguments)
        extract.assert_not_called()
        publish.assert_not_called()
    else:
        assert (
            input_owner.prepare_office_item_learning_input(Mock(), **arguments)
            == work.office_artifact
        )
        assert extract.call_args.args[0] == payload
        assert authorize.call_count == 2
    assert stream.closed
