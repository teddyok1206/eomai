"""Synthetic PID1/root metadata only; no native effect, root claim or GPU test."""

from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_benchmark_preack_inspection as module
from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots

from tests.unit.embedding_device_benchmark_fixtures import worker_invocation
from tests.unit.test_embedding_benchmark_preack_recovery import root_observation
from tests.unit.test_embedding_device_benchmark_budget import successor_request_v12


def observation():
    return root_observation(successor_request_v12(), worker_invocation(2))


@pytest.fixture
def stopped(monkeypatch):
    fields = dict(
        LoadState="loaded",
        ActiveState="inactive",
        SubState="dead",
        MainPID="0",
        NFileDescriptorStore="0",
        InvocationID="6" * 32,
        Job="",
        ControlGroup="",
        NeedDaemonReload="no",
        DropInPaths="",
    )

    def run(argv, **kwargs):
        assert argv[:3] == ("/usr/bin/systemctl", "show", observation().native_service)
        assert kwargs["check"] is False and kwargs["timeout"] == 10
        return SimpleNamespace(
            returncode=0,
            stdout="".join(f"{k}={v}\n" for k, v in fields.items()).encode(),
            stderr=b"",
        )

    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(module, "root_owned_unit_processes", lambda _: ())
    return fields


def test_actual_read_only_owner_observation_of_retired_unit(stopped):
    module._require_original_unit_retired(observation())


def test_proof_uses_owner_readable_root_not_private_runtime_parent():
    assert str(module.PREACK_PROOF_ROOT) == "/opt/eom/embedding-benchmark-preack-proofs"


@pytest.mark.parametrize(
    "key,value",
    [
        ("MainPID", "42"),
        ("NFileDescriptorStore", "1"),
        ("InvocationID", "f" * 32),
        ("ActiveState", "activating"),
        ("ControlGroup", "/system.slice/foo"),
        ("Job", "123"),
        ("NeedDaemonReload", "yes"),
        ("DropInPaths", "/override"),
    ],
)
def test_changed_live_unit_is_not_a_recovery_grant(stopped, key, value):
    stopped[key] = value
    with pytest.raises(ValueError, match="PREACK_INSPECTION_INVALID"):
        module._require_original_unit_retired(observation())


def test_original_cgroup_must_be_empty(stopped, monkeypatch):
    monkeypatch.setattr(module, "root_owned_unit_processes", lambda _: (42,))
    with pytest.raises(ValueError, match="PREACK_INSPECTION_INVALID"):
        module._require_original_unit_retired(observation())


def test_captured_proof_cannot_outlive_its_context(stopped):
    captured = module.CapturedBenchmarkPreackInspection(
        observation(), NumericalRuntimeFileSnapshots(0)
    )
    captured.active = False
    with pytest.raises(ValueError, match="PREACK_INSPECTION_INVALID"):
        captured.assert_current()


@pytest.mark.parametrize(
    "execution,digest", [("../escape", "sha256:" + "a" * 64), ("a" * 32, "bad")]
)
def test_fixed_proof_requires_exact_execution_and_hash(execution, digest):
    with pytest.raises(ValueError, match="PREACK_INSPECTION_INVALID"):
        module.FixedBenchmarkPreackInspection(execution, digest)
