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
from eom_catalog_service.embedding_benchmark_prelaunch_inspection import (
    FixedBenchmarkPrelaunchInspection,
)
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins
from eom_identifiers import sha256_bytes
from eom_identity_service import AuthenticatedOperatorSession, AuthenticatedSessionFence
from eom_orchestrator.embedding_benchmark_prelaunch_failure import (
    BenchmarkPrelaunchFailureApplication,
)
from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkExecutionOwner
from eom_orchestrator.models import JobRecord
from sqlalchemy import func, select

from tests.unit.embedding_benchmark_prelaunch_failure_fixtures import observation
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


def build_closure(value, **changes):
    return module.build_benchmark_prelaunch_failure_application(
        value.publisher,
        **(
            dict(
                request=value.request,
                configuration=value.configuration,
                capture=value.capture,
                session_fence=value.session_fence,
                inspection=FixedBenchmarkPrelaunchInspection("1" * 32, "sha256:" + "a" * 64),
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


def test_closure_composition_selects_exact_inspector_and_fresh_admission_without_compute(
    composition, monkeypatch
):
    value = composition
    inspection = FixedBenchmarkPrelaunchInspection("1" * 32, "sha256:" + "b" * 64)

    def no_compute(*_args, **_kwargs):
        pytest.fail("closure construction must not inspect native backends or allocate compute")

    monkeypatch.setattr(module, "FixedBenchmarkLaunchExecution", no_compute)
    monkeypatch.setattr(module, "BenchmarkLaunchArtifactPublisher", no_compute)
    monkeypatch.setattr(NativeEmbeddingBackendPins, "__post_init__", no_compute)
    monkeypatch.setattr(FixedBenchmarkPrelaunchInspection, "capture", no_compute)
    with value.publisher.sessions.begin() as session:
        before = session.scalar(select(func.count()).select_from(JobRecord))
    application = build_closure(value, inspection=inspection)
    assert type(application) is BenchmarkPrelaunchFailureApplication
    assert application.sessions is value.publisher.sessions
    assert application.inspection is inspection
    assert application.admission.configuration == value.configuration
    assert application.admission._control.capture is value.capture
    assert application.admission._control.fence is value.session_fence
    assert not hasattr(application, "execution")
    with value.publisher.sessions.begin() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == before == 0


@pytest.mark.parametrize(
    "fault",
    ("parsed", "dict", "mock", "subclass", "unissued", "execution", "hash"),
)
def test_closure_composition_never_accepts_parsed_mocked_or_invalid_proof_adapter(
    composition, fault
):
    if fault == "parsed":
        inspection = observation()
    elif fault == "dict":
        inspection = observation().model_dump(mode="json")
    elif fault == "mock":
        inspection = Mock(spec=FixedBenchmarkPrelaunchInspection)
    elif fault == "subclass":

        class UntrustedInspection(FixedBenchmarkPrelaunchInspection):
            pass

        inspection = UntrustedInspection("1" * 32, "sha256:" + "a" * 64)
    else:
        inspection = object.__new__(FixedBenchmarkPrelaunchInspection)
        if fault != "unissued":
            object.__setattr__(inspection, "execution_id", "1" * 32 if fault == "hash" else "../1")
            object.__setattr__(
                inspection,
                "expected_raw_sha256",
                "invalid" if fault == "hash" else "sha256:" + "a" * 64,
            )
    with pytest.raises(ValueError, match="BENCHMARK_PRELAUNCH_COMPOSITION_INVALID"):
        build_closure(composition, inspection=inspection)


@pytest.mark.parametrize(
    "fault",
    (
        "raw",
        "request",
        "semantic",
        "audit_only",
        "unissued_capture",
        "freshness",
        "actor",
        "extras",
    ),
)
def test_closure_reuses_exact_policy_actor_capture_and_freshness_invariants(composition, fault):
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
    elif fault == "audit_only":
        changes["capture"] = SimpleNamespace(operator_id=value.request.operator_audit_id)
    elif fault == "unissued_capture":
        changes["capture"] = object.__new__(AuthenticatedOperatorSession)
    elif fault == "freshness":
        changes["session_fence"] = AuthenticatedSessionFence(replace(PIN, fresh_auth_seconds=1800))
    elif fault == "actor":
        request = BenchmarkOwnerRequest.model_validate(
            seal(
                value.request.model_dump(mode="json") | {"operator_audit_id": "foreign_admin"},
                "request_sha256",
            )
        )
        changes.update(
            request=request,
            configuration=replace(value.configuration, request_sha256=request.request_sha256),
        )
    else:
        changes["request"] = value.request.model_copy(
            update={"private_note": "PRIVATE_VALUE_NOT_FOR_ERRORS"}
        )
    with pytest.raises(ValueError, match="BENCHMARK_PRELAUNCH_COMPOSITION_INVALID") as error:
        build_closure(value, **changes)
    assert "PRIVATE_VALUE_NOT_FOR_ERRORS" not in str(error.value)


@pytest.mark.parametrize("fault", ("root", "mixed_uid", "mixed_gid", "groups", "ambient_release"))
def test_closure_composition_rejects_untrusted_caller_or_unpinned_source(
    composition, monkeypatch, fault
):
    if fault == "root":
        monkeypatch.setattr(module.os, "getresuid", lambda: (0, 0, 0))
    elif fault == "mixed_uid":
        monkeypatch.setattr(module.os, "getresuid", lambda: (0, 2000, 2000))
    elif fault == "mixed_gid":
        monkeypatch.setattr(module.os, "getresgid", lambda: (0, 2001, 2001))
    elif fault == "groups":
        monkeypatch.setattr(module.os, "getgroups", lambda: [123])
    else:
        composition.publisher.settings = replace(
            composition.publisher.settings, runtime_source_commit=None
        )
    with pytest.raises(ValueError, match="BENCHMARK_PRELAUNCH_COMPOSITION_INVALID"):
        build_closure(composition)


@pytest.mark.parametrize("field", ("publisher", "configuration", "session_fence"))
def test_closure_requires_exact_supported_publisher_configuration_and_fence(composition, field):
    mocked = Mock(spec=type(getattr(composition, field)))
    if field == "publisher":
        values = vars(composition) | {"publisher": mocked}
        with pytest.raises(ValueError, match="BENCHMARK_PRELAUNCH_COMPOSITION_INVALID"):
            build_closure(SimpleNamespace(**values))
    else:
        with pytest.raises(ValueError, match="BENCHMARK_PRELAUNCH_COMPOSITION_INVALID"):
            build_closure(composition, **{field: mocked})


def test_closure_preserves_stricter_freshness_and_defers_actual_authority_to_current_root(
    composition, monkeypatch
):
    fence = AuthenticatedSessionFence(replace(PIN, fresh_auth_seconds=600))
    application = build_closure(composition, session_fence=fence)
    assert application.admission._control.fence is fence
    probe = Mock(side_effect=AssertionError("inspection before current source/operator admission"))
    monkeypatch.setattr(FixedBenchmarkPrelaunchInspection, "capture", probe)
    with pytest.raises(ValueError):
        application.close(composition.request, job_id="job_" + "1" * 32)
    probe.assert_not_called()
    with composition.publisher.sessions.begin() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 0
