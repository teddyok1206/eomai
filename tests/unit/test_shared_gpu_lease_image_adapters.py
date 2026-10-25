"""Real image lock entrypoints over synthetic lease files; no model or device execution."""

from __future__ import annotations

import signal
import subprocess
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock
from types import SimpleNamespace

import pytest
from eom_gpu_lease import SHARED_GPU_LOCK_PATH, SharedGpuLease, SharedGpuLeaseError
from eom_gpu_lease import lease as adapter
from eom_image_provider import provider
from eom_image_trainer import cli as trainer
from eom_image_trainer.runner import TrainingRunnerError

from tests.unit.test_shared_gpu_lease import policy as policy

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def configured_policy(
    policy: adapter._LeasePolicy, monkeypatch: pytest.MonkeyPatch
) -> adapter._LeasePolicy:
    monkeypatch.setattr(adapter, "_production_policy", lambda: policy)
    # Synthetic root observation only. Real PID1 acceptance/ACK remains a live gate.
    monkeypatch.setattr(signal, "pthread_sigmask", lambda how, mask: {signal.SIGUSR1})
    monkeypatch.setattr(signal, "sigpending", lambda: set())
    monkeypatch.setattr(adapter, "request_unit_gpu_lease_retention", lambda lease: None)
    monkeypatch.setattr(
        signal,
        "sigtimedwait",
        lambda mask, timeout: SimpleNamespace(si_signo=signal.SIGUSR1, si_uid=0, si_pid=1234),
    )
    return policy


def test_provider_and_trainer_shared_branches_contend_on_same_inode(
    configured_policy: adapter._LeasePolicy,
) -> None:
    handle = trainer._lock_gpu(SHARED_GPU_LOCK_PATH)
    assert isinstance(handle, SharedGpuLease)
    try:
        with (
            pytest.raises(provider.ProviderError, match="LOCAL_IMAGE_GPU_UNAVAILABLE"),
            provider.acquire_gpu_lease(SHARED_GPU_LOCK_PATH),
        ):
            pytest.fail("provider acquired a held physical inode")
    finally:
        trainer._close_gpu_lock(handle)
    with (
        provider.acquire_gpu_lease(SHARED_GPU_LOCK_PATH),
        pytest.raises(TrainingRunnerError, match="IMAGE_TRAINING_GPU_BUSY"),
    ):
        trainer._lock_gpu(SHARED_GPU_LOCK_PATH)
    lease = adapter._claim(configured_policy)
    lease.close()


def test_invalid_shared_path_never_falls_back_to_legacy_or_creates_file(
    configured_policy: adapter._LeasePolicy,
) -> None:
    configured_policy.path.unlink()
    with (
        pytest.raises(provider.ProviderError, match="LOCAL_IMAGE_GPU_UNAVAILABLE"),
        provider.acquire_gpu_lease(SHARED_GPU_LOCK_PATH),
    ):
        pytest.fail("missing shared inode was admitted")
    with pytest.raises(TrainingRunnerError, match="IMAGE_TRAINING_GPU_LOCK_INVALID"):
        trainer._lock_gpu(SHARED_GPU_LOCK_PATH)
    assert not configured_policy.path.exists()


