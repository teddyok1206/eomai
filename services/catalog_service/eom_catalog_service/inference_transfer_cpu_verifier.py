"""Fixed installed CPU negative probe. No model loading, source reads, or publication."""

from __future__ import annotations

import base64
import csv
import errno
import hashlib
import importlib
import importlib.metadata
import io
import json
import os
import pwd
import socket
import stat
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

from eom_catalog_contracts.item_inference_transfer import LocalEmbeddingModelSpec

from eom_catalog_service.local_embedding_adapter import verify_local_embedding_model_snapshot

PREFIX = Path("/opt/eom/conda/envs/eom-embedding-experiment")
MODEL_STORE = Path("/opt/eom/embedding-models")
MODEL_ID = "embeddingmodel_f30c692a99476867e96f3567ae266036"
MODEL_REVISION = "embeddingmodelrev_82eace0bd4ceeacb31ced2e8e40bc293"
MODEL_MANIFEST = "sha256:f106f8df1ca01062a3900fa65f4c235d278294c34a113efe1cc1934432d0d9eb"
WORKER_USER = "eom-embedding-experiment"
RUNTIME_VERSIONS = {
    "torch": "2.7.1+cpu",
    "transformers": "4.56.2",
    "safetensors": "0.6.2",
    "tokenizers": "0.22.2",
}
DENIED_FILES = (
    ("nas", Path("/mnt/nas")),
    ("repository", Path("/home/eom/EOM")),
    ("api_configuration", Path("/etc/eom")),
    ("root_auth", Path("/root/.codex")),
    ("worker_homes", Path("/srv/eom/worker-homes")),
    ("image_models", Path("/srv/eom/models/image")),
    ("api_runtime", Path("/srv/eom/conda/envs/eom-api")),
    ("owner_workspace", Path("/var/lib/eom-workflow-runner")),
    ("handoff_workspace", Path("/run/eom-embedding-experiments")),
    ("gpu", Path("/dev/nvidia0")),
)
DENIED_SOCKETS = (
    ("postgres", "/run/postgresql/.s.PGSQL.5432"),
    ("docker", "/var/run/docker.sock"),
    ("systemd", "/run/systemd/private"),
    ("dbus", "/run/dbus/system_bus_socket"),
)


def require_cpu_identity() -> None:
    identity = pwd.getpwnam(WORKER_USER)
    if (
        os.geteuid() != identity.pw_uid
        or os.getegid() != identity.pw_gid
        or set(os.getgroups()) - {identity.pw_gid}
    ):
        raise ValueError("INFERENCE_CPU_PROBE_IDENTITY_INVALID")
    status = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    if (
        status.get("NoNewPrivs", "").strip() != "1"
        or int(status.get("CapEff", "1").strip(), 16) != 0
        or int(status.get("CapBnd", "1").strip(), 16) != 0
    ):
        raise ValueError("INFERENCE_CPU_PROBE_PRIVILEGE_INVALID")


def _protected(path: Path, *, allow_link: bool = False) -> Path:
    for member in (path, *path.parents):
        value = member.lstat()
        if (
            value.st_uid != 0
            or (stat.S_ISLNK(value.st_mode) and not (allow_link and member == path))
            or (not stat.S_ISLNK(value.st_mode) and value.st_mode & 0o022)
        ):
            raise ValueError("INFERENCE_CPU_PROBE_RUNTIME_UNPROTECTED")
    resolved = path.resolve(strict=True)
    if resolved != path:
        _protected(resolved)
        if not resolved.is_relative_to(PREFIX):
            raise ValueError("INFERENCE_CPU_PROBE_RUNTIME_UNPROTECTED")
    return resolved


