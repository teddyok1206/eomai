"""Actual registration scope guard rejects wrong native pictures before Registry writes."""

from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.material_learning import (
    MaterialArtifactMember,
    MaterialExtractionResult,
    MaterialExtractionWork,
)
from eom_catalog_contracts.material_learning_authorization import (
    MaterialLearningAuthorizationRequest,
)
from eom_catalog_contracts.material_native_files import MaterialNativeItemBinding
from eom_catalog_contracts.material_native_visual_preparation import (
    MaterialNativeVisualPreparedArtifact,
)
from eom_catalog_contracts.material_native_visual_work import (
    material_visual_work_instructions,
    material_visual_work_sources,
)
from eom_catalog_service import material_item_registration as owner
from eom_catalog_service.material_learning_models import (
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)
from eom_catalog_service.material_task_results import ResolvedMaterialTask
from eom_identifiers import canonical_json_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.models import MaterialLearningRoleResult

from tests.unit.test_creative_learning_protocol_v2 import role_result
from tests.unit.test_material_learning_contracts import extraction_result, rehash
from tests.unit.test_material_learning_intake import ACTOR
from tests.unit.test_material_native_files import binding_data, native_work, pointer
from tests.unit.test_material_native_visual_preparation import visual_prepared
from tests.unit.test_material_native_visual_selection import (
    FIGURE,
    LOGO,
    SOURCE,
    _catalog,
    _file,
    _scope,
    _selection,
    _sha,
)


def registration_case(monkeypatch, *, missing=None, adapter=True, prepared_version=3):
    catalog = _catalog(SOURCE, (FIGURE, LOGO))
    scope = _scope(catalog)
    prepared_body = visual_prepared()
    prepared_body["catalog_supplements"][0]["catalog"]["sha256"] = _sha(catalog)
    prepared_body["question_visual_scopes"] = [scope.model_dump(mode="json")]
    prepared = MaterialNativeVisualPreparedArtifact.model_validate(
        rehash(prepared_body, "prepared_sha256")
    )
    native_body = binding_data()
    native_body.update(item_number=9, printed_label="9", question=_file().model_dump(mode="json"))
    native = MaterialNativeItemBinding.model_validate(rehash(native_body, "binding_sha256"))
    work_body = native_work()
    work_body["sources"] = [
        source.model_dump(mode="json") for source in material_visual_work_sources(prepared)
    ]
    work_body["question"]["printed_label"] = "9"
    work_body["additional_instructions"] = material_visual_work_instructions(
        source_instructions=work_body["additional_instructions"], scope=scope
    )
    work = MaterialExtractionWork.model_validate(rehash(work_body))
    value = extraction_result()
    value["input_sha256"] = work.input_sha256
    region_id = value["regions"][0]["region_id"]
    offset = len(value["proposal"]["content"]["body"])
    value["proposal"]["content"]["body"].append(
        dict(
            type="source_image",
            block_id="block_figure_0",
            purpose="stimulus",
            source_region_id=region_id,
            target_region_id=region_id,
            alt_text="원문 그림",
        )
    )
    value["proposal"]["content_region_map"].append(
        dict(content_path=f"body[{offset}]", region_ids=[region_id])
    )
    selection = _selection(scope, scope.allowed_picture_use_ids).model_dump(mode="json")
    selection["bindings"][0]["source_region_id"] = region_id
    value["office_bindings"] = selection
    observed = MaterialExtractionResult.model_validate(value)
    raw_role = role_result()
    raw_role.update(
        protocol_version="workflow-role/1.37.0",
        output={"learning_result": observed.model_dump(mode="json")},
    )
    role = MaterialLearningRoleResult.model_validate(raw_role)
    work_pointer = MaterialArtifactMember.model_validate(
        pointer(
            "material/work.json",
            "application/json",
            "eom://schemas/material-learning/extraction-work/1.0",
        )
    )
    result_member = MaterialArtifactMember.model_validate(
        pointer(
            "result.json", "application/json", "eom://schemas/material-learning/role-result/1.0"
        )
    )
    result_pointer = ArtifactMemberPointer.model_validate(
        result_member.model_dump(exclude={"bytes"})
    )
    resolved = ResolvedMaterialTask(
        task_id=work.task_id,
        unit_key=work.unit_key,
        operator_id=ACTOR,
        selection=MaterialLearningAuthorizationRequest(
            workflow_id=role.workflow_id,
            step_run_id=role.step_run_id,
            plan_id="execplan_" + "1" * 32,
            plan_sha256="sha256:" + "1" * 64,
            input_sha256=work.input_sha256,
        ),
        work=work,
        work_pointer=work_pointer,
        role=role,
        result_pointer=result_pointer,
        result_bytes=len(canonical_json_bytes(role.model_dump(mode="json"))),
    )
    run = SimpleNamespace(run_id="materialrun_" + "8" * 32)
    task = SimpleNamespace(run_id=run.run_id)
    reads = []

    class Session:
        def get(self, model, identity):
            reads.append((model, identity))
            if model is MaterialLearningTaskRecord:
                return None if missing == "task" else task
            if model is MaterialLearningRunRecord:
                return None if missing == "run" else run
            raise AssertionError("scope guard performed an unexpected read")

    session = Session()
    sessions = Mock(side_effect=lambda: nullcontext(session))
    sessions.begin.side_effect = AssertionError("Registry transaction must not begin")
    service = object.__new__(owner.MaterialItemRegistrationService)
    service.sessions = sessions
    service.artifacts = Mock()
    service.registry = Mock()
    service._read = Mock(return_value=canonical_json_bytes(catalog.model_dump(mode="json")))
    service.native_visuals = (
        SimpleNamespace(
            profile=prepared.visual_profile,
            question_scope=Mock(return_value=scope),
        )
        if adapter
        else None
    )

    def read_prepared(actual_session, artifacts, actual_run, *, authorize):
        assert actual_session is session and artifacts is service.artifacts and actual_run is run
        authorize()
        authorize()
        return prepared if prepared_version == 3 else None

    read_prepared_port = Mock(side_effect=read_prepared)
    monkeypatch.setattr(owner, "read_native_visual_prepared_for_run", read_prepared_port)
    authorize = Mock()
    return SimpleNamespace(**locals())


