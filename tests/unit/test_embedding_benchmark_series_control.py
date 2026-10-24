"""Real Unix framing/ordered rendezvous; root/source/unit/runtime evidence is synthetic."""

import os
import socket
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkResourceEvidence,
    BenchmarkWorkerInvocation,
    embedding_device_benchmark_bytes,
)
from eom_catalog_service import embedding_benchmark_root_control as root
from eom_catalog_service import embedding_benchmark_series_control as series
from eom_catalog_service.embedding_benchmark_channel import (
    BenchmarkResourceChannel,
    BenchmarkUnixPeer,
)
from eom_catalog_service.embedding_benchmark_control_channel import BenchmarkLaunchControlChannel
from eom_catalog_service.embedding_benchmark_launch_workspace import StagedOwnerBenchmarkLaunch
from eom_catalog_service.embedding_benchmark_layout import benchmark_series_socket_name
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins
from eom_identifiers import sha256_bytes
from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffIdentity
from eom_workflow.embedding_benchmark_launch_control import BenchmarkLaunchAssociation

from tests.unit.embedding_benchmark_control_fixtures import association, prepared
from tests.unit.embedding_device_benchmark_fixtures import (
    owner_request,
    resources,
    staged_inputs,
    worker_invocation,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_benchmark_channel import local_resources


def staged_launch(ordinal, *, job="a", fault=None):
    invocation = worker_invocation(ordinal)
    body = invocation.model_dump(mode="json") | {"job_id": "job_" + job * 32}
    invocation = BenchmarkWorkerInvocation.model_validate(seal(body, "invocation_sha256"))
    raw = embedding_device_benchmark_bytes(invocation)
    body = association(ordinal).model_dump(mode="json")
    body.update(
        job_id=invocation.job_id,
        invocation_sha256=invocation.invocation_sha256,
        invocation=dict(
            member_name="invocation.json", sha256=sha256_bytes(raw), byte_count=len(raw)
        ),
    )
    if fault == "request":
        body["owner_request_sha256"] = "sha256:" + "f" * 64
    elif fault == "birth":
        body["owner_start_ticks"] = 2
    value = BenchmarkLaunchAssociation.model_validate(seal(body, "association_sha256"))
    return StagedOwnerBenchmarkLaunch(value, owner_request(), invocation, staged_inputs())


def resource_for(invocation, *, local=False):
    value = (
        local_resources(invocation.launch_ordinal)
        if local
        else resources(invocation.launch_ordinal)
    )
    return BenchmarkResourceEvidence.model_validate(
        seal(
            value.model_dump(mode="json") | {"invocation_sha256": invocation.invocation_sha256},
            "resource_sha256",
        )
    )


@pytest.fixture
def rendezvous(monkeypatch):
    ready = Event()
    stages, effects, saved, selected_backends = {}, [], [], []
    peer = BenchmarkUnixPeer(os.getpid(), os.getuid(), os.getgid())
    monkeypatch.setattr(series, "require_root_benchmark_control", lambda: None)
    monkeypatch.setattr(root, "require_root_benchmark_control", lambda: None)
    monkeypatch.setattr(
        series, "fixed_owner_identity", lambda: CpuHandoffIdentity(peer.uid, peer.gid)
    )
    monkeypatch.setattr(series, "benchmark_owner_start_ticks", lambda *args, **kwargs: 1)
    monkeypatch.setattr(root, "benchmark_owner_start_ticks", lambda *args, **kwargs: 1)
    monkeypatch.setattr(
        root.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=peer.uid, pw_gid=peer.gid)
    )
    monkeypatch.setattr(
        series,
        "capture_benchmark_runtime_installation",
        lambda *args, **kwargs: Mock(assert_unchanged=Mock()),
    )
    monkeypatch.setattr(root, "prepare_benchmark_handoff", lambda *args: object())
    monkeypatch.setattr(
        root,
        "prepare_benchmark_environment",
        lambda *args, **kwargs: SimpleNamespace(
            owner_start_ticks=1, environment_raw_sha256="sha256:" + "a" * 64
        ),
    )
    monkeypatch.setattr(
        root, "_persist_root_control", lambda execution, name, raw: saved.append((execution, name))
    )

    def read_stage(execution_id, *, expected):
        staged = stages[execution_id]
        assert staged.association == expected
        return staged

    monkeypatch.setattr(series, "read_owner_benchmark_launch", read_stage)
    state = SimpleNamespace(fail=False, uncertain=False)

    class SyntheticDriver:
        def __init__(self, *args, **kwargs):
            if isinstance(args[0], socket.socket):
                self.duplicate, self.invocation = args[0], args[1]
            else:
                self.duplicate, self.invocation = None, args[0]
            selected_backends.append(kwargs["backend"])

        def run(self):
            invocation = self.invocation
            effects.append(invocation.execution_id)
            if state.uncertain:
                raise TimeoutError("synthetic original unit uncertainty")
            if self.duplicate is not None:
                resource = BenchmarkResourceChannel(
                    self.duplicate,
                    invocation,
                    expected_peer=peer,
                    peer_fence=lambda _: None,
                    expires_ns=stages[invocation.execution_id].association.expires_ns,
                )
                try:
                    assert resource.receive_resources() == resource_for(invocation, local=True)
                    resource.send_resources(resource_for(invocation))
                finally:
                    resource.close()
            return SimpleNamespace(
                execution_id=invocation.execution_id,
                job_id=invocation.job_id,
                invocation_sha256=invocation.invocation_sha256,
                started_ns=100,
                completed_ns=200,
                outcome="FAILED" if state.fail else "SUCCEEDED",
                resources=resource_for(invocation),
            )

    monkeypatch.setattr(root, "FixedRootBenchmarkCpuDriver", SyntheticDriver)
    monkeypatch.setattr(root, "FixedRootBenchmarkCudaDriver", SyntheticDriver)
    cpu = NativeEmbeddingBackendPins(**prepared(association(1)).backend.model_dump(mode="json"))
    cuda_pin = replace(cpu, configuration_revision_id="embeddingnativeconfigrev_" + "f" * 32)
    selection = series.BenchmarkRootSeriesSelection(
        owner_request(), peer.pid, 1, time.monotonic_ns() + 30 * 10**9, cpu, cuda_pin, "a" * 40
    )
    with tempfile.TemporaryDirectory(prefix="eom-series-") as directory:
        path = Path(directory) / benchmark_series_socket_name(
            selection.request.benchmark_revision_id
        )

        @contextmanager
        def listener(name):
            assert name == path.name
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(str(path))
            sock.listen(1)
            sock.setblocking(False)
            ready.set()
            try:
                yield sock
            finally:
                sock.close()
                path.unlink()

        monkeypatch.setattr(series, "root_benchmark_listener", listener)
        yield SimpleNamespace(
            selection=selection,
            ready=ready,
            path=path,
            stages=stages,
            effects=effects,
            saved=saved,
            selected_backends=selected_backends,
            peer=peer,
            state=state,
            cuda=root.RootBenchmarkCudaRuntime(
                Mock(assert_unchanged=Mock()), Mock(assert_current=Mock())
            ),
        )


