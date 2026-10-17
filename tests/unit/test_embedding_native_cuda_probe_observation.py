"""Synthetic root unit/proc/resource ports; not an actual CUDA invocation or ACK."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_native_cuda_probe_observation as owner
from eom_catalog_service.embedding_cuda_probe_resource_observation import (
    CudaProbeResourceObservation,
)
from eom_catalog_service.embedding_native_probe_observation import (
    validate_native_executable_mappings,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes

from tests.unit.test_embedding_cuda_installation_evidence import metadata
from tests.unit.test_embedding_native_cuda_probe import case as case
from tests.unit.test_embedding_native_cuda_probe_ready import ready_case as ready_case
from tests.unit.test_embedding_native_probe_observation import ledger as ledger
from tests.unit.test_embedding_native_probe_observation import maps, process_stat, running
from tests.unit.test_embedding_native_probe_observation import terminal as cpu_terminal

ROOT = Path(__file__).resolve().parents[2]
PREFIX = Path("/opt/eom/conda/envs/eom-embedding-cuda")


def status(ready):
    uids = " ".join([str(ready.worker_uid)] * 4)
    gids = " ".join([str(ready.worker_gid)] * 4)
    return (
        f"Uid:\t{uids}\nGid:\t{gids}\n"
        f"Groups:\t{ready.supplementary_gids[0]}\nNoNewPrivs:\t1\n"
        + "\n".join(
            f"{key}:\t0000000000000000"
            for key in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")
        )
        + "\n"
    ).encode()


@pytest.fixture
def process(monkeypatch, ready_case, ledger):
    _, _, ready, final, _ = ready_case
    inventory, host, _ = ledger
    inventory = replace(inventory, prefix=PREFIX)
    facts = metadata()["receipt"]
    resources = CudaProbeResourceObservation(facts.device_nodes, facts.shared_gpu_lease, 80)
    unit, cgroup = owner._unit(ready.execution_id)
    state = {
        "unit": replace(
            running(), fragment_path="/etc/systemd/system/" + owner.CUDA_PROBE_TEMPLATE
        ),
        "start": ready.start_time_ticks,
        "pids": (ready.pid,),
        "cgroup": cgroup,
        "maps": maps(path=PREFIX / "bin/python3.12"),
        "status": status(ready),
        "cwd_inode": 500,
        "resources": resources,
    }
    monkeypatch.setattr(owner.os, "getresuid", lambda: (0, 0, 0))
    monkeypatch.setattr(
        owner,
        "require_native_cuda_probe_unit",
        lambda: (ready.worker_uid, ready.worker_gid, ready.supplementary_gids[0]),
    )
    monkeypatch.setattr(owner, "inspect_cpu_unit", lambda *_a, **_kw: state["unit"])
    monkeypatch.setattr(owner, "native_probe_cgroup_members", lambda _: state["pids"])
    monkeypatch.setattr(owner, "observe_runtime_device", lambda _: None)
    monkeypatch.setattr(
        owner, "observe_cuda_probe_resources", lambda *_a, **_kw: state["resources"]
    )

    def read(path, *, maximum, owner_uid):
        assert path.parent == Path("/proc/123") and owner_uid == ready.worker_uid
        return {
            "stat": process_stat(ready.pid, start=state["start"]),
            "cgroup": f"0::{state['cgroup']}\n".encode(),
            "status": state["status"],
            "maps": state["maps"],
        }[path.name]

    original_lstat, original_stat = Path.lstat, Path.stat

    def lstat(path, *args, **kwargs):
        if path == owner.CUDA_LOADER_EMPTY_DIRECTORY:
            return SimpleNamespace(st_dev=1, st_ino=500)
        return original_lstat(path, *args, **kwargs)

    def stat(path, *args, **kwargs):
        if path == Path("/proc/123/cwd"):
            return SimpleNamespace(st_dev=1, st_ino=state["cwd_inode"])
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(owner, "read_live_runtime_os_file", read)
    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(Path, "stat", stat)
    return ready, final, inventory, host, state, unit


def observe(process, final=False):
    ready, result, inventory, host, *_ = process
    return owner.observe_native_cuda_probe_process(
        result if final else ready, inventory=inventory, host=host
    )


def test_template_is_fixed_without_installing_or_starting_and_has_bounded_fdstore():
    raw = (ROOT / "infra/systemd" / owner.CUDA_PROBE_TEMPLATE).read_bytes()
    assert sha256_bytes(raw) == owner.CUDA_PROBE_TEMPLATE_SHA256
    text = raw.decode()
    required = {
        "Type=oneshot",
        "RemainAfterExit=yes",
        "CollectMode=inactive",
        "Restart=no",
        "FileDescriptorStoreMax=1",
        "FileDescriptorStorePreserve=yes",
        "NotifyAccess=main",
        "SupplementaryGroups=eom-gpu-lease",
        "PrivateNetwork=yes",
        "DevicePolicy=closed",
        "CapabilityBoundingSet=",
        "AmbientCapabilities=",
        "NoNewPrivileges=yes",
        "PrivateDevices=no",
        "WorkingDirectory=/opt/eom/embedding-cuda-loader-empty",
        "DeviceAllow=/dev/nvidia0 rw",
        "DeviceAllow=/dev/nvidiactl rw",
        "DeviceAllow=/dev/nvidia-uvm rw",
        "DeviceAllow=/dev/nvidia-uvm-tools rw",
        "StandardError=file:/run/eom-embedding-native-cuda-probe/%i/ready.json",
    }
    assert required <= set(text.splitlines())
    assert "StandardOutput=journal" not in text and "ExecStop" not in text
    assert "EnvironmentFile=" not in text and "--gpu-lock" not in text


def test_two_actual_observations_and_phase_specific_signals_share_existing_map_algorithm(
    process, monkeypatch
):
    ready, final, inventory, host, _state, unit = process
    prepared = observe(process)
    finished = observe(process, final=True)
    assert prepared.phase == "READY" and finished.phase == "FINAL"
    assert prepared.report_sha256 != finished.report_sha256
    assert prepared.loaded_members_sha256 == finished.loaded_members_sha256
    commands = []
    monkeypatch.setattr(
        owner.subprocess,
        "run",
        lambda args, **kw: commands.append(args) or SimpleNamespace(returncode=0),
    )
    owner.acknowledge_native_cuda_probe_ready(prepared, ready, inventory=inventory, host=host)
    owner.acknowledge_native_cuda_probe_final(
        prepared, finished, final, inventory=inventory, host=host
    )
    assert [cmd[-2:] for cmd in commands] == [
        ("--signal=SIGUSR1", unit),
        ("--signal=SIGUSR2", unit),
    ]
    assert all(
        cmd[:4] == ("/usr/bin/systemctl", "--no-ask-password", "kill", "--kill-whom=main")
        for cmd in commands
    )


@pytest.mark.parametrize(
    "fault", ["start", "pid", "unit", "cgroup", "pids", "cwd", "identity", "maps"]
)
def test_wrong_or_changed_process_prevents_first_ack(process, monkeypatch, fault):
    ready, _final, inventory, host, state, _ = process
    observed = observe(process)
    if fault == "start":
        state["start"] += 1
    elif fault == "pid":
        state["unit"] = replace(state["unit"], main_pid=124)
    elif fault == "unit":
        state["unit"] = replace(state["unit"], invocation_id="c" * 32)
    elif fault == "cgroup":
        state["cgroup"] = "/other"
    elif fault == "pids":
        state["pids"] = (123, 124)
    elif fault == "cwd":
        state["cwd_inode"] += 1
    elif fault == "identity":
        state["status"] = state["status"].replace(b"NoNewPrivs:\t1", b"NoNewPrivs:\t0")
    else:
        state["maps"] = maps(path=Path("/outside/unknown.so"))
    monkeypatch.setattr(
        owner.subprocess,
        "run",
        lambda *_a, **_kw: pytest.fail("changed observation must not signal"),
    )
    with pytest.raises(ValueError):
        owner.acknowledge_native_cuda_probe_ready(observed, ready, inventory=inventory, host=host)


@pytest.mark.parametrize(
    "field,value",
    [
        ("invocation_id", "c" * 32),
        ("pid", 124),
        ("start_time_ticks", 988),
        ("cgroup", "/other"),
        ("execution_id", "c" * 32),
    ],
)
def test_final_ack_cannot_skip_or_replace_the_original_ready_observation(
    process, monkeypatch, field, value
):
    ready = observe(process)
    finished = replace(observe(process, final=True), **{field: value})
    _, report, inventory, host, *_ = process
    monkeypatch.setattr(
        owner.subprocess, "run", lambda *_a, **_kw: pytest.fail("must not acknowledge")
    )
    with pytest.raises(ValueError):
        owner.acknowledge_native_cuda_probe_final(
            ready, finished, report, inventory=inventory, host=host
        )


def test_cuda_mapping_path_does_not_broaden_the_cpu_prefix_wrapper(process):
    _r, _f, inventory, host, state, _ = process
    assert observe(process).pid == 123
    with pytest.raises(ValueError, match="PREFIX_INVALID"):
        validate_native_executable_mappings(state["maps"], inventory=inventory, host=host)


def test_missing_ack_result_is_uncertain_not_automatic_replay(process, monkeypatch):
    ready, _, inventory, host, *_ = process
    observed = observe(process)
    calls = []
    monkeypatch.setattr(
        owner.subprocess,
        "run",
        lambda args, **kw: calls.append(args) or SimpleNamespace(returncode=1),
    )
    with pytest.raises(ValueError, match="ACK_UNCERTAIN"):
        owner.acknowledge_native_cuda_probe_ready(observed, ready, inventory=inventory, host=host)
    assert len(calls) == 1


def test_phase_mismatch_never_emits_a_signal(process, monkeypatch):
    ready_report, final_report, inventory, host, *_ = process
    ready, final = observe(process), observe(process, final=True)
    monkeypatch.setattr(
        owner.subprocess, "run", lambda *_a, **_kw: pytest.fail("must not signal wrong phase")
    )
    with pytest.raises(ValueError, match="PHASE_INVALID"):
        owner.acknowledge_native_cuda_probe_ready(
            final, ready_report, inventory=inventory, host=host
        )
    with pytest.raises(ValueError, match="PHASE_INVALID"):
        owner.acknowledge_native_cuda_probe_final(
            final, ready, final_report, inventory=inventory, host=host
        )


@pytest.mark.parametrize(
    "fault",
    [
        "uid",
        "gid",
        "missing_lease",
        "extra_group",
        "duplicate_group",
        "capability",
        "new_privileges",
        "duplicate_field",
        "missing_field",
    ],
)
def test_independent_status_does_not_trust_reported_identity(ready_case, fault):
    ready = ready_case[2]
    raw = status(ready)
    if fault in {"uid", "gid"}:
        key = b"Uid:" if fault == "uid" else b"Gid:"
        raw = b"\n".join(
            key + b"\t0 0 0 0" if line.startswith(key) else line for line in raw.splitlines()
        )
    elif fault == "missing_lease":
        raw = raw.replace(f"Groups:\t{ready.supplementary_gids[0]}".encode(), b"Groups:\t")
    elif fault == "extra_group":
        raw = raw.replace(b"Groups:\t", b"Groups:\t0 ")
    elif fault == "duplicate_group":
        raw = raw.replace(b"Groups:\t", f"Groups:\t{ready.supplementary_gids[0]} ".encode())
    elif fault == "capability":
        raw = raw.replace(b"CapEff:\t0000000000000000", b"CapEff:\t0000000000000001")
    elif fault == "new_privileges":
        raw = raw.replace(b"NoNewPrivs:\t1", b"NoNewPrivs:\t0")
    elif fault == "duplicate_field":
        raw += b"Uid:\t0 0 0 0\n"
    else:
        raw = raw.replace(b"CapBnd:\t0000000000000000\n", b"")
    with pytest.raises(ValueError, match="PROCESS_IDENTITY_INVALID"):
        owner._require_status(
            raw, uid=ready.worker_uid, gid=ready.worker_gid, lease_gid=ready.supplementary_gids[0]
        )


@pytest.mark.parametrize(
    "fault", [None, "root_user", "wrong_primary", "extra_group", "same_lease_group"]
)
def test_account_and_template_are_observed_from_installed_root_inputs(monkeypatch, fault):
    calls = []

    class Files:
        def __init__(self, uid):
            assert uid == 0

        def read(self, path, **kwargs):
            assert path == Path("/etc/systemd/system") / owner.CUDA_PROBE_TEMPLATE
            assert kwargs["sha256"] == owner.CUDA_PROBE_TEMPLATE_SHA256
            calls.append("unit")

        def observe_empty_directory(self, path):
            assert path == owner.CUDA_LOADER_EMPTY_DIRECTORY
            calls.append("cwd")

        def assert_unchanged(self):
            calls.append("current")

    uid, gid, lease_gid = 3456, 3456, 2468
    user = SimpleNamespace(
        pw_uid=0 if fault == "root_user" else uid,
        pw_gid=0 if fault == "wrong_primary" else gid,
        pw_name="eom-embedding-cuda",
    )
    monkeypatch.setattr(owner.os, "getresuid", lambda: (0, 0, 0))
    monkeypatch.setattr(owner, "NumericalRuntimeFileSnapshots", Files)
    monkeypatch.setattr(owner.pwd, "getpwnam", lambda _: user)
    monkeypatch.setattr(
        owner.grp,
        "getgrnam",
        lambda name: SimpleNamespace(
            gr_gid=(gid if fault == "same_lease_group" else lease_gid)
            if name == "eom-gpu-lease"
            else gid
        ),
    )
    monkeypatch.setattr(
        owner.os,
        "getgrouplist",
        lambda *_: [gid, lease_gid, *([0] if fault == "extra_group" else [])],
    )
    if fault:
        with pytest.raises(ValueError, match="ACCOUNT_INVALID"):
            owner.require_native_cuda_probe_unit()
    else:
        assert owner.require_native_cuda_probe_unit() == (uid, gid, lease_gid)
        assert calls == ["unit", "cwd", "current"]


@pytest.fixture
def ended(process, monkeypatch):
    return end_process(process, monkeypatch, observe(process, final=True))


def end_process(process, monkeypatch, observed):
    from eom_catalog_service import embedding_cuda_probe_gpu_clients as clients

    state = process[4]
    state["unit"] = replace(cpu_terminal(), fragment_path=state["unit"].fragment_path)
    state["pids"] = ()
    state["gpu_pids"] = ()
    events = []

    def retained(resources, *, unit):
        assert resources == observed.resources and unit == process[-1]
        events.append("retained")
        return resources

    def gpu(expected):
        assert expected == process[1].device_capture
        events.append("gpu")
        return state["gpu_pids"]

    monkeypatch.setattr(owner, "observe_cuda_probe_retained_resources", retained)
    monkeypatch.setattr(clients, "observe_cuda_probe_gpu_clients", gpu)
    monkeypatch.setattr(
        owner.subprocess,
        "run",
        lambda *_a, **_kw: pytest.fail("terminal observation must not mutate any unit"),
    )
    return process, observed, state, events


def test_terminal_requires_unit_cgroup_gpu_and_two_retained_fences_but_not_global_idle(ended):
    process, observed, state, events = ended
    state["gpu_pids"] = (203, 999)  # Other normal clients are not this completed probe.
    result = owner.verify_native_cuda_probe_terminal(observed, process[1])
    assert result.final_observation is observed and result.terminal_unit.succeeded
    assert result.terminal_probe_gpu_client_count == 0 and result.terminated_at_utc.endswith("Z")
    assert events == ["retained", "gpu", "retained"]


@pytest.mark.parametrize(
    "fault", ("running", "failed", "invocation", "cgroup", "probe_gpu", "report")
)
def test_unknown_or_remaining_work_cannot_be_terminal_success(ended, fault):
    process, observed, state, _ = ended
    report = process[1]
    if fault == "running":
        state["unit"] = replace(state["unit"], main_pid=123)
    elif fault == "failed":
        state["unit"] = replace(
            state["unit"], status=replace(state["unit"].status, result="signal", exec_main_status=9)
        )
    elif fault == "invocation":
        state["unit"] = replace(state["unit"], invocation_id="c" * 32)
    elif fault == "cgroup":
        state["pids"] = (123,)
    elif fault == "probe_gpu":
        state["gpu_pids"] = (123,)
    else:
        report = type(report).model_validate(
            report.model_dump(mode="json")
            | {"checked_model_members": report.checked_model_members + 1}
        )
    with pytest.raises(ValueError):
        owner.verify_native_cuda_probe_terminal(observed, report)


def test_known_terminal_unit_may_have_an_already_removed_empty_cgroup(ended, monkeypatch):
    process, observed, _, _ = ended

    def absent(_):
        raise FileNotFoundError("synthetic already-removed cgroup")

    monkeypatch.setattr(owner, "native_probe_cgroup_members", absent)
    assert owner.verify_native_cuda_probe_terminal(observed, process[1]).terminal_unit.succeeded


@pytest.fixture
def failed_ended(process, monkeypatch):
    observed = observe(process)
    result = end_process(process, monkeypatch, observed)
    state = process[4]
    state["unit"] = replace(
        state["unit"],
        status=replace(
            state["unit"].status,
            active_state="failed",
            sub_state="failed",
            result="exit-code",
            exec_main_status=1,
        ),
    )
    state["proc_exists"] = False
    original_exists = Path.exists

    def exists(path, *args, **kwargs):
        if path == Path("/proc/123"):
            return state["proc_exists"]
        return original_exists(path, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", exists)
    return result


def test_failed_terminal_preserves_failure_and_ready_without_seal_or_release(failed_ended):
    process, observed, state, events = failed_ended
    state["gpu_pids"] = (203, 999)
    result = owner.verify_native_cuda_probe_failed_terminal(observed, process[0])
    assert type(result) is owner.NativeCudaProbeFailedTerminalObservation
    assert not isinstance(result, owner.NativeCudaProbeTerminalObservation)
    assert result.ready_observation is observed
    assert result.failed_unit.failed and not result.failed_unit.succeeded
    assert result.observed_at_utc.endswith("Z")
    assert result.terminal_probe_gpu_client_count == 0
    assert events == ["retained", "gpu", "retained"]


@pytest.mark.parametrize(
    "fault",
    (
        "owner",
        "running",
        "successful",
        "invocation",
        "cgroup",
        "process",
        "probe_gpu",
        "report",
        "phase",
        "execution",
        "pid",
        "start",
        "account",
        "observed_cgroup",
    ),
)
def test_failed_terminal_rejects_changed_or_unfinished_identity(failed_ended, monkeypatch, fault):
    process, observed, state, _ = failed_ended
    report = process[0]
    if fault == "owner":
        monkeypatch.setattr(owner.os, "getresuid", lambda: (1000, 1000, 1000))
    elif fault == "running":
        state["unit"] = replace(state["unit"], main_pid=123)
    elif fault == "successful":
        state["unit"] = replace(cpu_terminal(), fragment_path=state["unit"].fragment_path)
    elif fault == "invocation":
        state["unit"] = replace(state["unit"], invocation_id="c" * 32)
    elif fault == "cgroup":
        state["pids"] = (123,)
    elif fault == "process":
        state["proc_exists"] = True
    elif fault == "probe_gpu":
        state["gpu_pids"] = (123,)
    elif fault == "report":
        observed = replace(observed, report_sha256="sha256:" + "0" * 64)
    elif fault == "phase":
        observed = replace(observed, phase="FINAL")
    elif fault == "execution":
        observed = replace(observed, execution_id="c" * 32)
    elif fault == "pid":
        observed = replace(observed, pid=124)
    elif fault == "start":
        observed = replace(observed, start_time_ticks=observed.start_time_ticks + 1)
    elif fault == "account":
        monkeypatch.setattr(owner, "require_native_cuda_probe_unit", lambda: (1, 2, 3))
    else:
        observed = replace(observed, cgroup="/other")
    with pytest.raises(ValueError):
        owner.verify_native_cuda_probe_failed_terminal(observed, report)


def test_rejected_final_report_cannot_become_failed_terminal_authority(failed_ended):
    process, observed, _, _ = failed_ended
    with pytest.raises(ValueError, match="PHASE_INVALID"):
        owner.verify_native_cuda_probe_failed_terminal(observed, process[1])


def test_failed_terminal_detects_unit_change_during_gpu_observation(failed_ended, monkeypatch):
    from eom_catalog_service import embedding_cuda_probe_gpu_clients as clients

    process, observed, state, _ = failed_ended

    def changed(_):
        state["unit"] = replace(state["unit"], invocation_id="c" * 32)
        return ()

    monkeypatch.setattr(clients, "observe_cuda_probe_gpu_clients", changed)
    with pytest.raises(ValueError, match="TERMINATION_UNCERTAIN"):
        owner.verify_native_cuda_probe_failed_terminal(observed, process[0])


def test_failed_terminal_does_not_swallow_lost_fencing(failed_ended, monkeypatch):
    process, observed, _, _ = failed_ended

    def lost(*_args, **_kwargs):
        raise ValueError("NATIVE_CUDA_PROBE_RESOURCE_OBSERVATION_INVALID")

    monkeypatch.setattr(owner, "observe_cuda_probe_retained_resources", lost)
    with pytest.raises(ValueError, match="RESOURCE_OBSERVATION_INVALID"):
        owner.verify_native_cuda_probe_failed_terminal(observed, process[0])


def test_failure_observation_never_satisfies_successful_final_terminal_gate(failed_ended):
    process, observed, _, _ = failed_ended
    forged_final = replace(
        observed, phase="FINAL", report_sha256=sha256_bytes(canonical_json_bytes(process[1]))
    )
    with pytest.raises(ValueError, match="TERMINATION_UNCERTAIN"):
        owner.verify_native_cuda_probe_terminal(forged_final, process[1])