def changed_observation(resolved, *, ids=None, catalog_sha=None, no_bindings=False):
    role_body = resolved.role.model_dump(mode="json")
    result = role_body["output"]["learning_result"]
    if no_bindings:
        result["office_bindings"] = None
    else:
        if ids is not None:
            prototype = result["office_bindings"]["bindings"][0]
            result["office_bindings"]["bindings"] = [
                {**prototype, "block_id": f"block_figure_{index}", "picture_use_id": identifier}
                for index, identifier in enumerate(ids)
            ]
            if not ids:
                last = len(result["proposal"]["content"]["body"]) - 1
                result["proposal"]["content"]["body"].pop()
                result["proposal"]["content_region_map"] = [
                    mapping
                    for mapping in result["proposal"]["content_region_map"]
                    if mapping["content_path"] != f"body[{last}]"
                ]
        if catalog_sha is not None:
            result["office_bindings"]["office_catalog_sha256"] = catalog_sha
    return replace(resolved, role=MaterialLearningRoleResult.model_validate(role_body))


@pytest.mark.parametrize("missing", ["task", "run"])
@pytest.mark.parametrize("adapter", [False, True])
def test_missing_actual_task_or_run_never_becomes_a_legacy_fallback(monkeypatch, missing, adapter):
    case = registration_case(monkeypatch, missing=missing, adapter=adapter)
    with pytest.raises(ValueError, match="VISUAL_SOURCE_MISMATCH"):
        case.service._verify_native_visual_scope(
            case.resolved, case.native, authorize=case.authorize
        )
    case.read_prepared_port.assert_not_called()
    case.service._read.assert_not_called()
    case.service.registry.register.assert_not_called()


@pytest.mark.parametrize("adapter", [False, True])
def test_real_legacy_run_is_not_retrospectively_reinterpreted(monkeypatch, adapter):
    case = registration_case(monkeypatch, prepared_version=2, adapter=adapter)
    case.service._verify_native_visual_scope(case.resolved, case.native, authorize=case.authorize)
    assert len(case.reads) == 2 and case.authorize.call_count == 2
    case.service._read.assert_not_called()
    if case.service.native_visuals is not None:
        case.service.native_visuals.question_scope.assert_not_called()