def test_provider_busy_wait_reuses_original_inode_and_enters_body_once(
    configured_policy: adapter._LeasePolicy, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle = trainer._lock_gpu(SHARED_GPU_LOCK_PATH)
    before = configured_policy.path.stat().st_ino
    sleeps: list[float] = []
    entered = 0

    def release_on_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        trainer._close_gpu_lock(handle)

    monkeypatch.setattr(provider.time, "sleep", release_on_sleep)
    with provider.acquire_gpu_lease(SHARED_GPU_LOCK_PATH, busy_wait_seconds=2):
        entered += 1
        assert configured_policy.path.stat().st_ino == before
        with pytest.raises(TrainingRunnerError, match="IMAGE_TRAINING_GPU_BUSY"):
            trainer._lock_gpu(SHARED_GPU_LOCK_PATH)
    assert entered == 1 and sleeps == [1.0]
    released = adapter._claim(configured_policy)
    released.close()


def test_provider_busy_wait_expires_without_entering_or_replacing_held_inode(
    configured_policy: adapter._LeasePolicy, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle = trainer._lock_gpu(SHARED_GPU_LOCK_PATH)
    now = [100.0]
    sleeps: list[float] = []

    def advance(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(provider.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(provider.time, "sleep", advance)
    try:
        with (
            pytest.raises(provider.ProviderError, match="LOCAL_IMAGE_GPU_UNAVAILABLE"),
            provider.acquire_gpu_lease(SHARED_GPU_LOCK_PATH, busy_wait_seconds=2),
        ):
            pytest.fail("model body entered while the original GPU mutex was held")
        assert sleeps == [1.0, 1.0]
    finally:
        trainer._close_gpu_lock(handle)


@pytest.mark.parametrize(
    "failure_stage", ["missing_inode", "body_busy", "body_model_error", "close_drift"]
)
def test_provider_busy_wait_never_retries_nonbusy_or_postentry_failure(
    configured_policy: adapter._LeasePolicy,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    def no_sleep(_seconds: float) -> None:
        pytest.fail("nonbusy or post-entry error was retried")

    monkeypatch.setattr(provider.time, "sleep", no_sleep)
    if failure_stage == "missing_inode":
        configured_policy.path.unlink()
    expected = (
        "LOCAL_IMAGE_MODEL_UNAVAILABLE"
        if failure_stage == "body_model_error"
        else "LOCAL_IMAGE_GPU_UNAVAILABLE"
    )
    with (
        pytest.raises(provider.ProviderError, match=expected),
        provider.acquire_gpu_lease(SHARED_GPU_LOCK_PATH, busy_wait_seconds=2),
    ):
        if failure_stage == "missing_inode":
            pytest.fail("missing inode admitted")
        if failure_stage == "body_busy":
            raise SharedGpuLeaseError("BUSY")
        if failure_stage == "close_drift":
            configured_policy.path.chmod(0o600)
            return
        raise provider.ProviderError("LOCAL_IMAGE_MODEL_UNAVAILABLE")


@pytest.mark.parametrize("budget", [-1, 901, True, 0.5, "2", None])
def test_provider_busy_wait_rejects_invalid_internal_budget_before_entry(budget: object) -> None:
    with (
        pytest.raises(provider.ProviderError, match="LOCAL_IMAGE_INPUT_INVALID"),
        provider.acquire_gpu_lease(SHARED_GPU_LOCK_PATH, busy_wait_seconds=budget),  # type: ignore[arg-type]
    ):
        pytest.fail("invalid budget admitted")


def test_provider_busy_wait_does_not_acquire_after_budget_even_if_holder_releases(
    configured_policy: adapter._LeasePolicy, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle = trainer._lock_gpu(SHARED_GPU_LOCK_PATH)
    now = [100.0]

    def release_at_deadline(seconds: float) -> None:
        now[0] += seconds
        if now[0] == 102.0:
            trainer._close_gpu_lock(handle)

    monkeypatch.setattr(provider.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(provider.time, "sleep", release_at_deadline)
    with (
        pytest.raises(provider.ProviderError, match="LOCAL_IMAGE_GPU_UNAVAILABLE"),
        provider.acquire_gpu_lease(SHARED_GPU_LOCK_PATH, busy_wait_seconds=2),
    ):
        pytest.fail("a new acquisition started after the original busy-wait budget")
    free = adapter._claim(configured_policy)
    free.close()


def test_provider_busy_wait_cancellation_does_not_enter_or_release_other_holder(
    configured_policy: adapter._LeasePolicy, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle = trainer._lock_gpu(SHARED_GPU_LOCK_PATH)

    def cancel(_seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(provider.time, "sleep", cancel)
    try:
        with (
            pytest.raises(KeyboardInterrupt),
            provider.acquire_gpu_lease(SHARED_GPU_LOCK_PATH, busy_wait_seconds=2),
        ):
            pytest.fail("cancelled waiter entered model body")
        with pytest.raises(SharedGpuLeaseError, match="BUSY"):
            adapter._claim(configured_policy)
    finally:
        trainer._close_gpu_lock(handle)


def test_two_waiting_providers_serialize_on_real_same_inode(
    configured_policy: adapter._LeasePolicy,
) -> None:
    gate, count_lock = Barrier(2), Lock()
    active = [0]
    entered: list[int] = []

    def run(number: int) -> None:
        gate.wait(timeout=5)
        with provider.acquire_gpu_lease(SHARED_GPU_LOCK_PATH, busy_wait_seconds=3):
            with count_lock:
                active[0] += 1
                assert active[0] == 1
                entered.append(number)
            provider.time.sleep(0.03)
            with count_lock:
                active[0] -= 1

    with ThreadPoolExecutor(max_workers=2) as pool:
        tuple(pool.map(run, (0, 1)))
    assert sorted(entered) == [0, 1] and active == [0]
    free = adapter._claim(configured_policy)
    free.close()


def test_legacy_arbitrary_same_uid_0700_0600_contract_still_returns_fd(tmp_path: Path) -> None:
    parent = tmp_path / "legacy"
    parent.mkdir(mode=0o700)
    path = parent / "gpu0.lock"
    with provider.acquire_gpu_lease(path):
        assert path.stat().st_mode & 0o777 == 0o600
        with pytest.raises(TrainingRunnerError, match="IMAGE_TRAINING_GPU_BUSY"):
            trainer._lock_gpu(path)
    descriptor = trainer._lock_gpu(path)
    assert isinstance(descriptor, int)
    trainer._close_gpu_lock(descriptor)
    with provider.acquire_gpu_lease(path):
        pass


@pytest.mark.parametrize("stage", ["lookup", "install", "restore", "body"])
def test_sigterm_lookup_install_restore_or_body_failure_always_releases(
    configured_policy: adapter._LeasePolicy, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    calls = 0

    def lookup(number: int) -> signal.Handlers:
        if stage == "lookup":
            raise RuntimeError("synthetic signal failure")
        return signal.SIG_DFL

    def set_handler(number: int, handler: object) -> signal.Handlers:
        nonlocal calls
        calls += 1
        if (stage == "install" and calls == 1) or (stage == "restore" and calls == 2):
            raise RuntimeError("synthetic signal failure")
        return signal.SIG_DFL

    monkeypatch.setattr(signal, "getsignal", lookup)
    monkeypatch.setattr(signal, "signal", set_handler)
    with (
        pytest.raises(RuntimeError, match="synthetic"),
        trainer._sigterm_gpu_lock(SHARED_GPU_LOCK_PATH, lambda number, frame: None),
    ):
        if stage == "body":
            raise RuntimeError("synthetic body failure")
    lease = adapter._claim(configured_policy)
    lease.close()


def test_shared_release_drift_maps_to_existing_trainer_invalid_label(
    configured_policy: adapter._LeasePolicy,
) -> None:
    handle = trainer._lock_gpu(SHARED_GPU_LOCK_PATH)
    configured_policy.path.chmod(0o600)
    with pytest.raises(TrainingRunnerError, match="IMAGE_TRAINING_GPU_LOCK_INVALID"):
        trainer._close_gpu_lock(handle)


def test_shared_release_drift_maps_to_existing_provider_label(
    configured_policy: adapter._LeasePolicy,
) -> None:
    with (
        pytest.raises(provider.ProviderError, match="LOCAL_IMAGE_GPU_UNAVAILABLE"),
        provider.acquire_gpu_lease(SHARED_GPU_LOCK_PATH),
    ):
        configured_policy.path.chmod(0o600)


def test_standalone_wheel_is_canonical_without_platform_record_overlap() -> None:
    platform = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert "packages/gpu_lease" not in platform["tool"]["setuptools"]["packages"]["find"]["where"]
    assert "packages/gpu_lease" in platform["tool"]["mypy"]["mypy_path"]
    assert "eom-gpu-lease==0.1.0" in platform["project"]["optional-dependencies"]["gpu-runtime"]
    assert not any("eom-gpu-lease" in value for value in platform["project"]["dependencies"])
    for component in ("image_provider", "image_trainer"):
        project = tomllib.loads((ROOT / "services" / component / "pyproject.toml").read_text())
        assert "eom-gpu-lease==0.1.0" in project["project"]["dependencies"]
    standalone = tomllib.loads((ROOT / "packages/gpu_lease/pyproject.toml").read_text())
    assert standalone["project"]["requires-python"] == ">=3.11,<3.13"
    assert standalone["project"]["dependencies"] == []


def test_only_shared_lease_error_crosses_public_infrastructure_boundary() -> None:
    assert issubclass(SharedGpuLeaseError, RuntimeError)
    assert str(SharedGpuLeaseError("INVALID")) == "INVALID"
    assert str(SharedGpuLeaseError("BUSY")) == "BUSY"


def test_legacy_provider_and_trainer_import_without_shared_distribution(tmp_path: Path) -> None:
    parent = tmp_path / "legacy-without-shared-package"
    parent.mkdir(mode=0o700)
    code = """import importlib.abc, sys
from pathlib import Path
sys.path[:0] = sys.argv[1:4]
class AbsentSharedPackage(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == 'eom_gpu_lease' or fullname.startswith('eom_gpu_lease.'):
            raise ModuleNotFoundError('synthetic unavailable optional distribution')
        return None
sys.meta_path.insert(0, AbsentSharedPackage())
from eom_image_provider import provider
from eom_image_trainer import cli as trainer
from eom_image_trainer.runner import TrainingRunnerError
assert 'eom_gpu_lease' not in sys.modules
path = Path(sys.argv[4]) / 'gpu0.lock'
with provider.acquire_gpu_lease(path):
    assert path.stat().st_mode & 0o777 == 0o600
descriptor = trainer._lock_gpu(path)
assert isinstance(descriptor, int)
trainer._close_gpu_lock(descriptor)
shared = Path('/run/eom-gpu-lease/gpu0.lock')
try:
    with provider.acquire_gpu_lease(shared):
        raise AssertionError('unavailable shared package was admitted')
except provider.ProviderError as error:
    assert error.code == 'LOCAL_IMAGE_GPU_UNAVAILABLE'
try:
    trainer._lock_gpu(shared)
    raise AssertionError('unavailable shared package was admitted')
except TrainingRunnerError as error:
    assert error.code == 'IMAGE_TRAINING_GPU_LOCK_INVALID'
assert 'eom_gpu_lease' not in sys.modules
print('LEGACY_WITHOUT_SHARED_PASS')
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            code,
            str(ROOT / "packages/image_contracts"),
            str(ROOT / "services/image_provider"),
            str(ROOT / "services/image_trainer"),
            str(parent),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "LEGACY_WITHOUT_SHARED_PASS"
