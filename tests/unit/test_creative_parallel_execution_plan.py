"""Separate capacity/preset identities do not require another source task schema."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from eom_catalog_contracts import ExternalItemLearningWorkInput
from eom_identifiers import content_sha256
from eom_orchestrator.control_service import ControlPlaneError
from eom_workflow import ResolvedExecutionPlanV28, parse_creative_learning_execution_plan
from eom_workflow.control_plane import ExecutionPresetRevision
from eom_workflow.creative_learning_profile import creative_learning_profile_for_preset

from tests.unit.test_external_item_learning_execution import _execute, _fixture
from tests.unit.test_external_item_learning_execution_resolver import (
    _published_preset,
    _resolve,
    _Session,
)
from tests.unit.test_external_item_learning_work_contract import _work


def test_existing_resolver_pins_parallel_model_instructions_and_exact_preset():
    logical, row = _published_preset(successor=True)
    value = deepcopy(row.canonical_document)
    value["preset_id"] = "execpreset_" + "d" * 32
    value["preset_revision_id"] = "execpresetrev_" + "e" * 32
    value["capacity_policy_revision_id"] = "capacityrev_" + "f" * 32
    value["content_sha256"] = content_sha256(
        {k: v for k, v in value.items() if k != "content_sha256"}
    )
    row.canonical_document = value
    row.content_sha256 = value["content_sha256"]
    row.preset_id = value["preset_id"]
    logical.preset_id = value["preset_id"]
    logical.current_revision_id = value["preset_revision_id"]
    logical.preset_key = "creative-source-learning-parallel"
    preset = ExecutionPresetRevision.model_validate(value)
    session = _Session(logical, row)
    actual = _resolve(
        session,
        ExternalItemLearningWorkInput.model_validate(_work()),
        protocol="workflow-role/1.34.0",
        execution_preset_key=logical.preset_key,
        expected_preset=preset,
    )
    assert isinstance(actual, ResolvedExecutionPlanV28)
    assert actual.steps[0].worker_pool_key == "support"
    assert actual.preset_id == preset.preset_id
    assert actual.capacity_policy_revision_id == value["capacity_policy_revision_id"]
    assert actual.steps[0].instruction_bundle == preset.role_policies[0].instruction_bundle
    assert actual.steps[0].model == preset.role_policies[0].model_candidates[0].model

    replay = SimpleNamespace(scalar=lambda _statement: session.added[0])
    assert (
        _resolve(
            replay,
            actual.work_input,
            protocol="workflow-role/1.34.0",
            execution_preset_key=logical.preset_key,
            expected_preset=preset,
        )
        == actual
    )
    with pytest.raises(ControlPlaneError, match="exact purpose pin"):
        _resolve(
            _Session(logical, row),
            actual.work_input,
            protocol="workflow-role/1.34.0",
            execution_preset_key=logical.preset_key,
        )


@pytest.mark.parametrize(
    "version,key",
    [
        ("1.0.0", "creative-source-learning-parallel"),
        ("2.0.0", "arbitrary"),
        ("3.0.0", "creative-source-learning-parallel"),
    ],
)
def test_closed_preset_mapping_rejects_unrelated_family(version, key):
    with pytest.raises(ValueError):
        creative_learning_profile_for_preset(version, key)


def test_source_execution_uses_original_role_result_and_claims_the_exact_plan(
    monkeypatch, tmp_path
):
    # Actual orchestration and result validation, with synthetic capacity/worker/commit ports.
    # No real worker or live three-slot acceptance is claimed by this test.
    value = _fixture(monkeypatch, tmp_path, successor=True)
    value.orchestrator.capacity.claim.return_value.slot_key = "slot04"
    monkeypatch.setattr(
        value.orchestrator,
        "_slot_by_key",
        lambda _key: SimpleNamespace(
            slot_id="04",
            role="item_management",
            linux_user="synthetic-worker-04",
        ),
    )
    result = _execute(value, result_schema="external-item-learning-result@2.0")
    assert result.status == "SUCCEEDED"
    assert value.orchestrator.capacity.claim.call_args.args[0].plan_id == value.plan.plan_id
    assert (
        value.worker.prepare_structured_workspace.call_args.kwargs["input_document"]["role"]
        == "support"
    )
    value.worker.run_prepared.assert_called_once()
    value.commit.assert_called_once()


def test_unneeded_new_plan_family_was_not_admitted():
    from tests.unit.test_external_item_learning_execution_plan import _plan

    value = _plan(successor=True)
    value.update(schema_version="resolved-execution-plan/29.0", resolver_version="29.0.0")
    value["plan_sha256"] = content_sha256({k: v for k, v in value.items() if k != "plan_sha256"})
    with pytest.raises(ValueError):
        parse_creative_learning_execution_plan(value)
