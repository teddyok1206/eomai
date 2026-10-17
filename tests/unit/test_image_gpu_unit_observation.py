"""Synthetic root unit/kernel read ports; no actual root, signal, CUDA or image run."""

from __future__ import annotations

import shlex
import signal
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_service import image_gpu_unit_observation as owner
from eom_catalog_service.embedding_cuda_probe_resource_observation import ImageUnitGpuResources
from eom_catalog_service.image_gpu_unit_identity import image_gpu_unit_role, image_gpu_unit_template
from eom_identifiers import sha256_bytes

from tests.unit.test_embedding_cuda_installation_evidence import metadata
from tests.unit.test_embedding_native_probe_observation import process_stat, running
from tests.unit.test_embedding_native_probe_observation import terminal as terminal_unit

UNIT = "eom-image-provider@imgreq_" + "a" * 32 + ".service"
TEMPLATE = "eom-image-provider@.service"
BOOTSTRAP = "/usr/local/libexec/eom-image-runtime/run_gpu_unit.py"
EXECUTABLE = "/srv/eom/conda/envs/eom-image/bin/python3.11"
COMMAND = (
    EXECUTABLE,
    "-I",
    "-B",
    BOOTSTRAP,
    "PROVIDER",
    "generate-composite",
    "--request",
    "/srv/eom/image-workspaces/%i/request.json",
    "--gpu-lock",
    "/run/eom-gpu-lease/gpu0.lock",
)


def status(tid, *, reserved=True):
    return (
        f"Pid:\t{tid}\nTgid:\t123\nUid:\t984 984 984 984\nGid:\t980 980 980 980\n"
        "Groups:\t980 2468\nNoNewPrivs:\t1\n"
        + "\n".join(
            f"{name}:\t0000000000000000"
            for name in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")
        )
        + f"\nSigBlk:\t{1 << (signal.SIGUSR1 - 1) if reserved else 0:016x}\n"
    ).encode()


def policy():
    fields = {
        "User": "eom-image",
        "Group": "eom-image",
        "SupplementaryGroups": "eom-gpu-lease",
        "Type": "oneshot",
        "RemainAfterExit": "yes",
        "NotifyAccess": "main",
        "FileDescriptorStoreMax": "1",
        "FileDescriptorStorePreserve": "yes",
        "CollectMode": "inactive",
        "Restart": "no",
        "KillMode": "control-group",
        "NoNewPrivileges": "yes",
        "PrivateNetwork": "yes",
        "PrivateDevices": "no",
        "DevicePolicy": "closed",
        "CapabilityBoundingSet": "",
        "AmbientCapabilities": "",
    }
    devices = (
        "char-rtc r",
        "/dev/nvidia0 rw",
        "/dev/nvidiactl rw",
        "/dev/nvidia-uvm rw",
        "/dev/nvidia-uvm-tools rw",
    )
    return (
        "\n".join(f"{key}={value}" for key, value in fields.items())
        + "\n"
        + "\n".join("DeviceAllow=" + value for value in devices)
        + "\n"
    ).encode()


