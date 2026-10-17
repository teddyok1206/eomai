"""Synthetic root ACK and real duplicate-FD lifetime; no PID1, GPU or model execution."""

from __future__ import annotations

import ast
import inspect
import os
import signal
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_gpu_lease import lease as adapter

from scripts.image_provider import run_gpu_unit as bootstrap
from tests.unit.test_shared_gpu_lease import policy as policy


@pytest.fixture
def unit_entry(policy, monkeypatch):
    retained = []
    events = []
    monkeypatch.setattr(adapter, "_production_policy", lambda: policy)

    def mask(how, selected):
        assert how == signal.SIG_BLOCK and selected == set()
        events.append("MASK_QUERY_ONLY")
        return {signal.SIGUSR1}

    def retain(lease):
        lease.assert_valid()
        retained.append(os.dup(lease.fileno()))
        events.append("RETENTION_REQUESTED")

    def acknowledge(selected, timeout):
        assert selected == {signal.SIGUSR1} and timeout == 30
        assert events[-1] == "RETENTION_REQUESTED"
        with pytest.raises(adapter.SharedGpuLeaseError, match="BUSY"):
            adapter.acquire_shared_gpu_lease()
        events.append("SYNTHETIC_ROOT_ACK")
        return SimpleNamespace(si_signo=signal.SIGUSR1, si_uid=0, si_pid=1234)

    monkeypatch.setattr(signal, "pthread_sigmask", mask)
    monkeypatch.setattr(signal, "sigpending", lambda: set())
    monkeypatch.setattr(adapter, "request_unit_gpu_lease_retention", retain)
    monkeypatch.setattr(signal, "sigtimedwait", acknowledge)
    try:
        yield policy, retained, events
    finally:
        for descriptor in retained:
            os.close(descriptor)


def test_root_ack_precedes_yield_and_worker_close_does_not_release_retained_copy(unit_entry):
    _, retained, events = unit_entry
    with adapter.retained_unit_gpu_lease() as lease:
        lease.assert_valid()
        assert events == ["MASK_QUERY_ONLY", "RETENTION_REQUESTED", "SYNTHETIC_ROOT_ACK"]
    with pytest.raises(adapter.SharedGpuLeaseError, match="BUSY"):
        adapter.acquire_shared_gpu_lease()
    os.close(retained.pop())
    with adapter.shared_gpu_lease():
        pass


@pytest.mark.parametrize(
    "received",
    [
        None,
        SimpleNamespace(si_signo=signal.SIGUSR1, si_uid=1000, si_pid=1234),
        SimpleNamespace(si_signo=signal.SIGUSR2, si_uid=0, si_pid=1234),
        SimpleNamespace(si_signo=signal.SIGUSR1, si_uid=0, si_pid=0),
    ],
)
def test_missing_foreign_wrong_or_kernel_signal_cannot_admit_and_duplicate_stays_held(
    unit_entry,
    monkeypatch,
    received,
):
    _, retained, events = unit_entry
    monkeypatch.setattr(signal, "sigtimedwait", lambda selected, timeout: received)
    with (
        pytest.raises(adapter.SharedGpuLeaseError, match="INVALID"),
        adapter.retained_unit_gpu_lease(),
    ):
        pytest.fail("work started without the root observation ACK")
    assert events == ["MASK_QUERY_ONLY", "RETENTION_REQUESTED"]
    assert len(retained) == 1
    with pytest.raises(adapter.SharedGpuLeaseError, match="BUSY"):
        adapter.acquire_shared_gpu_lease()
    os.close(retained.pop())
    with adapter.shared_gpu_lease():
        pass


@pytest.mark.parametrize("stage", ["mask", "pending"])
def test_missing_bootstrap_or_early_signal_fails_before_claim_or_retention(
    unit_entry,
    monkeypatch,
    stage,
):
    _, retained, events = unit_entry
    if stage == "mask":
        monkeypatch.setattr(signal, "pthread_sigmask", lambda how, selected: set())
    else:
        monkeypatch.setattr(signal, "sigpending", lambda: {signal.SIGUSR1})
    monkeypatch.setattr(
        adapter,
        "acquire_shared_gpu_lease",
        lambda: pytest.fail("invalid bootstrap reached physical claim"),
    )
    with pytest.raises(adapter.SharedGpuLeaseError, match="INVALID"):
        adapter.acquire_retained_unit_gpu_lease()
    assert not retained and "RETENTION_REQUESTED" not in events


@pytest.mark.parametrize(
    "failure", [OSError("synthetic"), ValueError("synthetic"), KeyboardInterrupt()]
)
def test_wait_failure_or_cancellation_never_releases_pid1_copy(unit_entry, monkeypatch, failure):
    _, retained, _ = unit_entry

    def failed_wait(selected, timeout):
        raise failure

    monkeypatch.setattr(signal, "sigtimedwait", failed_wait)
    expected = (
        KeyboardInterrupt if isinstance(failure, KeyboardInterrupt) else adapter.SharedGpuLeaseError
    )
    with pytest.raises(expected):
        adapter.acquire_retained_unit_gpu_lease()
    with pytest.raises(adapter.SharedGpuLeaseError, match="BUSY"):
        adapter.acquire_shared_gpu_lease()
    os.close(retained.pop())
    with adapter.shared_gpu_lease():
        pass


