"""Real local Artifact/schema resolution; synthetic Identity/source, no live compute grant."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.embedding_device_benchmark import (
    BENCHMARK_POLICY_SCHEMA_REF,
    BENCHMARK_POLICY_V11_SCHEMA_REF,
    BENCHMARK_POLICY_V12_SCHEMA_REF,
    BenchmarkOwnerRequest,
    embedding_device_benchmark_bytes,
)
from eom_catalog_service import embedding_benchmark_owner_composition as composition_module
from eom_catalog_service.embedding_benchmark_budget600_poststart_inspection import (
    FixedBudget600PoststartInspection,
)
from eom_catalog_service.embedding_benchmark_owner_admission import BenchmarkOwnerConfiguration
from eom_catalog_service.embedding_benchmark_poststart_inspection import (
    FixedBenchmarkPoststartInspection,
)
from eom_orchestrator.embedding_benchmark_poststart_failure import (
    BenchmarkPoststartFailureApplication,
)

from tests.unit.embedding_benchmark_job_fixtures import SyntheticBenchmarkAdmission
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_benchmark_owner_admission import NOW
from tests.unit.test_embedding_benchmark_owner_admission import admitted as admitted
from tests.unit.test_embedding_benchmark_owner_composition import composition as composition


def select_successor(value, *, version="1.1"):
    assert version in {"1.1", "1.2"}
    policy = value.request.execution_policy.model_dump(mode="json") | {
        "schema_version": f"embedding-device-benchmark-policy/{version}",
        "policy_revision_id": "embeddingbenchmarkpolicyrev_" + "f" * 32,
        "timeout_seconds": 600 if version == "1.1" else 1200,
    }
    body = value.request.model_dump(mode="json") | {
        "schema_version": f"embedding-device-benchmark-request/{version}",
        "execution_policy": seal(policy, "policy_sha256"),
    }
    request = BenchmarkOwnerRequest.model_validate(seal(body, "request_sha256"))
    published = value.policy_publisher.publish_benchmark_policy(
        request.execution_policy,
        idempotency_key=f"synthetic-budget-{version}-policy",
        created_at=NOW,
    )
    value.owner.configuration = BenchmarkOwnerConfiguration(
        request.request_sha256, published.member, published.semantic_sha256
    )
    value.owner._source = SyntheticBenchmarkAdmission(request, value.inputs)
    return request, published


def test_successor_policy_uses_exact_registered_v11_member_and_current_owner_fence(admitted):
    value = admitted
    request, published = select_successor(value)
    assert published.member.schema_ref == BENCHMARK_POLICY_V11_SCHEMA_REF
    assert value.published.member.schema_ref == BENCHMARK_POLICY_SCHEMA_REF
    with value.publisher.sessions() as session, session.begin():
        with value.owner.admit_execution_in_session(session, request) as inputs:
            assert inputs == value.inputs
        assert value.owner._control.fence_current_operator.call_count == 2
    assert published.semantic_sha256 == request.execution_policy.policy_sha256
    assert published.member.sha256 != published.semantic_sha256
    assert published.member.artifact_id != value.published.member.artifact_id


def test_v12_policy_uses_exact_registered_member_and_current_owner_fence(admitted):
    value = admitted
    request, published = select_successor(value, version="1.2")
    assert published.member.schema_ref == BENCHMARK_POLICY_V12_SCHEMA_REF
    with value.publisher.sessions() as session, session.begin():
        with value.owner.admit_execution_in_session(session, request) as inputs:
            assert inputs == value.inputs
        assert value.owner._control.fence_current_operator.call_count == 2
    assert published.semantic_sha256 == request.execution_policy.policy_sha256
    assert published.member.sha256 != published.semantic_sha256


def test_predecessor_pointer_cannot_alias_a_successor_policy_before_any_source_read(admitted):
    value = admitted
    request, _published = select_successor(value)
    configuration = value.owner.configuration
    value.owner.configuration = replace(
        configuration,
        execution_policy=configuration.execution_policy.model_copy(
            update={"schema_ref": BENCHMARK_POLICY_SCHEMA_REF}
        ),
    )
    with (
        pytest.raises(ValueError, match="SELECTION_MISMATCH"),
        value.publisher.sessions() as session,
        session.begin(),
        value.owner.admit_execution_in_session(session, request),
    ):
        pytest.fail("mixed policy alias reached the application body")
    assert value.owner._source.entered == 0
    value.owner._control.fence_current_operator.assert_not_called()


def test_poststart_composition_selects_only_concrete_proof_adapter_without_effects(composition):
    value = composition
    inspection = FixedBenchmarkPoststartInspection("1" * 32, "sha256:" + "a" * 64)
    arguments = dict(
        request=value.request,
        configuration=value.configuration,
        capture=value.capture,
        session_fence=value.session_fence,
        inspection=inspection,
    )
    application = composition_module.build_benchmark_poststart_failure_application(
        value.publisher, **arguments
    )
    assert type(application) is BenchmarkPoststartFailureApplication
    assert application.inspection is inspection
    assert application.sessions is value.publisher.sessions
    with pytest.raises(ValueError, match="POSTSTART_COMPOSITION_INVALID"):
        composition_module.build_benchmark_poststart_failure_application(
            value.publisher,
            **(arguments | {"inspection": SimpleNamespace(capture=lambda: None)}),
        )
    assert embedding_device_benchmark_bytes(value.request)


def test_budget600_poststart_composition_keeps_the_same_fresh_operator_boundary(composition):
    value = composition
    inspection = FixedBudget600PoststartInspection("1" * 32, "sha256:" + "a" * 64)
    arguments = dict(
        request=value.request,
        configuration=value.configuration,
        capture=value.capture,
        session_fence=value.session_fence,
        inspection=inspection,
    )
    application = composition_module.build_benchmark_poststart_failure_application(
        value.publisher, **arguments
    )
    assert type(application) is BenchmarkPoststartFailureApplication
    assert application.inspection is inspection
    assert application.admission._control.capture is value.capture
    assert application.admission._control.fence is value.session_fence

    class UntrustedInspector(FixedBudget600PoststartInspection):
        pass

    with pytest.raises(ValueError, match="POSTSTART_COMPOSITION_INVALID"):
        composition_module.build_benchmark_poststart_failure_application(
            value.publisher,
            **(arguments | {"inspection": UntrustedInspector("1" * 32, "sha256:" + "a" * 64)}),
        )