@pytest.fixture
def image(monkeypatch):
    facts = metadata()["receipt"]
    resources = ImageUnitGpuResources(facts.device_nodes, facts.shared_gpu_lease, 80)
    state = {
        "unit": replace(running(), fragment_path="/etc/systemd/system/" + TEMPLATE),
        "template": ("ExecStart=" + " ".join(COMMAND) + "\n").encode(),
        "bootstrap": b"synthetic root bootstrap",
        "policy": policy(),
        "pids": (123,),
        "tasks": ["123", "124"],
        "gpu_clients": (),
        "start": 987,
        "main_status": status(123),
        "other_status": status(124),
        "changed": False,
        "cgroup": "0::/system.slice/" + UNIT + "\n",
        "resources": resources,
        "executable": Path(EXECUTABLE),
        "reads": [],
        "policy_calls": 0,
        "process_exists": False,
        "cgroup_exists": False,
        "command": b"\0".join(arg.replace("%i", "imgreq_" + "a" * 32).encode() for arg in COMMAND)
        + b"\0",
    }

    class Files:
        def __init__(self, uid):
            assert uid == 0

        def read(self, path, *, sha256, maximum):
            assert path in {Path("/etc/systemd/system") / TEMPLATE, Path(BOOTSTRAP)}
            value = state["bootstrap" if path == Path(BOOTSTRAP) else "template"]
            if sha256 != sha256_bytes(value):
                raise ValueError("synthetic pinned file mismatch")
            assert len(value) <= maximum
            state["reads"].append(path)
            return value

        def assert_unchanged(self):
            if state["changed"]:
                raise ValueError("synthetic captured file drift")

    def read(path, *, maximum, owner_uid):
        assert str(path).startswith("/proc/123/") and owner_uid == 984
        name = str(path.relative_to("/proc/123"))
        if name == "stat":
            return process_stat(123, start=state["start"])
        return {
            "cgroup": state["cgroup"].encode(),
            "status": state["main_status"],
            "cmdline": state["command"],
            "task/123/status": state["main_status"],
            "task/124/status": state["other_status"],
        }[name]

    def command(arguments, **kwargs):
        assert arguments[:3] == ("/usr/bin/systemctl", "show", UNIT)
        assert "kill" not in arguments and "start" not in arguments
        state["policy_calls"] += 1
        return SimpleNamespace(returncode=0, stdout=state["policy"], stderr=b"")

    @contextmanager
    def scan(path):
        assert path == Path("/proc/123/task")
        yield iter(SimpleNamespace(name=name) for name in state["tasks"])

    monkeypatch.setattr(owner, "NumericalRuntimeFileSnapshots", Files)
    monkeypatch.setattr(owner, "os", SimpleNamespace(getresuid=lambda: (0, 0, 0), scandir=scan))
    monkeypatch.setattr(
        owner, "pwd", SimpleNamespace(getpwnam=lambda _: SimpleNamespace(pw_uid=984, pw_gid=980))
    )
    monkeypatch.setattr(
        owner,
        "grp",
        SimpleNamespace(
            getgrnam=lambda name: SimpleNamespace(gr_gid=980 if name == "eom-image" else 2468)
        ),
    )
    monkeypatch.setattr(owner, "inspect_cpu_unit", lambda *args, **kwargs: state["unit"])
    monkeypatch.setattr(owner, "root_owned_unit_processes", lambda _: state["pids"])
    monkeypatch.setattr(owner, "read_live_runtime_os_file", read)
    monkeypatch.setattr(owner, "subprocess", SimpleNamespace(run=command))
    monkeypatch.setattr(owner, "observe_runtime_device", lambda _: None)
    monkeypatch.setattr(owner, "observe_cuda_probe_gpu_clients", lambda _: state["gpu_clients"])
    monkeypatch.setattr(
        owner, "observe_image_unit_gpu_resources", lambda **kwargs: state["resources"]
    )
    monkeypatch.setattr(
        owner,
        "observe_image_unit_gpu_retained_resources",
        lambda resources, **kwargs: (
            resources
            if resources is state["resources"]
            else pytest.fail("unexpected resource frame")
        ),
    )
    original = Path.readlink
    monkeypatch.setattr(
        Path,
        "readlink",
        lambda path: state["executable"] if path == Path("/proc/123/exe") else original(path),
    )
    original_exists = Path.exists
    original_lstat = Path.lstat

    def process_lstat(path, *args, **kwargs):
        if path == Path("/proc/123"):
            if not state["process_exists"]:
                raise FileNotFoundError("synthetic original process ended")
            return SimpleNamespace(st_uid=984)
        return original_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", process_lstat)
    monkeypatch.setattr(
        Path,
        "exists",
        lambda path: (
            state["process_exists"]
            if path == Path("/proc/123")
            else state["cgroup_exists"]
            if path == Path("/sys/fs/cgroup/system.slice") / UNIT
            else original_exists(path)
        ),
    )
    state["device"] = facts.device_capture
    return state


def observe(image, **overrides):
    return owner.observe_image_gpu_unit_ready(
        UNIT,
        template_sha256=overrides.get("template_sha256", sha256_bytes(image["template"])),
        bootstrap_sha256=overrides.get("bootstrap_sha256", sha256_bytes(image["bootstrap"])),
        device=image["device"],
    )


def test_root_readback_binds_process_threads_policy_file_pins_and_actual_resources(image):
    result = observe(image)
    assert result.unit_name == UNIT and result.pid == 123 and result.start_time_ticks == 987
    assert result.thread_ids == (123, 124)
    assert result.resources is image["resources"]
    assert result.worker_uid == 984 and result.worker_gid == 980 and result.lease_gid == 2468
    assert image["policy_calls"] == 2 and len(image["reads"]) == 2
    assert not hasattr(result, "assert_owned") and not hasattr(result, "acknowledge")


