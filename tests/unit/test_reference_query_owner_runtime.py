"""Current-capture factory/pins; installed IAM/unit/account observations are synthetic."""

from unittest.mock import Mock

import pytest
from eom_identity_service import identity_provider_code_members
from eom_identity_service.installed_owner_session_provider import (
    ProtectedInstalledIdentityProviderAdmission,
)
from eom_workflow.reference_query_owner_configuration import ReferenceQueryServiceConfiguration
from eom_workflow_runner import reference_query_owner_runtime as module
from eom_workflow_runner.reference_query_prepare_driver import ReferenceQueryPrepareDriver
from eom_workflow_runner.repository import CommandExecutionFamily

from tests.unit.test_installed_identity_provider_observation import observation as observation
from tests.unit.test_reference_query_owner_admission import source as source
from tests.unit.test_reference_query_owner_configuration import owner_body


def configuration(source, observation):
    body = owner_body(source)
    observed = observation[0]
    body["api_provider"] = {
        "source_commit": observed.pin.source_commit,
        "wheel_sha256": observed.pin.wheel_sha256,
        "configuration_sha256": observed.pin.configuration_sha256,
        "code_members": [
            {"member": member, "sha256": value.sha256}
            for member, value in zip(
                identity_provider_code_members(),
                sorted(observed.code, key=lambda item: str(item.path)),
                strict=True,
            )
        ],
    }
    return ReferenceQueryServiceConfiguration.model_validate(body)


def test_each_request_binds_actual_capture_to_own_owner_and_shared_finite_driver(
    source, observation
):
    selected = configuration(source, observation)
    runtime = module.ReferenceQueryOwnerRuntime(
        source.publisher.engine,
        selected,
        source.publisher,
        source.owner.settings,
        source.owner.configuration,
        source.policy.spaces,
        Mock(),
        ProtectedInstalledIdentityProviderAdmission(observation[0]),
        ReferenceQueryPrepareDriver(),
    )
    capture = source.owner.identity.capture
    first, second = runtime.application(capture), runtime.application(capture)
    assert first.owner is not second.owner
    assert first.owner.identity.capture is capture and second.owner.identity.capture is capture
    assert first.driver is runtime.driver is second.driver
    assert first.runner.command_families == frozenset({CommandExecutionFamily.REFERENCE_QUERY})
    assert first.runner.command_actor_selection.actor_id == capture.operator_id
    assert not first.runner.available_roles and first.runner.executor is None
    assert first.owner.identity.fence.owner.fresh_auth_seconds == 900
    runtime.close()


@pytest.mark.parametrize("fault", ("hash", "member", "provider_restart"))
def test_changed_provider_selection_or_real_observation_fails_before_engine(
    source, observation, monkeypatch, fault
):
    selected = configuration(source, observation)
    body = selected.model_dump(mode="json")
    if fault == "hash":
        body["api_provider"]["code_members"][0]["sha256"] = "sha256:" + "0" * 64
    elif fault == "member":
        body["api_provider"]["code_members"] = body["api_provider"]["code_members"][1:]
    else:
        observation[1]["MainPID"] = "12346"
    selected = ReferenceQueryServiceConfiguration.model_validate(body)
    engine = Mock(side_effect=AssertionError("DB creation before installed provider"))
    monkeypatch.setattr(module, "build_native_embedding_controller_engine", engine)
    with pytest.raises(ValueError):
        module.build_reference_query_owner_runtime(
            selected, ProtectedInstalledIdentityProviderAdmission(observation[0])
        )
    engine.assert_not_called()
