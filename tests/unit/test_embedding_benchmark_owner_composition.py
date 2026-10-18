"""Actual adapter assembly and local DB; OS/Identity capture fixtures are synthetic."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_device_benchmark import (
    BENCHMARK_POLICY_SCHEMA_REF,
    BenchmarkOwnerRequest,
    embedding_device_benchmark_bytes,
)
from eom_catalog_service import embedding_benchmark_owner_composition as module
from eom_catalog_service.embedding_benchmark_owner_admission import BenchmarkOwnerConfiguration
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins
from eom_identifiers import sha256_bytes
from eom_identity_service import AuthenticatedOperatorSession, AuthenticatedSessionFence
from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkExecutionOwner
from eom_orchestrator.models import JobRecord
from sqlalchemy import func, select

from tests.unit.embedding_device_benchmark_fixtures import owner_request
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_authenticated_session_fence import PIN, verified_capture
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_reference_query_execution_contracts import pointer


@pytest.fixture
def composition(tmp_path, monkeypatch):
    publisher, engine = _publisher(tmp_path)
    publisher.settings = replace(publisher.settings, runtime_source_commit="a" * 40)
    _rows, capture = verified_capture(monkeypatch)
    request = BenchmarkOwnerRequest.model_validate(
        seal(
            owner_request().model_dump(mode="json") | {"operator_audit_id": capture.operator_id},
            "request_sha256",
        )
    )
    configuration = BenchmarkOwnerConfiguration(
        request.request_sha256,
        pointer(
            "policy.json",
            BENCHMARK_POLICY_SCHEMA_REF,
            sha256_bytes(embedding_device_benchmark_bytes(request.execution_policy)),
        ),
        request.execution_policy.policy_sha256,
    )

    def backend(seed):
        return NativeEmbeddingBackendPins(
            "embeddingnativeconfig_" + seed * 32,
            "embeddingnativeconfigrev_" + seed * 32,
            "sha256:" + seed * 64,
            "sha256:" + "a" * 64,
            "sha256:" + "b" * 64,
        )

    monkeypatch.setattr(
        module, "fixed_owner_identity", lambda: SimpleNamespace(owner_uid=2000, owner_gid=2001)
    )
    monkeypatch.setattr(module.os, "getresuid", lambda: (2000, 2000, 2000))
    monkeypatch.setattr(module.os, "getresgid", lambda: (2001, 2001, 2001))
    monkeypatch.setattr(module.os, "getgroups", lambda: [])
    yield SimpleNamespace(
        publisher=publisher,
        request=request,
        configuration=configuration,
        capture=capture,
        session_fence=AuthenticatedSessionFence(PIN),
        cpu=backend("1"),
        cuda=backend("2"),
    )
    engine.dispose()


def build(value, **changes):
    return module.build_benchmark_execution_owner(
        value.publisher,
        **(
            dict(
                request=value.request,
                configuration=value.configuration,
                capture=value.capture,
                session_fence=value.session_fence,
                cpu=value.cpu,
                cuda=value.cuda,
                controller_release="a" * 40,
            )
            | changes
        ),
    )


def test_concrete_composition_reuses_original_identity_engine_publisher_and_no_effects(composition):
    value = composition
    with value.publisher.sessions.begin() as session:
        before = session.scalar(select(func.count()).select_from(JobRecord))
    owner = build(value)
    assert type(owner) is BenchmarkExecutionOwner and owner.sessions is value.publisher.sessions
    assert owner.admission.configuration == value.configuration
    assert owner.admission._control.capture is value.capture
    assert owner.admission._control.fence is value.session_fence
    assert owner.execution._request == value.request
    assert owner.execution._publisher.publisher is value.publisher
    assert owner.execution._publisher.source_commit == "a" * 40
    assert owner.execution._cpu is value.cpu and owner.execution._cuda is value.cuda
    with value.publisher.sessions.begin() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == before == 0


@pytest.mark.parametrize(
    "fault",
    [
        "raw",
        "request",
        "semantic",
        "controller",
        "same_backend",
        "audit_only",
        "unissued_capture",
        "freshness",
        "actor",
        "request_extras",
    ],
)
def test_invalid_selection_or_stored_audit_identity_cannot_construct_an_owner(composition, fault):
    value = composition
    changes = {}
    if fault in {"raw", "request", "semantic"}:
        config = value.configuration
        if fault == "raw":
            config = replace(
                config,
                execution_policy=config.execution_policy.model_copy(
                    update={"sha256": "sha256:" + "f" * 64}
                ),
            )
        elif fault == "request":
            config = replace(config, request_sha256="sha256:" + "f" * 64)
        else:
            config = replace(config, execution_policy_sha256="sha256:" + "f" * 64)
        changes["configuration"] = config
    elif fault == "controller":
        changes["controller_release"] = "b" * 40
    elif fault == "same_backend":
        changes["cuda"] = value.cpu
    elif fault == "audit_only":
        changes["capture"] = SimpleNamespace(operator_id=value.request.operator_audit_id)
    elif fault == "unissued_capture":
        changes["capture"] = object.__new__(AuthenticatedOperatorSession)
    elif fault == "actor":
        request = BenchmarkOwnerRequest.model_validate(
            seal(
                value.request.model_dump(mode="json")
                | {"operator_audit_id": "operator_" + "f" * 32},
                "request_sha256",
            )
        )
        changes["request"] = request
        changes["configuration"] = replace(
            value.configuration, request_sha256=request.request_sha256
        )
    elif fault == "request_extras":
        changes["request"] = value.request.model_copy(
            update={"private_note": "PRIVATE_VALUE_NOT_FOR_ERRORS"}
        )
    else:
        changes["session_fence"] = AuthenticatedSessionFence(replace(PIN, fresh_auth_seconds=1800))
    with pytest.raises(ValueError, match="BENCHMARK_OWNER_COMPOSITION_INVALID") as error:
        build(value, **changes)
    assert "PRIVATE_VALUE_NOT_FOR_ERRORS" not in str(error.value)


def test_stricter_actual_freshness_is_preserved_not_replaced_with_a_default(composition):
    fence = AuthenticatedSessionFence(replace(PIN, fresh_auth_seconds=600))
    owner = build(composition, session_fence=fence)
    assert owner.admission._control.fence is fence
    assert owner.admission._control.fence.owner.fresh_auth_seconds == 600


@pytest.mark.parametrize("fault", ["root", "mixed_uid", "group", "ambient_release"])
def test_untrusted_process_or_missing_installed_release_is_not_an_execution_grant(
    composition, monkeypatch, fault
):
    value = composition
    if fault == "root":
        monkeypatch.setattr(module.os, "getresuid", lambda: (0, 0, 0))
    elif fault == "mixed_uid":
        monkeypatch.setattr(module.os, "getresuid", lambda: (0, 2000, 2000))
    elif fault == "group":
        monkeypatch.setattr(module.os, "getgroups", lambda: [123])
    else:
        value.publisher.settings = replace(value.publisher.settings, runtime_source_commit=None)
    with pytest.raises(ValueError, match="BENCHMARK_OWNER_COMPOSITION_INVALID"):
        build(value)


def test_construction_does_not_bypass_actual_caller_root_fencing(composition, monkeypatch):
    value = composition
    owner = build(value)
    probe = Mock(side_effect=AssertionError("runtime probe before actual operator admission"))
    monkeypatch.setattr(owner.execution, "assert_installed", probe)
    with pytest.raises(ValueError):
        # SQLite is not an admitted PostgreSQL owner root; the real Identity
        # fence must reject it before an installed probe or Job reservation.
        owner.run_launches(value.request)
    probe.assert_not_called()
    with value.publisher.sessions.begin() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 0