def test_busy_is_preserved_and_never_requests_retention(unit_entry):
    _, retained, events = unit_entry
    with adapter.shared_gpu_lease(), pytest.raises(adapter.SharedGpuLeaseError, match="BUSY"):
        adapter.acquire_retained_unit_gpu_lease()
    assert events == ["MASK_QUERY_ONLY"] and not retained


@pytest.mark.parametrize("failure", [OSError("retention uncertain"), KeyboardInterrupt()])
def test_retention_failure_after_duplicate_preserves_that_duplicate(
    unit_entry, monkeypatch, failure
):
    _, retained, _ = unit_entry
    original = adapter.request_unit_gpu_lease_retention

    def fail_after_send(lease):
        original(lease)
        raise failure

    monkeypatch.setattr(adapter, "request_unit_gpu_lease_retention", fail_after_send)
    expected = (
        KeyboardInterrupt if isinstance(failure, KeyboardInterrupt) else adapter.SharedGpuLeaseError
    )
    with pytest.raises(expected):
        adapter.acquire_retained_unit_gpu_lease()
    with pytest.raises(adapter.SharedGpuLeaseError, match="BUSY"):
        adapter.acquire_shared_gpu_lease()
    os.close(retained.pop())
    with adapter.shared_gpu_lease():
        pass


def test_body_failure_after_ack_closes_worker_but_not_retained_duplicate(unit_entry):
    _, retained, _ = unit_entry
    with pytest.raises(RuntimeError, match="synthetic body"), adapter.retained_unit_gpu_lease():
        raise RuntimeError("synthetic body")
    with pytest.raises(adapter.SharedGpuLeaseError, match="BUSY"):
        adapter.acquire_shared_gpu_lease()
    os.close(retained.pop())
    with adapter.shared_gpu_lease():
        pass


def test_lease_changed_while_waiting_is_rejected_before_yield(unit_entry, monkeypatch):
    policy, retained, _ = unit_entry

    def changed(selected, timeout):
        policy.path.chmod(0o600)
        return SimpleNamespace(si_signo=signal.SIGUSR1, si_uid=0, si_pid=1234)

    monkeypatch.setattr(signal, "sigtimedwait", changed)
    with pytest.raises(adapter.SharedGpuLeaseError, match="INVALID"):
        adapter.acquire_retained_unit_gpu_lease()
    assert len(retained) == 1