def connect_owner(case, staged):
    case.stages[staged.invocation.execution_id] = staged
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.connect(str(case.path))
    return BenchmarkLaunchControlChannel(
        connection,
        staged.association,
        side="OWNER",
        expected_peer=case.peer,
        peer_fence=lambda _: None,
        controller_release="a" * 40,
    )


def finish_launch(owner, staged, peer):
    owner.send_association()
    owner.receive_prepared()
    if staged.invocation.device == "CUDA":
        with owner.resources() as duplicate:
            resource = BenchmarkResourceChannel(
                duplicate,
                staged.invocation,
                expected_peer=peer,
                peer_fence=lambda _: None,
                expires_ns=staged.association.expires_ns,
            )
            try:
                resource.send_resources(resource_for(staged.invocation, local=True))
                assert resource.receive_resources() == resource_for(staged.invocation)
            finally:
                resource.close()
    return owner.receive_completed()


def test_six_original_stages_use_one_listener_and_the_same_root_driver_and_resource_path(
    rendezvous,
):
    case = rendezvous
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(series.serve_root_benchmark_series, case.selection, cuda=case.cuda)
        if not case.ready.wait(3):
            future.result(timeout=1)
            pytest.fail("series exited without a listening socket")
        completed = []
        for ordinal in range(1, 7):
            staged = staged_launch(ordinal)
            owner = connect_owner(case, staged)
            try:
                completed.append(finish_launch(owner, staged, case.peer))
            finally:
                owner.close()
        assert future.result(timeout=3) == tuple(completed)
    assert len(case.effects) == len(set(case.effects)) == 6
    assert [record[1] for record in case.saved] == [
        "root-prepared.json",
        "root-completion.json",
    ] * 6
    assert case.selected_backends == [
        case.selection.cpu,
        case.selection.cuda,
        case.selection.cuda,
        case.selection.cpu,
        case.selection.cpu,
        case.selection.cuda,
    ]
    assert not case.path.exists()


