"""Synthetic protected cgroup tree; no production cgroup mutation or privileged process."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from eom_catalog_service import embedding_native_probe_observation as native
from eom_orchestrator import systemd_unit_processes as reader


@pytest.fixture
def cgroup(tmp_path, monkeypatch):
    root = tmp_path / "system.slice"
    unit = root / "synthetic-unit@x.service"
    unit.mkdir(parents=True)
    unit.chmod(0o755)
    target = unit / "cgroup.procs"
    target.write_bytes(b"123\n456\n")
    protected = {unit, *unit.parents}
    state = {"wrong_owner": False}
    original = Path.lstat

    def lstat(path, *args, **kwargs):
        value = original(path, *args, **kwargs)
        if path not in protected:
            return value
        fields = list(value)
        fields[4] = 1000 if path == unit and state["wrong_owner"] else 0
        if path != unit:
            fields[0] &= ~0o022  # Synthetic protected ancestors, including the private tmp fixture.
        return os.stat_result(fields)

    monkeypatch.setattr(reader, "_ROOT", root)
    monkeypatch.setattr(Path, "lstat", lstat)
    return unit, target, state


def test_bounded_ordered_pid_read_and_empty_terminal_frame(cgroup):
    unit, target, _ = cgroup
    assert reader.root_owned_unit_processes(unit.name) == (123, 456)
    target.write_bytes(b"")
    assert reader.root_owned_unit_processes(unit.name) == ()


@pytest.mark.parametrize(
    "raw",
    [
        b"123\n123\n",
        b"0\n",
        b"-1\n",
        b"1 \n",
        b"abc\n",
        b"2147483648\n",
        b"9" * 4097,
        b"\n",
        b"\n".join(str(i).encode() for i in range(1, 66)),
    ],
)
def test_invalid_duplicate_oversized_or_out_of_range_processes_fail(cgroup, raw):
    unit, target, _ = cgroup
    target.write_bytes(raw)
    with pytest.raises(reader.UnitProcessObservationError, match="INVALID"):
        reader.root_owned_unit_processes(unit.name)


@pytest.mark.parametrize("fault", ["owner", "writable", "nested", "symlink"])
def test_cgroup_tree_cannot_be_worker_owned_writable_nested_or_symlinked(cgroup, fault):
    unit, target, state = cgroup
    if fault == "owner":
        state["wrong_owner"] = True
    elif fault == "writable":
        unit.chmod(0o777)
    elif fault == "nested":
        (unit / "unexpected-child").mkdir()
    else:
        target.rename(unit / "original")
        target.symlink_to(unit / "original")
    with pytest.raises((ValueError, OSError)):
        reader.root_owned_unit_processes(unit.name)


@pytest.mark.parametrize(
    "unit",
    [
        "../synthetic-unit@x.service",
        "/tmp/x.service",
        "x\n.service",
        "x.service/child",
        "x",
        "a" * 256,
        "x\x00.service",
    ],
)
def test_unit_name_never_becomes_an_arbitrary_path(unit):
    with pytest.raises(reader.UnitProcessObservationError, match="INVALID"):
        reader.root_owned_unit_processes(unit)


def test_missing_known_tree_is_not_terminal_success_or_automatic_recreation(cgroup):
    unit, _, _ = cgroup
    with pytest.raises(FileNotFoundError):
        reader.root_owned_unit_processes("missing@x.service")
    assert not (unit.parent / "missing@x.service").exists()


@pytest.mark.parametrize("profile", ["cpu", "cuda"])
def test_native_wrapper_keeps_its_strict_identity_and_uses_shared_reader(monkeypatch, profile):
    unit = "eom-embedding-native-" + profile + "-probe@" + "a" * 32 + ".service"
    calls = []
    monkeypatch.setattr(
        native, "root_owned_unit_processes", lambda name: calls.append(name) or (123,)
    )
    assert native.native_probe_cgroup_members("/system.slice/" + unit) == (123,)
    assert calls == [unit]
    with pytest.raises(ValueError, match="CGROUP_INVALID"):
        native.native_probe_cgroup_members("/system.slice/eom-image-provider@x.service")
    assert calls == [unit]


@pytest.mark.parametrize(
    "code,label", [("INVALID", "CGROUP_INVALID"), ("NESTED_CGROUP", "NESTED_CGROUP")]
)
def test_native_wrapper_keeps_existing_error_labels(monkeypatch, code, label):
    def failure(unit):
        raise reader.UnitProcessObservationError(code)

    monkeypatch.setattr(native, "root_owned_unit_processes", failure)
    with pytest.raises(ValueError, match="NATIVE_CPU_PROBE_" + label):
        native.native_probe_cgroup_members(
            "/system.slice/eom-embedding-native-cuda-probe@" + "a" * 32 + ".service"
        )


def test_native_wrapper_keeps_missing_tree_explicit_for_terminal_owner(monkeypatch):
    def missing(unit):
        raise FileNotFoundError("synthetic retired cgroup")

    monkeypatch.setattr(native, "root_owned_unit_processes", missing)
    with pytest.raises(FileNotFoundError):
        native.native_probe_cgroup_members(
            "/system.slice/eom-embedding-native-cuda-probe@" + "a" * 32 + ".service"
        )