def test_retained_entry_has_no_caller_authority_or_model_import():
    assert not inspect.signature(adapter.acquire_retained_unit_gpu_lease).parameters
    assert not inspect.signature(adapter.retained_unit_gpu_lease).parameters
    tree = ast.parse(Path(adapter.__file__).read_text())
    imports = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    imports.update(
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    assert not imports & {
        "torch",
        "numpy",
        "eom_catalog_service",
        "eom_orchestrator",
        "eom_image_provider",
        "eom_image_trainer",
        "sqlalchemy",
        "httpx",
    }
    ast.parse(Path(adapter.__file__).read_text(), feature_version=(3, 11))
    ast.parse(Path(bootstrap.__file__).read_text(), feature_version=(3, 11))


@pytest.fixture
def fixed_bootstrap(monkeypatch):
    events = []
    state = SimpleNamespace(
        argv=[
            "run_gpu_unit.py",
            "PROVIDER",
            "generate-composite",
            "--x",
            "--gpu-lock",
            str(adapter.SHARED_GPU_LOCK_PATH),
        ],
        prefix="/srv/eom/conda/envs/eom-image",
        executable="/srv/eom/conda/envs/eom-image/bin/python3.11",
        flags=SimpleNamespace(isolated=1),
        dont_write_bytecode=True,
        platform="linux",
        modules={},
    )
    identity = SimpleNamespace(uid=(984,) * 3, gid=(980,) * 3, groups=[980, 974])
    monkeypatch.setattr(bootstrap, "sys", state)
    monkeypatch.setattr(
        bootstrap,
        "pwd",
        SimpleNamespace(getpwnam=lambda name: SimpleNamespace(pw_uid=984, pw_gid=980)),
    )
    monkeypatch.setattr(
        bootstrap, "grp", SimpleNamespace(getgrnam=lambda name: SimpleNamespace(gr_gid=974))
    )
    monkeypatch.setattr(
        bootstrap,
        "os",
        SimpleNamespace(
            getresuid=lambda: identity.uid,
            getresgid=lambda: identity.gid,
            getgroups=lambda: identity.groups,
        ),
    )
    monkeypatch.setattr(
        bootstrap,
        "signal",
        SimpleNamespace(
            SIG_BLOCK=signal.SIG_BLOCK,
            SIGUSR1=signal.SIGUSR1,
            pthread_sigmask=lambda how, mask: events.append(("BLOCK", how, mask)),
        ),
    )
    monkeypatch.setattr(
        bootstrap,
        "runpy",
        SimpleNamespace(
            run_module=lambda module, **kwargs: events.append(("IMPORT", module, kwargs))
        ),
    )
    return state, identity, events


@pytest.mark.parametrize(
    "role,prefix,module,entry",
    [
        ("PROVIDER", "eom-image", "eom_image_provider.cli", "eom-local-image"),
        ("TRAINER", "eom-image-trainer", "eom_image_trainer.cli", "eom-local-image-trainer"),
    ],
)
def test_fixed_bootstrap_blocks_ack_before_importing_cli(
    fixed_bootstrap, role, prefix, module, entry
):
    state, _, events = fixed_bootstrap
    state.argv[1] = role
    state.prefix = "/srv/eom/conda/envs/" + prefix
    state.executable = state.prefix + "/bin/python3.11"
    bootstrap.main()
    assert events == [
        ("BLOCK", signal.SIG_BLOCK, {signal.SIGUSR1}),
        ("IMPORT", module, {"run_name": "__main__", "alter_sys": True}),
    ]
    assert state.argv == [
        state.prefix + "/bin/" + entry,
        "generate-composite",
        "--x",
        "--gpu-lock",
        str(adapter.SHARED_GPU_LOCK_PATH),
    ]


@pytest.mark.parametrize(
    "selection",
    [
        [],
        ["--gpu-lock"],
        ["--gpu-lock", "/var/lib/eom-image/gpu0.lock"],
        ["--gpu-l", str(adapter.SHARED_GPU_LOCK_PATH)],
        [
            "--gpu-lock",
            str(adapter.SHARED_GPU_LOCK_PATH),
            "--gpu-lock",
            "/var/lib/eom-image/gpu0.lock",
        ],
        [
            "--gpu-lock=" + str(adapter.SHARED_GPU_LOCK_PATH),
            "--gpu-lock=" + str(adapter.SHARED_GPU_LOCK_PATH),
        ],
    ],
)
def test_bootstrap_never_selects_legacy_missing_ambiguous_or_duplicate_lock(
    fixed_bootstrap, selection
):
    state, _, events = fixed_bootstrap
    state.argv = ["run_gpu_unit.py", "PROVIDER", "generate-composite", *selection]
    with pytest.raises(SystemExit, match="IMAGE_GPU_UNIT_BOOTSTRAP_INVALID"):
        bootstrap.main()
    assert not events


def test_bootstrap_accepts_one_unambiguous_equals_form_without_rewriting_flags(fixed_bootstrap):
    state, _, events = fixed_bootstrap
    state.argv = [
        "run_gpu_unit.py",
        "PROVIDER",
        "generate-composite",
        "--gpu-lock=" + str(adapter.SHARED_GPU_LOCK_PATH),
    ]
    bootstrap.main()
    assert events[0] == ("BLOCK", signal.SIG_BLOCK, {signal.SIGUSR1})
    assert state.argv[-1] == "--gpu-lock=" + str(adapter.SHARED_GPU_LOCK_PATH)


@pytest.mark.parametrize(
    "invalid",
    [
        "role",
        "prefix",
        "executable",
        "uid",
        "gid",
        "groups",
        "missing_group",
        "isolated",
        "bytecode",
        "platform",
        "preloaded_ml",
        "missing_args",
    ],
)
def test_bootstrap_rejects_invalid_identity_before_signal_or_cli_import(fixed_bootstrap, invalid):
    state, identity, events = fixed_bootstrap
    if invalid == "role":
        state.argv[1] = "arbitrary.module"
    elif invalid == "prefix":
        state.prefix = "/tmp/other-prefix"
    elif invalid == "executable":
        state.executable = "/usr/bin/python"
    elif invalid == "uid":
        identity.uid = (0,) * 3
    elif invalid == "gid":
        identity.gid = (0,) * 3
    elif invalid == "groups":
        identity.groups.append(1000)
    elif invalid == "missing_group":
        identity.groups = [980]
    elif invalid == "isolated":
        state.flags.isolated = 0
    elif invalid == "bytecode":
        state.dont_write_bytecode = False
    elif invalid == "platform":
        state.platform = "other"
    elif invalid == "preloaded_ml":
        state.modules["numpy.core"] = object()
    else:
        state.argv = ["run_gpu_unit.py", "PROVIDER"]
    with pytest.raises(SystemExit, match="IMAGE_GPU_UNIT_BOOTSTRAP_INVALID"):
        bootstrap.main()
    assert not events


@pytest.mark.parametrize("missing", ["user", "group"])
def test_bootstrap_missing_installed_identity_has_stable_error(
    fixed_bootstrap, monkeypatch, missing
):
    _, _, events = fixed_bootstrap

    def absent(name):
        raise KeyError("synthetic missing installed identity")

    if missing == "user":
        monkeypatch.setattr(bootstrap.pwd, "getpwnam", absent)
    else:
        monkeypatch.setattr(bootstrap.grp, "getgrnam", absent)
    with pytest.raises(SystemExit, match="IMAGE_GPU_UNIT_BOOTSTRAP_INVALID"):
        bootstrap.main()
    assert not events
