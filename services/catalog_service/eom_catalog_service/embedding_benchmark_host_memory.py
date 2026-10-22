"""Read-only own-benchmark-unit host OOM observation, not admission or cleanup proof."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Literal

from eom_catalog_contracts.embedding_device_benchmark import BenchmarkExecutionPolicy

from eom_catalog_service.embedding_benchmark_unit_policy import benchmark_unit_family
from eom_catalog_service.embedding_execution_ports import BenchmarkHostObservationError
from eom_catalog_service.embedding_runtime_files import read_live_runtime_os_file

_CGROUP_ROOT = Path("/sys/fs/cgroup")
_MAX_COUNTER = 2**64 - 1
_REQUIRED_COUNTERS = frozenset({"low", "high", "max", "oom", "oom_kill"})


def _require(condition: bool, code: str = "BENCHMARK_HOST_OBSERVATION_INVALID") -> None:
    if not condition:
        raise BenchmarkHostObservationError(code)


def _counters(raw: bytes) -> dict[str, int]:
    _require(type(raw) is bytes and 0 < len(raw) <= 4096 and raw.endswith(b"\n"))
    values: dict[str, int] = {}
    for line in raw.splitlines():
        pair = line.split(b" ")
        _require(
            len(pair) == 2
            and re.fullmatch(rb"[a-z_]{1,64}", pair[0]) is not None
            and re.fullmatch(rb"0|[1-9][0-9]{0,19}", pair[1]) is not None
        )
        key, value = pair[0].decode("ascii"), int(pair[1])
        _require(key not in values and value <= _MAX_COUNTER and len(values) < 32)
        values[key] = value
    _require(values.keys() >= _REQUIRED_COUNTERS)
    return values


def _mount_identity(raw: bytes) -> tuple[str, ...]:
    _require(type(raw) is bytes and 0 < len(raw) <= 1024**2 and raw.endswith(b"\n"))
    matches = []
    for line in raw.decode("ascii").splitlines():
        left, separator, right = line.partition(" - ")
        fields, filesystem = left.split(), right.split()
        if len(fields) < 5 or fields[4] != str(_CGROUP_ROOT):
            continue
        _require(
            bool(separator)
            and len(fields) >= 6
            and len(filesystem) == 3
            and all(re.fullmatch(r"[1-9][0-9]{0,19}", value) for value in fields[:2])
            and re.fullmatch(r"[0-9]+:[0-9]+", fields[2]) is not None
            and fields[3] == "/"
            and filesystem[0] == "cgroup2"
            and "memory_localevents" not in fields[5].split(",")
            and "memory_localevents" not in filesystem[2].split(",")
        )
        device = _CGROUP_ROOT.lstat().st_dev
        _require(fields[2] == f"{os.major(device)}:{os.minor(device)}")
        matches.append(tuple((*fields, "-", *filesystem)))
    _require(len(matches) == 1)
    return matches[0]


def _node_identity(path: Path) -> tuple[int, ...]:
    value = path.lstat()
    if path.name == "memory.events":
        _require(stat.S_ISREG(value.st_mode) and value.st_nlink == 1)
    else:
        _require(stat.S_ISDIR(value.st_mode))
    # Dynamic counters and child creation may update times; identity, not contents, is pinned.
    return value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode


class OwnBenchmarkHostOomObserver:
    """One process/unit baseline; sequential observations only, without retained open FDs.

    Trusted composition supplies the two small fixed identities before backend entry.
    Kernel/epoch failures poison this instance and require the original owner to reconcile;
    recreating it is not a supported retry. Source/installation/physical lease are external.
    """

    def __init__(
        self,
        *,
        device: Literal["CPU", "CUDA"],
        execution_id: str,
        policy: BenchmarkExecutionPolicy | None = None,
    ) -> None:
        self._failed = True
        try:
            _require(type(device) is str and device in ("CPU", "CUDA"))
            _require(
                type(execution_id) is str
                and re.fullmatch(r"[0-9a-f]{32}", execution_id) is not None
            )
            self._pid, self._uid = os.getpid(), os.geteuid()
            self._proc = Path("/proc") / str(self._pid)
            family = benchmark_unit_family(device, policy)
            unit = family.service_template.replace("@.service", f"@{execution_id}.service")
            self._membership = f"0::/system.slice/{unit}\n".encode("ascii")
            self._events = _CGROUP_ROOT / "system.slice" / unit / "memory.events"
            self._mount = _mount_identity(self._read_proc("mountinfo", maximum=1024**2))
            self._nodes = {
                path: _node_identity(path) for path in (self._events, *self._events.parents)
            }
            self._check_identity()
            self._baseline = self._read_counts()
            self._check_identity()
            self._last = self._baseline
            self._failed = False
        except Exception:
            raise BenchmarkHostObservationError("BENCHMARK_HOST_CAPTURE_INVALID") from None

    def _read_proc(self, member: str, *, maximum: int) -> bytes:
        return read_live_runtime_os_file(self._proc / member, maximum=maximum, owner_uid=self._uid)

    def _check_identity(self) -> None:
        _require((os.getpid(), os.geteuid()) == (self._pid, self._uid))
        _require(self._read_proc("cgroup", maximum=4096) == self._membership)
        _require(_mount_identity(self._read_proc("mountinfo", maximum=1024**2)) == self._mount)
        _require(all(_node_identity(path) == value for path, value in self._nodes.items()))

    def _read_counts(self) -> dict[str, int]:
        return _counters(read_live_runtime_os_file(self._events, maximum=4096))

    def observe_delta(self) -> int:
        try:
            _require(not self._failed, "BENCHMARK_HOST_OBSERVER_POISONED")
            self._check_identity()
            current = self._read_counts()
            self._check_identity()
            _require(
                current.keys() == self._last.keys()
                and all(current[key] >= previous for key, previous in self._last.items()),
                "BENCHMARK_HOST_COUNTER_RESET",
            )
            # Global OOM kills can advance oom_kill while local-limit oom remains unchanged.
            _require(
                all(
                    current.get(key, 0) == self._baseline.get(key, 0)
                    for key in ("oom_kill", "oom_group_kill")
                ),
                "BENCHMARK_HOST_OOM_KILL_DETECTED",
            )
            self._last = current
            return current["oom"] - self._baseline["oom"]
        except Exception as error:
            self._failed = True
            if isinstance(error, BenchmarkHostObservationError):
                raise
            raise BenchmarkHostObservationError("BENCHMARK_HOST_OBSERVATION_INVALID") from None
