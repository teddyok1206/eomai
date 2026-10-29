"""Concrete readiness and exact selected-owner controls; not runtime/source activation."""

import json
import time
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow
from eom_catalog_service.embedding_registry_catalog_adapter import (
    EmbeddingRegistryOwnerConfiguration,
)
from eom_orchestrator.native_embedding_index_systemd import FixedNativeIndexLauncher
from eom_workflow_runner import local_embedding_native_executor as native
from eom_workflow_runner.document_embedding_cpu_execution import FixedCpuDocumentEmbeddingExecution
from eom_workflow_runner.local_embedding_native_executor import CatalogNativeEmbeddingExecutor
from eom_workflow_runner.local_embedding_owner_admission import LocalEmbeddingOwnerConfiguration
from eom_workflow_runner.local_indexing_service_entry import _failure_detail

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_admission_fixtures import native_fixture
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_embedding_batch_owner_channel import endpoints


@pytest.fixture
def executor(tmp_path):
    fixture = native_fixture()
    profile = fixture.policy.profiles[0]
    config = LocalEmbeddingOwnerConfiguration(
        EmbeddingRegistryOwnerConfiguration(
            fixture.plan.corpus_id,
            fixture.plan.namespace,
            profile.space,
            fixture.plan.recipe,
            ("PAST_EXAM",),
        ),
        fixture.request.native_execution_policy,
        fixture.request.native_execution_policy_sha256,
    )
    owner = SimpleNamespace(configuration=config, identity=Mock())
    launcher = Mock(spec=FixedNativeIndexLauncher)
    publisher, _ = _publisher(tmp_path)
    return (
        fixture,
        CatalogNativeEmbeddingExecutor(
            owner=owner,
            publisher=publisher,
            execution_backend=FixedCpuDocumentEmbeddingExecution(launcher),
            runtime_profile=profile,
            source_commit="a" * 40,
        ),
        launcher,
        owner,
    )


def test_readiness_reads_installed_closure_without_authentication_claim_or_model(executor) -> None:
    fixture, service, launcher, owner = executor
    assert service.evaluate(fixture.request).ready
    launcher.assert_current_runtime.assert_called_once()
    launcher.run.assert_not_called()
    owner.identity.fence_current_operator.assert_not_called()


@pytest.mark.parametrize(
    "field", ["source_policy", "source_hash", "namespace", "space", "installed"]
)
def test_wrong_configured_controls_fail_before_model_or_scope_mutation(executor, field) -> None:
    fixture, service, launcher, owner = executor
    body = fixture.request.model_dump(mode="json")
    if field == "source_policy":
        body["native_execution_policy"]["artifact_revision_id"] = "rev_" + "f" * 32
    if field == "source_hash":
        body["native_execution_policy_sha256"] = "sha256:" + "f" * 64
    if field == "namespace":
        body["namespace"]["view"] = "METADATA_ONLY"
    if field == "space":
        service.runtime_profile = native_fixture(device="CUDA").policy.profiles[0]
    if field == "installed":
        launcher.assert_current_runtime.side_effect = ValueError("synthetic installed mismatch")
    request = type(fixture.request).model_validate(seal(body, "request_sha256"))
    assert not service.evaluate(request).ready
    launcher.run.assert_not_called()
    owner.identity.fence_current_operator.assert_not_called()


def _execute_before_source_admission(service, request, *, key=None):
    workflow_id = "workflow_" + "a" * 32
    transaction = Mock(side_effect=AssertionError("source mutation must not start"))
    return service.execute(
        workflow=SimpleNamespace(workflow_id=workflow_id),
        step=SimpleNamespace(step_run_id="steprun_" + "b" * 32),
        request=request,
        command_lease=Mock(),
        idempotency_key=(
            f"local-embedding-step:{workflow_id}:encode_batch:1:"
            f"{request.workflow_definition_sha256}"
        )
        if key is None
        else key,
        fenced_transaction=transaction,
    )


@pytest.mark.parametrize("exception", [ValueError, OSError])
def test_execution_preserves_original_runtime_cause_without_logging_its_text(executor, exception):
    fixture, service, launcher, owner = executor
    original = exception("SECRET credential and arbitrary source text")
    launcher.assert_current_runtime.side_effect = original
    with pytest.raises(ValueError, match="LOCAL_EMBEDDING_EXECUTOR_CONTEXT_INVALID") as failed:
        _execute_before_source_admission(service, fixture.request)
    assert failed.value.__cause__ is original
    detail = _failure_detail(failed.value)
    assert detail["cause_type"] == exception.__name__
    assert "eom_workflow_runner.document_embedding_cpu_execution:" in detail["cause_site"]
    assert "SECRET" not in json.dumps(detail)
    assert "credential" not in json.dumps(detail)
    launcher.assert_current_runtime.assert_called_once()
    launcher.run.assert_not_called()
    owner.identity.fence_current_operator.assert_not_called()