@pytest.mark.parametrize(
    "fault",
    [
        "uid",
        "extra_group",
        "capability",
        "no_new_privs",
        "thread_signal_unblocked",
        "wrong_thread_identity",
        "wrong_cmdline",
        "wrong_executable",
        "wrong_cgroup",
        "child_process",
        "no_main_thread",
        "duplicate_thread",
        "invalid_thread",
        "too_many_threads",
        "active_gpu",
        "file_drift",
        "resource_pid",
        "resource_start",
        "resource_gid",
    ],
)
def test_invalid_or_changed_frame_never_yields_ready(image, fault):
    if fault == "uid":
        image["main_status"] = image["main_status"].replace(b"984 984 984 984", b"0 0 0 0")
    elif fault == "extra_group":
        image["main_status"] = image["main_status"].replace(b"980 2468", b"980 2468 1000")
    elif fault == "capability":
        image["main_status"] = image["main_status"].replace(
            b"CapEff:\t0000000000000000", b"CapEff:\t0000000000000001"
        )
    elif fault == "no_new_privs":
        image["main_status"] = image["main_status"].replace(b"NoNewPrivs:\t1", b"NoNewPrivs:\t0")
    elif fault == "thread_signal_unblocked":
        image["other_status"] = status(124, reserved=False)
    elif fault == "wrong_thread_identity":
        image["other_status"] = status(125)
    elif fault == "wrong_cmdline":
        image["command"] = image["command"].replace(b"-I\0", b"-i\0")
    elif fault == "wrong_executable":
        image["executable"] = Path("/tmp/python3.11")
    elif fault == "wrong_cgroup":
        image["cgroup"] = "0::/system.slice/other.service\n"
    elif fault == "child_process":
        image["pids"] = (123, 500)
    elif fault == "no_main_thread":
        image["tasks"] = ["124"]
    elif fault == "duplicate_thread":
        image["tasks"] = ["123", "123"]
    elif fault == "invalid_thread":
        image["tasks"] = ["../123"]
    elif fault == "too_many_threads":
        image["tasks"] = ["123"] * 513
    elif fault == "active_gpu":
        image["gpu_clients"] = (500,)
    elif fault == "file_drift":
        image["changed"] = True
    else:
        field = {
            "resource_pid": "holder_pid",
            "resource_start": "holder_start_time_ticks",
            "resource_gid": "lease_gid",
        }[fault]
        lease = image["resources"].shared_gpu_lease
        image["resources"] = replace(
            image["resources"],
            shared_gpu_lease=lease.model_copy(update={field: getattr(lease, field) + 1}),
        )
    with pytest.raises(ValueError):
        observe(image)


@pytest.mark.parametrize("key", ["template_sha256", "bootstrap_sha256"])
def test_wrong_pinned_file_hash_does_not_fall_back_to_current(image, key):
    with pytest.raises(ValueError, match="mismatch"):
        observe(image, **{key: "sha256:" + "f" * 64})


@pytest.mark.parametrize(
    "field,value",
    [
        ("DevicePolicy", "auto"),
        ("RemainAfterExit", "no"),
        ("NotifyAccess", "all"),
        ("FileDescriptorStoreMax", "0"),
        ("FileDescriptorStorePreserve", "no"),
        ("SupplementaryGroups", "eom"),
        ("Restart", "always"),
        ("KillMode", "process"),
        ("CapabilityBoundingSet", "cap_sys_admin"),
        ("PrivateNetwork", "no"),
    ],
)
def test_effective_policy_cannot_be_widened_or_lose_cleanup_fence(image, field, value):
    lines = image["policy"].decode().splitlines()
    image["policy"] = (
        "\n".join(field + "=" + value if line.startswith(field + "=") else line for line in lines)
        + "\n"
    ).encode()
    with pytest.raises(ValueError, match="POLICY_INVALID"):
        observe(image)


@pytest.mark.parametrize(
    "unit",
    [
        "eom-image-unreviewed@x.service",
        "eom-image-provider@.service",
        "eom-image-provider@../x.service",
        "eom-image-provider@a.b.service",
        "../other.service",
        "eom-image-provider@x@x.service",
        "eom-image-provider@" + "a" * 161 + ".service",
    ],
)
def test_unit_identity_is_closed_and_cannot_be_a_path_or_implicit_new_role(unit):
    with pytest.raises(ValueError, match="IDENTITY_INVALID"):
        image_gpu_unit_template(unit)


def test_nonroot_cannot_read_image_ready_frame(image, monkeypatch):
    monkeypatch.setattr(owner.os, "getresuid", lambda: (1000, 1000, 1000))
    with pytest.raises(ValueError, match="OWNER_REQUIRED"):
        observe(image)
    assert not image["reads"]