def test_completed_prefix_is_not_redispatched_when_root_serves_original_suffix(rendezvous):
    case = rendezvous
    selection = replace(case.selection, first_ordinal=2)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(series.serve_root_benchmark_series, selection, cuda=case.cuda)
        assert case.ready.wait(3)
        completed = []
        for ordinal in range(2, 7):
            staged = staged_launch(ordinal)
            owner = connect_owner(case, staged)
            try:
                completed.append(finish_launch(owner, staged, case.peer))
            finally:
                owner.close()
        assert future.result(timeout=3) == tuple(completed)
    assert len(case.effects) == len(set(case.effects)) == 5
    assert case.selected_backends == [
        selection.cuda,
        selection.cuda,
        selection.cpu,
        selection.cpu,
        selection.cuda,
    ]


@pytest.mark.parametrize("ordinal", [0, 7, True, 2.0, "2"])
def test_suffix_selection_is_bounded_before_listener_or_effects(rendezvous, ordinal):
    with pytest.raises(ValueError, match="SELECTION_INVALID"):
        replace(rendezvous.selection, first_ordinal=ordinal)
    assert not rendezvous.effects


def test_suffix_listener_cannot_reexecute_completed_cpu1(rendezvous):
    case = rendezvous
    selection = replace(case.selection, first_ordinal=2)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(series.serve_root_benchmark_series, selection, cuda=case.cuda)
        assert case.ready.wait(3)
        staged = staged_launch(1)
        owner = connect_owner(case, staged)
        try:
            with pytest.raises(ValueError):
                finish_launch(owner, staged, case.peer)
        finally:
            owner.close()
        with pytest.raises(ValueError):
            future.result(timeout=3)
    assert not case.effects


@pytest.mark.parametrize("fault", ["order", "request", "birth", "job", "failed", "uncertain"])
def test_wrong_original_or_failed_or_uncertain_launch_stops_without_a_replacement(
    rendezvous, fault
):
    case = rendezvous
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(series.serve_root_benchmark_series, case.selection, cuda=case.cuda)
        if not case.ready.wait(3):
            future.result(timeout=1)
            pytest.fail("series exited without a listening socket")
        if fault == "job":
            staged = staged_launch(1)
            owner = connect_owner(case, staged)
            try:
                finish_launch(owner, staged, case.peer)
            finally:
                owner.close()
        ordinal = 2 if fault in {"order", "job"} else 1
        staged = staged_launch(ordinal, job="b" if fault == "job" else "a", fault=fault)
        case.state.fail, case.state.uncertain = fault == "failed", fault == "uncertain"
        owner = connect_owner(case, staged)
        try:
            if fault == "failed":
                assert finish_launch(owner, staged, case.peer).original_outcome == "FAILED"
            else:
                with pytest.raises(ValueError):
                    finish_launch(owner, staged, case.peer)
        finally:
            owner.close()
        with pytest.raises((ValueError, TimeoutError)):
            future.result(timeout=3)
    assert len(case.effects) == int(fault in {"job", "failed", "uncertain"})
    assert not case.path.exists()


@pytest.mark.parametrize(
    "revision", [None, True, "../escape", "a" * 32, "embeddingbenchmarkrev_" + "a" * 31]
)
def test_series_storage_label_never_accepts_arbitrary_paths_or_hash_prefixes(revision):
    with pytest.raises(ValueError, match="REVISION_INVALID"):
        benchmark_series_socket_name(revision)


def test_actual_nonroot_cannot_start_a_controller_or_capture_a_selection():
    if os.geteuid() == 0:
        pytest.skip("requires actual nonroot")
    with pytest.raises(ValueError, match="ROOT_REQUIRED"):
        series.serve_root_benchmark_series(None, cuda=None)