def test_execution_preserves_real_finite_channel_expiry_cause(executor):
    from eom_catalog_service.embedding_batch_owner_channel import EmbeddingBatchOwnerChannelError

    fixture, service, launcher, _owner = executor
    with endpoints() as (_root, channel, *_):
        # Same real bounded channel used by CUDA readiness; no physical GPU or
        # source grant is supplied by this same-process socket fixture.
        channel._frames.expires_ns = time.monotonic_ns() - 1
        launcher.assert_current_runtime.side_effect = channel.require_direct_peer
        with pytest.raises(ValueError, match="LOCAL_EMBEDDING_EXECUTOR_CONTEXT_INVALID") as failed:
            _execute_before_source_admission(service, fixture.request)
        assert isinstance(failed.value.__cause__, EmbeddingBatchOwnerChannelError)
        detail = _failure_detail(failed.value)
        assert detail["cause_type"] != "ValueError"
        assert "eom_catalog_service." in detail["cause_site"]
        launcher.run.assert_not_called()


def test_execution_control_mismatch_stops_before_backend_or_source(executor):
    fixture, service, launcher, _owner = executor
    body = fixture.request.model_dump(mode="json")
    body["native_execution_policy_sha256"] = "sha256:" + "f" * 64
    request = type(fixture.request).model_validate(seal(body, "request_sha256"))
    with pytest.raises(ValueError, match="LOCAL_EMBEDDING_EXECUTOR_CONTEXT_INVALID") as failed:
        _execute_before_source_admission(service, request)
    assert str(failed.value.__cause__) == "LOCAL_EMBEDDING_EXECUTOR_CONTROLS_MISMATCH"
    launcher.assert_current_runtime.assert_not_called()
    launcher.run.assert_not_called()


def test_execution_idempotency_mismatch_still_stops_before_source(executor):
    fixture, service, launcher, _owner = executor
    with pytest.raises(ValueError, match="LOCAL_EMBEDDING_EXECUTOR_CONTEXT_INVALID") as failed:
        _execute_before_source_admission(service, fixture.request, key="incorrect-key")
    assert failed.value.__cause__ is None
    launcher.assert_current_runtime.assert_called_once()
    launcher.run.assert_not_called()


@pytest.mark.parametrize("cache_state", ["all_cached", "uncached", "revoked"])
def test_legacy_registered_row_basis_controls_numerical_reservation_before_launch(
    executor, monkeypatch, cache_state
):
    """Synthetic owner/basis seams; actual registered-row flow is disposable-DB tested."""
    fixture, service, launcher, owner = executor
    request = fixture.request
    owner.registry_caller = Mock(return_value=Mock())
    owner.catalog = SimpleNamespace(
        require_index_publication_scope=Mock(),
        prepare_index_basis=Mock(
            return_value=SimpleNamespace(
                reusable_rows=tuple(
                    RegisteredEmbeddingRow(demand.encoding, completion.receipt.row_ref)
                    for demand, completion in zip(
                        fixture.plan.demands, fixture.completions, strict=True
                    )
                )
                if cache_state == "all_cached"
                else (),
            )
        ),
    )
    if cache_state == "revoked":
        owner.catalog.prepare_index_basis.side_effect = ValueError("synthetic revoked cache")
    monkeypatch.setattr(
        service,
        "_current",
        lambda *_a, **_k: SimpleNamespace(admission=SimpleNamespace(plan=fixture.plan)),
    )
    allocation = native.NativeCoordinatorAllocation(
        index_producer=native.new_native_artifact_producer(),
        receipt_producer=native.new_native_artifact_producer(),
        created_at=fixture.policy.created_at,
        source_commit="a" * 40,
    )
    coordinator = Mock()
    coordinator.read.return_value = SimpleNamespace(
        state="RUNNING", records=(SimpleNamespace(payload=allocation),)
    )
    monkeypatch.setattr(native, "NativeEmbeddingCoordinator", Mock(return_value=coordinator))
    monkeypatch.setattr(
        native,
        "create_native_embedding_launch",
        Mock(return_value=SimpleNamespace(intent=fixture.association.intent)),
    )
    completion = Mock(return_value=object())
    monkeypatch.setattr(service._index_completion, "publish", completion)
    reservations = Mock(side_effect=RuntimeError("synthetic numerical reservation boundary"))
    monkeypatch.setattr(service, "_reservations", reservations)

    @contextmanager
    def fenced():
        yield Mock()

    workflow = SimpleNamespace(workflow_id=fixture.association.intent.workflow_id)
    values = dict(
        workflow=workflow,
        step=SimpleNamespace(step_run_id=fixture.association.intent.step_run_id),
        request=request,
        command_lease=SimpleNamespace(
            command_id="wfcmd_" + "3" * 32, runner_id="synthetic", lease_generation=1
        ),
        idempotency_key=f"local-embedding-step:{workflow.workflow_id}:encode_batch:1:{request.workflow_definition_sha256}",
        fenced_transaction=fenced,
    )
    if cache_state == "all_cached":
        assert service.execute(**values) is completion.return_value
        assert completion.call_args.args[7] == ()
        reservations.assert_not_called()
    elif cache_state == "uncached":
        with pytest.raises(RuntimeError, match="numerical reservation boundary"):
            service.execute(**values)
        reservations.assert_called_once()
        completion.assert_not_called()
    else:
        with pytest.raises(ValueError, match="revoked cache"):
            service.execute(**values)
        reservations.assert_not_called()
        completion.assert_not_called()
    owner.catalog.prepare_index_basis.assert_called_once()
    launcher.run.assert_not_called()