def test_three_actual_cli_prefix_bindings_have_explicit_roles():
    assert image_gpu_unit_role(UNIT) == "PROVIDER"
    assert image_gpu_unit_role("eom-image-trainer@x.service") == "TRAINER"
    assert (
        image_gpu_unit_role("eom-image-informative-lineart-extraction@x.service")
        == "PROVIDER_IN_TRAINER"
    )


def test_all_source_gpu_execution_bindings_match_closed_root_unit_roles():
    root = Path(__file__).resolve().parents[2] / "infra/systemd"
    roles = {
        "PROVIDER": "/srv/eom/conda/envs/eom-image/bin/python3.11",
        "PROVIDER_IN_TRAINER": "/srv/eom/conda/envs/eom-image-trainer/bin/python3.11",
        "TRAINER": "/srv/eom/conda/envs/eom-image-trainer/bin/python3.11",
    }
    checked = set()
    for path in root.glob("eom-image-*.service"):
        lines = path.read_text().splitlines()
        if not any(line.startswith("DeviceAllow=") and "nvidia" in line for line in lines):
            continue
        commands = [
            line.removeprefix("ExecStart=") for line in lines if line.startswith("ExecStart=")
        ]
        assert len(commands) == 1
        arguments = shlex.split(commands[0])
        if path.name == "eom-image-gpu-lifetime@.service":
            assert "User=root" in lines
            assert arguments == [
                "/opt/eom/conda/envs/eom-embedding-experiment/bin/python3.12",
                "-I",
                "-B",
                "/usr/local/libexec/eom-image-runtime/watch_gpu_guard.py",
                "%I",
            ]
            continue
        assert arguments[4] in roles and arguments[0] == roles[arguments[4]], path.name
        assert arguments[1:4] == [
            "-I",
            "-B",
            "/usr/local/libexec/eom-image-runtime/run_gpu_unit.py",
        ]
        assert image_gpu_unit_role(path.name.replace("@.service", "@x.service")) == arguments[4]
        checked.add(path.name)
    assert len(checked) == 19


@pytest.mark.parametrize("outcome", ["SUCCEEDED", "FAILED", "TIMEOUT"])
def test_terminal_read_keeps_original_success_failure_and_timeout_history(image, outcome):
    ready = observe(image)
    image["pids"] = ()
    terminal = replace(terminal_unit(), fragment_path="/etc/systemd/system/" + TEMPLATE)
    if outcome != "SUCCEEDED":
        terminal = replace(
            terminal,
            status=replace(
                terminal.status,
                active_state="failed",
                sub_state="failed",
                result="timeout" if outcome == "TIMEOUT" else "exit-code",
                exec_main_status=15 if outcome == "TIMEOUT" else 1,
            ),
        )
    image["unit"] = terminal
    result = owner.verify_image_gpu_unit_terminal(ready)
    assert result.terminal_unit == terminal
    assert result.original_outcome == ("SUCCEEDED" if outcome == "SUCCEEDED" else "FAILED")
    assert result.terminated_at_utc.endswith("Z")
    assert result.ready == ready


@pytest.mark.parametrize(
    "fault",
    [
        "running",
        "invocation",
        "process",
        "child",
        "gpu",
        "policy",
        "file",
        "missing_tree_exists",
        "unknown_result",
        "start_time",
    ],
)
def test_terminal_unknown_or_incomplete_cleanup_never_authorizes_retirement(
    image, monkeypatch, fault
):
    ready = observe(image)
    image["pids"] = ()
    image["unit"] = replace(terminal_unit(), fragment_path="/etc/systemd/system/" + TEMPLATE)
    if fault == "running":
        image["unit"] = ready.unit
    elif fault == "invocation":
        image["unit"] = replace(image["unit"], invocation_id="f" * 32)
    elif fault == "process":
        image["process_exists"] = True
    elif fault == "child":
        image["pids"] = (500,)
    elif fault == "gpu":
        image["gpu_clients"] = (500,)
    elif fault == "policy":
        image["policy"] = image["policy"].replace(b"Restart=no", b"Restart=always")
    elif fault == "file":
        image["changed"] = True
    elif fault == "unknown_result":
        image["unit"] = replace(
            image["unit"],
            status=replace(
                image["unit"].status,
                active_state="failed",
                sub_state="failed",
                result="unrecognized-future-state",
                exec_main_status=1,
            ),
        )
    elif fault == "start_time":
        image["unit"] = replace(
            image["unit"], status=replace(image["unit"].status, exec_main_started_monotonic=101)
        )
    else:
        image["cgroup_exists"] = True

        def missing(unit):
            raise FileNotFoundError("synthetic conflicting cgroup observation")

        monkeypatch.setattr(owner, "root_owned_unit_processes", missing)
    with pytest.raises(ValueError):
        owner.verify_image_gpu_unit_terminal(ready)