@pytest.mark.parametrize("case_name", ["no_adapter", "profile_changed"])
def test_native3_requires_the_actual_visual_preparation_adapter_profile(monkeypatch, case_name):
    case = registration_case(monkeypatch, adapter=case_name != "no_adapter")
    if case_name == "profile_changed":
        case.service.native_visuals.profile = case.prepared.visual_profile.model_copy(
            update={"source_commit": "f" * 40}
        )
    with pytest.raises(ValueError, match="PREPARATION_PROFILE_STALE"):
        case.service._verify_native_visual_scope(
            case.resolved, case.native, authorize=case.authorize
        )
    case.service._read.assert_not_called()
    case.service.registry.register.assert_not_called()


@pytest.mark.parametrize(
    "field",
    ["allowed_picture_use_ids", "question_document", "split_evidence", "source_catalog_sha256"],
)
def test_native_recomputed_scope_must_equal_stored_scope_before_registry_commit(monkeypatch, field):
    case = registration_case(monkeypatch)
    actual = case.scope.model_dump(mode="json")
    if field == "allowed_picture_use_ids":
        actual[field] = []
    elif field == "source_catalog_sha256":
        actual[field] = "sha256:" + "0" * 64
    else:
        actual[field]["sha256"] = "sha256:" + "0" * 64
    case.service.native_visuals.question_scope.return_value = type(case.scope).model_validate(
        actual
    )
    case.service._native_binding = Mock(return_value=case.native)
    case.service._authorize = Mock()
    monkeypatch.setattr(
        owner, "resolve_completed_material_task", lambda *args, **kwargs: case.resolved
    )
    monkeypatch.setattr(owner, "verify_material_native_item_files", lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="QUESTION_SCOPE_MISMATCH"):
        case.service.register_completed(task_id=case.resolved.task_id, operator_id=ACTOR)
    case.sessions.begin.assert_not_called()
    case.service.registry.register.assert_not_called()


@pytest.mark.parametrize("case_name", ["header", "unknown_use", "wrong_catalog"])
def test_native_body_binding_cannot_select_global_header_or_another_use(monkeypatch, case_name):
    case = registration_case(monkeypatch)
    if case_name == "header":
        resolved = changed_observation(case.resolved, ids=(case.catalog.picture_uses[1].use_id,))
    elif case_name == "unknown_use":
        resolved = changed_observation(case.resolved, ids=("officeobj_" + "0" * 32,))
    else:
        resolved = changed_observation(case.resolved, catalog_sha="sha256:" + "0" * 64)
    with pytest.raises(ValueError, match=r"SELECTION_OUT_OF_SCOPE|SELECTION_CATALOG_MISMATCH"):
        case.service._verify_native_visual_scope(resolved, case.native, authorize=case.authorize)
    case.service.registry.register.assert_not_called()


@pytest.mark.parametrize("empty", [False, True])
def test_correct_allowed_subset_passes_and_adapter_receives_exact_native_pins(monkeypatch, empty):
    case = registration_case(monkeypatch)
    resolved = changed_observation(case.resolved, ids=()) if empty else case.resolved
    case.service._verify_native_visual_scope(resolved, case.native, authorize=case.authorize)
    call = case.service.native_visuals.question_scope.call_args
    assert call.args == (case.native.question,)
    assert call.kwargs == dict(
        item_number=9,
        catalog=case.catalog,
        catalog_pointer=case.resolved.work.sources[0].office_catalog,
        authorize=case.authorize,
    )
    case.service.registry.register.assert_not_called()


@pytest.mark.parametrize("where", ["prepared_read", "native_file_recheck"])
def test_current_actor_revocation_propagates_without_being_swallowed(monkeypatch, where):
    case = registration_case(monkeypatch)
    checks = []

    def actual_actor_authorize():
        checks.append(case.resolved.operator_id)
        if where == "prepared_read" or len(checks) > 2:
            raise ValueError("ACTUAL_OPERATOR_PERMISSION_REVOKED")

    if where == "native_file_recheck":

        def recheck(*args, **kwargs):
            kwargs["authorize"]()
            return case.scope

        case.service.native_visuals.question_scope.side_effect = recheck
    with pytest.raises(ValueError, match="PERMISSION_REVOKED"):
        case.service._verify_native_visual_scope(
            case.resolved, case.native, authorize=actual_actor_authorize
        )
    assert checks and all(actor == ACTOR for actor in checks)
    case.service.registry.register.assert_not_called()
