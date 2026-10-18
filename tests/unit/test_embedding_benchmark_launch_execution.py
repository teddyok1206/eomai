"""Concrete owner ordering with explicitly synthetic machine/admission/publication ports."""

import os
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.embedding_device_benchmark import embedding_device_benchmark_bytes
from eom_catalog_service import embedding_benchmark_launch_execution as execution
from eom_catalog_service.embedding_benchmark_launch import (
    BenchmarkLaunchPins,
    benchmark_launch_environment_bytes,
)
from eom_catalog_service.embedding_benchmark_launch_publication import (
    BenchmarkLaunchArtifactPublisher,
)
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins
from eom_identifiers import sha256_bytes
from eom_workflow.embedding_benchmark_launch_control import BenchmarkLaunchPrepared

from tests.unit.embedding_benchmark_control_fixtures import association, completed, prepared
from tests.unit.embedding_device_benchmark_fixtures import (
    launch_receipt,
    owner_request,
    staged_inputs,
    worker_invocation,
)
from tests.unit.inference_transfer_embedding_fixtures import seal


@pytest.fixture
def composition(monkeypatch):
    events = []
    state = SimpleNamespace(fault=None, association=None, prepared=None)
    pins = NativeEmbeddingBackendPins(**prepared(association(1)).backend.model_dump(mode="json"))
    publisher = BenchmarkLaunchArtifactPublisher(SimpleNamespace(), source_commit="a" * 40)

    def publish(invocation, *args, **kwargs):
        events.append("publish")
        return launch_receipt(invocation.launch_ordinal)

    monkeypatch.setattr(publisher, "publish", publish)
    adapter = execution.FixedBenchmarkLaunchExecution(
        owner_request(), cpu=pins, cuda=pins, controller_release="a" * 40, publisher=publisher
    )
    monkeypatch.setattr(adapter, "assert_installed", lambda _: events.append("installed"))

    def stage(request, invocation, inputs, **kwargs):
        assert request == owner_request() and inputs == staged_inputs()
        events.append("stage")
        body = association(invocation.launch_ordinal).model_dump(mode="json")
        body["expires_ns"] = kwargs["expires_ns"]
        from eom_workflow.embedding_benchmark_launch_control import BenchmarkLaunchAssociation

        value = BenchmarkLaunchAssociation.model_validate(seal(body, "association_sha256"))
        state.association = value
        return SimpleNamespace(association=value)

    class Control:
        def receive_prepared(self):
            events.append("prepared")
            invocation = worker_invocation(state.association.launch_ordinal)
            body = prepared(state.association).model_dump(mode="json")
            raw = benchmark_launch_environment_bytes(
                BenchmarkLaunchPins(
                    invocation.execution_id,
                    sha256_bytes(embedding_device_benchmark_bytes(invocation)),
                    os.getpid(),
                    state.association.expires_ns,
                    pins,
                )
            )
            body["environment_raw_sha256"] = sha256_bytes(raw)
            if state.fault == "selection":
                body["environment_raw_sha256"] = "sha256:" + "0" * 64
            state.prepared = BenchmarkLaunchPrepared.model_validate(seal(body, "prepared_sha256"))
            return state.prepared

        @contextmanager
        def resources(self):
            events.append("resource-borrow")
            try:
                yield object()
            finally:
                events.append("resource-return")

        def receive_completed(self):
            events.append("completed")
            if state.fault == "completion":
                raise ValueError("synthetic completion uncertainty")
            return completed(state.association, state.prepared)

        def close(self):
            events.append("control-close")

    def connect(*args, **kwargs):
        events.append("root-connect")
        if state.fault == "connect":
            raise ValueError("synthetic original connect uncertainty")
        return Control(), object()

    class Transport:
        @classmethod
        def connect(cls, *args, **kwargs):
            events.append("native-connect")
            return cls()

        def close(self):
            events.append("native-close")

    class Authorization:
        def assert_invocation(self, invocation):
            assert invocation == worker_invocation(invocation.launch_ordinal)
            events.append("authorize")

        def require_cpu_reference(self):
            events.append("cpu-reference")
            if state.fault == "reference":
                raise ValueError("synthetic original CPU reference unavailable")

    def observe(*args, **kwargs):
        events.append("observe")
        return object()

    monkeypatch.setattr(execution, "stage_owner_benchmark_launch", stage)
    monkeypatch.setattr(execution, "connect_benchmark_series_root", connect)
    monkeypatch.setattr(execution, "CapturedBenchmarkNativeConnection", Transport)
    monkeypatch.setattr(execution, "observe_benchmark_native_session", observe)
    monkeypatch.setattr(
        execution, "OwnerBenchmarkGpuResourceClient", lambda *args, **kwargs: object()
    )
    return adapter, Authorization(), state, events


@pytest.mark.parametrize("ordinal", range(1, 7))
def test_all_original_launches_reach_same_owner_publication_once(composition, ordinal):
    adapter, authorization, _state, events = composition
    receipt = adapter.run_and_publish(worker_invocation(ordinal), staged_inputs(), authorization)
    assert receipt == launch_receipt(ordinal)
    assert events.count("stage") == events.count("root-connect") == events.count("publish") == 1
    assert events.index("completed") < events.index("publish") < events.index("control-close")
    assert events[-2:] == ["native-close", "control-close"]
    if worker_invocation(ordinal).device == "CUDA":
        assert (
            events.index("resource-borrow")
            < events.index("observe")
            < events.index("resource-return")
        )
        assert events.index("resource-return") < events.index("completed")
    else:
        assert "resource-borrow" not in events
    if ordinal > 1:
        assert events.index("cpu-reference") < events.index("stage")
    else:
        assert "cpu-reference" not in events


def test_later_launch_cannot_stage_or_connect_before_original_cpu_seal(composition):
    adapter, authorization, state, events = composition
    state.fault = "reference"
    with pytest.raises(ValueError, match="CPU reference unavailable"):
        adapter.run_and_publish(worker_invocation(2), staged_inputs(), authorization)
    assert "cpu-reference" in events and "stage" not in events and "root-connect" not in events


@pytest.mark.parametrize("fault", ("connect", "selection", "completion"))
def test_uncertain_original_is_not_reconnected_reencoded_or_published(composition, fault):
    adapter, authorization, state, events = composition
    state.fault = fault
    with pytest.raises(ValueError):
        adapter.run_and_publish(worker_invocation(1), staged_inputs(), authorization)
    assert events.count("stage") == events.count("root-connect") == 1
    assert "publish" not in events
    if fault == "selection":
        assert "native-connect" not in events