def test_missing_terminal_cgroup_is_allowed_only_with_confirmed_absent_tree(image, monkeypatch):
    ready = observe(image)
    image["unit"] = replace(terminal_unit(), fragment_path="/etc/systemd/system/" + TEMPLATE)

    def missing(unit):
        raise FileNotFoundError("synthetic removed terminal cgroup")

    monkeypatch.setattr(owner, "root_owned_unit_processes", missing)
    assert owner.verify_image_gpu_unit_terminal(ready).original_outcome == "SUCCEEDED"


def test_terminal_recovery_does_not_confuse_reused_pid_number_with_original_process(image):
    ready = observe(image)
    image["unit"] = replace(terminal_unit(), fragment_path="/etc/systemd/system/" + TEMPLATE)
    image["pids"] = ()
    image["process_exists"] = True
    image["start"] = ready.start_time_ticks + 1
    assert owner.verify_image_gpu_unit_terminal(ready).original_outcome == "SUCCEEDED"


def test_unleased_exit_does_not_claim_ready_or_require_another_gpu_holder_idle(image, monkeypatch):
    ended = replace(terminal_unit(), fragment_path="/etc/systemd/system/" + TEMPLATE)
    image["unit"], image["pids"] = ended, ()
    monkeypatch.setattr(owner, "image_gpu_unit_descriptor_count", lambda _: 0)

    def forbidden(*args, **kwargs):
        pytest.fail("a no-lease exit must not touch/query another physical GPU holder")

    monkeypatch.setattr(owner, "observe_runtime_device", forbidden)
    monkeypatch.setattr(owner, "observe_cuda_probe_gpu_clients", forbidden)
    monkeypatch.setattr(owner, "observe_image_unit_gpu_resources", forbidden)
    result = owner.observe_unleased_image_gpu_unit_terminal(
        UNIT,
        template_sha256=sha256_bytes(image["template"]),
        bootstrap_sha256=sha256_bytes(image["bootstrap"]),
        expected_unit=ended,
    )
    assert result.terminal_unit == ended and result.original_outcome == "SUCCEEDED"
    assert not hasattr(result, "ready") and not hasattr(result, "resources")


@pytest.mark.parametrize("fault", ("store", "child", "invocation", "source", "policy"))
def test_unleased_exit_requires_exact_empty_store_cgroup_source_and_terminal(
    image, monkeypatch, fault
):
    ended = replace(terminal_unit(), fragment_path="/etc/systemd/system/" + TEMPLATE)
    image["unit"], image["pids"] = ended, ()
    monkeypatch.setattr(
        owner, "image_gpu_unit_descriptor_count", lambda _: 1 if fault == "store" else 0
    )
    if fault == "child":
        image["pids"] = (500,)
    elif fault == "invocation":
        image["unit"] = replace(ended, invocation_id="f" * 32)
    elif fault == "source":
        image["changed"] = True
    elif fault == "policy":
        image["policy"] = image["policy"].replace(b"Restart=no", b"Restart=always")
    with pytest.raises(ValueError):
        owner.observe_unleased_image_gpu_unit_terminal(
            UNIT,
            template_sha256=sha256_bytes(image["template"]),
            bootstrap_sha256=sha256_bytes(image["bootstrap"]),
            expected_unit=ended,
        )


@pytest.mark.parametrize("raw,expected", ((b"0\n", 0), (b"1\n", 1)))
def test_root_descriptor_count_uses_only_fixed_bounded_systemctl_read(
    image, monkeypatch, raw, expected
):
    calls = []

    def command(arguments, **kwargs):
        calls.append(arguments)
        return SimpleNamespace(returncode=0, stdout=raw, stderr=b"")

    monkeypatch.setattr(owner.subprocess, "run", command)
    assert owner.image_gpu_unit_descriptor_count(UNIT) == expected
    assert calls == [
        ("/usr/bin/systemctl", "show", UNIT, "--property=NFileDescriptorStore", "--value")
    ]


@pytest.mark.parametrize("raw", (b"2\n", b"1\n0\n", b"1", b"-1\n", b"garbage\n"))
def test_descriptor_count_rejects_unknown_or_multiple_retained_handles(image, monkeypatch, raw):
    monkeypatch.setattr(
        owner.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=raw, stderr=b""),
    )
    with pytest.raises(ValueError, match="STORE_UNAVAILABLE"):
        owner.image_gpu_unit_descriptor_count(UNIT)