def verify_installed_runtime() -> None:
    if sys.version_info[:3] != (3, 12, 13) or Path(sys.prefix) != PREFIX:
        raise ValueError("INFERENCE_CPU_PROBE_RUNTIME_MISMATCH")
    _protected(Path(sys.executable), allow_link=True)
    for name, expected in RUNTIME_VERSIONS.items():
        if importlib.metadata.version(name) != expected:
            raise ValueError("INFERENCE_CPU_PROBE_RUNTIME_MISMATCH")
    # Imports verify actual module availability, not numerical inference or quality.
    for name in (
        "torch",
        "transformers",
        "safetensors",
        "tokenizers",
        "eom_catalog_service",
        "eom_orchestrator",
    ):
        module = importlib.import_module(name)
        origin = getattr(module, "__file__", None)
        if origin is None or not Path(origin).is_relative_to(PREFIX):
            raise ValueError("INFERENCE_CPU_PROBE_IMPORT_INVALID")
        _protected(Path(origin))
    distribution = importlib.metadata.distribution("eom-platform")
    direct = distribution.read_text("direct_url.json")
    if direct and json.loads(direct).get("dir_info", {}).get("editable"):
        raise ValueError("INFERENCE_CPU_PROBE_EDITABLE_FORBIDDEN")
    record = distribution.read_text("RECORD")
    if record is None:
        raise ValueError("INFERENCE_CPU_PROBE_RECORD_INVALID")
    for row in csv.reader(io.StringIO(record)):
        if len(row) != 3:
            raise ValueError("INFERENCE_CPU_PROBE_RECORD_INVALID")
        path = Path(str(distribution.locate_file(row[0]))).resolve(strict=True)
        if not path.is_relative_to(PREFIX):
            raise ValueError("INFERENCE_CPU_PROBE_RECORD_INVALID")
        _protected(path)
        if row[1]:
            actual = (
                base64.urlsafe_b64encode(hashlib.sha256(path.read_bytes()).digest())
                .decode()
                .rstrip("=")
            )
            if row[1] != "sha256=" + actual or row[2] != str(path.stat().st_size):
                raise ValueError("INFERENCE_CPU_PROBE_RECORD_INVALID")
        elif not (row[0].endswith("/RECORD") or row[0].endswith(".pyc")):
            raise ValueError("INFERENCE_CPU_PROBE_RECORD_INVALID")
    check = subprocess.run(
        [str(PREFIX / "bin/python"), "-I", "-m", "pip", "check"],
        env={"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=60,
        check=False,
    )
    if check.returncode:
        raise ValueError("INFERENCE_CPU_PROBE_REQUIREMENTS_BROKEN")


def denied_file(path: Path) -> str:
    """Never read bytes, including when the forbidden path unexpectedly opens."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    except PermissionError:
        return "DENIED"
    except FileNotFoundError:
        # Report absence separately; it is not evidence of permission enforcement.
        return "ABSENT_IN_SANDBOX"
    else:
        os.close(descriptor)
        raise ValueError("INFERENCE_CPU_PROBE_FORBIDDEN_ACCESS")


def denied_socket(path: str) -> str:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(1)
        try:
            connection.connect(path)
        except PermissionError:
            return "DENIED"
        except FileNotFoundError:
            return "ABSENT_IN_SANDBOX"
        # Refused means the socket path was reachable, not a successful deny check.
        raise ValueError("INFERENCE_CPU_PROBE_FORBIDDEN_SOCKET")


def verify_no_network() -> None:
    if set(os.listdir("/sys/class/net")) != {"lo"}:
        raise ValueError("INFERENCE_CPU_PROBE_NETWORK_NAMESPACE_INVALID")
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            connection = socket.socket(family, socket.SOCK_STREAM)
        except OSError as exc:
            if exc.errno in {errno.EAFNOSUPPORT, errno.EPERM, errno.EACCES}:
                continue
            raise ValueError("INFERENCE_CPU_PROBE_NETWORK_CHECK_FAILED") from exc
        connection.close()
        raise ValueError("INFERENCE_CPU_PROBE_NETWORK_FAMILY_ALLOWED")


def read_cpu_model_spec(root: Path) -> LocalEmbeddingModelSpec:
    """Bound the initial manifest materialization before the shared full snapshot resolver."""
    path = _protected(root / "manifest.json")
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= 128 * 1024
        ):
            raise ValueError("INFERENCE_CPU_PROBE_MODEL_MISMATCH")
        payload = os.read(descriptor, before.st_size + 1)

        def epoch(value: os.stat_result) -> tuple[int, ...]:
            return (
                value.st_dev,
                value.st_ino,
                value.st_uid,
                value.st_gid,
                value.st_mode,
                value.st_nlink,
                value.st_size,
                value.st_mtime_ns,
                value.st_ctime_ns,
            )

        if (
            len(payload) != before.st_size
            or epoch(before) != epoch(os.fstat(descriptor))
            or epoch(before) != epoch(path.lstat())
        ):
            raise ValueError("INFERENCE_CPU_PROBE_MODEL_MISMATCH")
        return LocalEmbeddingModelSpec.model_validate_json(payload)
    finally:
        os.close(descriptor)


def run_probe() -> tuple[str, ...]:
    require_cpu_identity()
    verify_installed_runtime()
    verify_no_network()
    root = MODEL_STORE / MODEL_ID / MODEL_REVISION
    spec = read_cpu_model_spec(root)
    if spec.manifest_sha256 != MODEL_MANIFEST:
        raise ValueError("INFERENCE_CPU_PROBE_MODEL_MISMATCH")
    verify_local_embedding_model_snapshot(MODEL_STORE, spec)
    results = ["IDENTITY=PASS", "RUNTIME_RECORD=PASS", "NETWORK=PASS", "MODEL_SNAPSHOT=PASS"]
    results.extend(f"{label}={denied_file(path)}" for label, path in DENIED_FILES)
    results.extend(f"{label}={denied_socket(path)}" for label, path in DENIED_SOCKETS)
    results.append("MODEL_FORWARD_COUNT=0")
    return tuple(results)


def main() -> int:
    try:
        # Optional imported libraries must not emit diagnostics or private content to the journal.
        original = os.dup(1)
        sys.stdout.flush()
        with open(os.devnull, "w") as sink, redirect_stdout(sink):
            os.dup2(sink.fileno(), 1)
            try:
                results = run_probe()
            finally:
                sink.flush()
                os.dup2(original, 1)
                os.close(original)
        for result in results:
            print(result)
        return 0
    except Exception:
        print("INFERENCE_CPU_ISOLATION_PROBE_REJECTED")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
