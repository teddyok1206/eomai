#!/srv/eom/conda/envs/eom-api/bin/python
"""Probe pinned chat service sandboxes without activating either native host."""

from __future__ import annotations

import argparse
import grp
import inspect
import json
import os
import pwd
import re
import shlex
import stat
import subprocess
import sys
from pathlib import Path
from typing import TypedDict
from uuid import uuid4

REPOSITORY = Path("/home/eom/EOM")
PYTHON = "/srv/eom/conda/envs/eom-api/bin/python"
UNITS = {"owner": "eom-general-chat.service", "worker": "eom-general-chat-worker.service"}
USERS = {"owner": "eom-general-chat", "worker": "eom-cdx-chat"}
OMITTED = frozenset(
    {
        "EnvironmentFile",
        "ExecStart",
        "ExecStartPre",
        "Restart",
        "RestartSec",
        "StandardOutput",
        "StandardError",
        "TimeoutStopSec",
    }
)
KEPT = frozenset(
    {
        "Type",
        "User",
        "Group",
        "SupplementaryGroups",
        "WorkingDirectory",
        "Environment",
        "RuntimeDirectory",
        "RuntimeDirectoryMode",
        "StateDirectory",
        "StateDirectoryMode",
        "NoNewPrivileges",
        "PrivateTmp",
        "PrivateDevices",
        "ProtectSystem",
        "ProtectHome",
        "ProtectKernelTunables",
        "ProtectKernelModules",
        "ProtectControlGroups",
        "ProtectClock",
        "ProtectHostname",
        "RestrictSUIDSGID",
        "RestrictRealtime",
        "LockPersonality",
        "CapabilityBoundingSet",
        "AmbientCapabilities",
        "RestrictAddressFamilies",
        "SystemCallArchitectures",
        "IPAddressDeny",
        "IPAddressAllow",
        "InaccessiblePaths",
        "ReadWritePaths",
        "ReadOnlyPaths",
        "UMask",
        "MemoryMax",
        "TasksMax",
        "KillMode",
    }
)
LIST_KEYS = frozenset({"Environment", "InaccessiblePaths", "ReadWritePaths", "ReadOnlyPaths"})


class IsolationProbeError(RuntimeError):
    pass


class NamespaceProbe(TypedDict):
    component: str
    uid: int
    gid: int
    allowed_groups: list[int]
    required_groups: list[int]
    denied: list[tuple[str, str, bool]]
    state: str
    config: str
    workspace: str
    nas: str
    docker: tuple[str, bool]


def sandbox_properties(source: str, component: str) -> dict[str, str]:
    if component not in UNITS:
        raise IsolationProbeError("CHAT_ISOLATION_COMPONENT_INVALID")
    section = ""
    values: dict[str, str] = {}
    for raw in source.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            section = line
            continue
        if section != "[Service]":
            continue
        if "=" not in line or line.endswith("\\"):
            raise IsolationProbeError("CHAT_ISOLATION_SOURCE_INVALID")
        key, value = line.split("=", 1)
        if key not in KEPT | OMITTED:
            raise IsolationProbeError("CHAT_ISOLATION_DIRECTIVE_UNREVIEWED")
        if key in OMITTED:
            continue
        if key in values:
            if key not in LIST_KEYS or not value:
                raise IsolationProbeError("CHAT_ISOLATION_SOURCE_INVALID")
            value = values[key] + " " + value
        values[key] = value
    identity = USERS[component]
    expected = {
        "User": identity,
        "Group": "eom-api" if component == "owner" else identity,
        "RuntimeDirectory": UNITS[component].removesuffix(".service"),
        "StateDirectory": UNITS[component].removesuffix(".service"),
        "RuntimeDirectoryMode": "0750",
        "StateDirectoryMode": "0700",
    }
    if any(values.get(key) != value for key, value in expected.items()):
        raise IsolationProbeError("CHAT_ISOLATION_SOURCE_IDENTITY_INVALID")
    environment = {"LANG=C.UTF-8"}
    if component == "worker":
        environment.update(
            {
                "HOME=/srv/eom/worker-homes/eom-cdx-chat",
                "CODEX_HOME=/srv/eom/worker-homes/eom-cdx-chat/.codex",
                "EOM_GENERAL_CHAT_PROTOCOL_VERSION=3",
            }
        )
    if set(shlex.split(values.get("Environment", ""))) != environment:
        raise IsolationProbeError("CHAT_ISOLATION_ENVIRONMENT_UNREVIEWED")
    values.update(Restart="no", TimeoutStopSec="20", RuntimeMaxSec="30")
    return values


def probe(data: NamespaceProbe) -> None:
    """Executed inline inside the real namespace, not imported from the repository."""
    import errno
    import os
    import socket
    import stat
    import tempfile

    def require(condition: bool, label: str) -> None:
        if not condition:
            print("FAIL " + label, flush=True)
            raise SystemExit(1)
        print("PASS " + label, flush=True)

    def open_only(path: str) -> None:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        os.close(descriptor)

    require(os.getuid() == data["uid"] and os.getgid() == data["gid"], "identity")
    groups = set(os.getgroups()) | {os.getgid()}
    require(
        groups <= set(data["allowed_groups"]) and set(data["required_groups"]) <= groups,
        "groups",
    )
    with open("/proc/self/status", encoding="ascii") as stream:
        status = dict(line.split(":", 1) for line in stream if ":" in line)
    require(status["NoNewPrivs"].strip() == "1", "no_new_privileges")
    require(int(status["CapEff"], 16) == 0 and int(status["CapBnd"], 16) == 0, "capabilities")
    for label, path, exists in data["denied"]:
        if not exists:
            print("SKIP_HOST_ABSENT " + label, flush=True)
            continue
        try:
            open_only(path)
        except OSError as error:
            require(error.errno in {errno.EACCES, errno.EPERM, errno.ENOENT}, "denied:" + label)
        else:
            require(False, "denied:" + label)
    docker_path, docker_exists = data["docker"]
    if docker_exists:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(1)
            try:
                connection.connect(docker_path)
            except OSError as error:
                require(error.errno in {errno.EACCES, errno.EPERM, errno.ENOENT}, "docker_denied")
            else:
                require(False, "docker_denied")
    else:
        print("SKIP_HOST_ABSENT docker_socket", flush=True)
    state = data["state"]
    metadata = os.stat(state, follow_symlinks=False)
    require(
        stat.S_ISDIR(metadata.st_mode)
        and (metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode))
        == (data["uid"], data["gid"], 0o700),
        "private_state",
    )
    with tempfile.TemporaryDirectory(prefix=".isolation-", dir=state) as directory:
        target = os.path.join(directory, "own-probe")
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            require(os.write(descriptor, b"probe") == 5, "local_state_write")
        finally:
            os.close(descriptor)
    mounts: dict[str, frozenset[str]] = {}
    with open("/proc/self/mountinfo", encoding="ascii") as stream:
        for line in stream:
            fields = line.split()
            mounts[fields[4]] = frozenset(fields[5].split(","))

    def readonly(path: str) -> bool:
        while path not in mounts:
            if path == "/":
                raise SystemExit(1)
            path = path.rpartition("/")[0] or "/"
        return "ro" in mounts[path]

    if data["component"] == "worker":
        config = data["config"]
        open_only(config)
        require(readonly(config) and readonly(data["workspace"]), "read_only_config_workspace")
        try:
            descriptor = os.open(config, os.O_WRONLY | os.O_NONBLOCK)
        except OSError as error:
            require(error.errno in {errno.EROFS, errno.EACCES, errno.EPERM}, "config_write_denied")
        else:
            os.close(descriptor)
            require(False, "config_write_denied")
    else:
        open_only(data["nas"])
        require(
            not readonly(data["nas"]) and os.access(data["nas"], os.W_OK, effective_ids=True),
            "nas_writer_permission_no_mutation",
        )
    print("CHAT_ISOLATION_NAMESPACE_PASS " + data["component"], flush=True)


def probe_data(properties: dict[str, str], component: str) -> NamespaceProbe:
    user = pwd.getpwnam(properties["User"])
    group = grp.getgrnam(properties["Group"])
    allowed = {user.pw_gid, group.gr_gid}
    required = {group.gr_gid}
    for name in properties.get("SupplementaryGroups", "").split():
        gid = grp.getgrnam(name).gr_gid
        allowed.add(gid)
        required.add(gid)
    shared = [
        ("repository", "/home/eom/EOM"),
        ("legacy_repository", "/home/eom/EOMIS"),
        ("operator_home", "/home/eom"),
        ("root_home", "/root"),
        ("postgres_secret", "/etc/eom/secrets/postgres.env"),
        ("api_secret", "/etc/eom/secrets/api.env"),
        ("slack_secret", "/etc/eom/secrets/dev-slack.env"),
        ("observe_secret", "/etc/eom/secrets/observe.env"),
        ("local_models", "/srv/eom/models"),
    ]
    if component == "worker":
        shared.extend([("nas", "/mnt/nas/eom/artifacts"), ("staging", "/srv/eom/staging")])
        shared.extend(
            (f"legacy_home_{index:02}", f"/srv/eom/worker-homes/eom-cdx-{index:02}")
            for index in range(1, 7)
        )
        shared.extend(
            (f"legacy_workspace_{index:02}", f"/srv/eom/workspaces/eom-cdx-{index:02}")
            for index in range(1, 7)
        )
    else:
        shared.extend(
            [
                ("all_worker_homes", "/srv/eom/worker-homes"),
                ("all_worker_workspaces", "/srv/eom/workspaces"),
                ("api_state", "/var/lib/eom-api"),
            ]
        )
    for name, mode, parent in (
        (properties["RuntimeDirectory"], 0o750, "/run"),
        (properties["StateDirectory"], 0o700, "/var/lib"),
    ):
        directory = Path(parent) / name
        if directory.exists() or directory.is_symlink():
            node = directory.lstat()
            if (
                not stat.S_ISDIR(node.st_mode)
                or (node.st_uid, node.st_gid, stat.S_IMODE(node.st_mode))
                != (user.pw_uid, group.gr_gid, mode)
                or (parent == "/run" and next(directory.iterdir(), None) is not None)
            ):
                raise IsolationProbeError("CHAT_ISOLATION_EXISTING_STATE_CONFLICT")
    return {
        "component": component,
        "uid": user.pw_uid,
        "gid": group.gr_gid,
        "allowed_groups": sorted(allowed),
        "required_groups": sorted(required),
        "denied": [(label, path, Path(path).exists()) for label, path in shared],
        "state": "/var/lib/" + properties["StateDirectory"],
        "config": "/srv/eom/worker-homes/eom-cdx-chat/.codex/config.toml",
        "workspace": "/srv/eom/workspaces/general-chat/native",
        "nas": "/mnt/nas/eom/artifacts",
        "docker": ("/var/run/docker.sock", Path("/var/run/docker.sock").exists()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("commit")
    args = parser.parse_args()
    try:
        if os.geteuid() != 0:
            raise IsolationProbeError("CHAT_ISOLATION_REQUIRES_ROOT")
        git = ["git", "-C", str(REPOSITORY)]
        if (
            re.fullmatch(r"[0-9a-f]{40}", args.commit) is None
            or subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()
            != args.commit
            or subprocess.check_output([*git, "status", "--porcelain=v1"], text=True)
        ):
            raise IsolationProbeError("CHAT_ISOLATION_SOURCE_MISMATCH")
        for unit in UNITS.values():
            state = subprocess.check_output(
                ["systemctl", "show", unit, "--property=ActiveState", "--value"], text=True
            ).strip()
            if state != "inactive":
                raise IsolationProbeError("CHAT_ISOLATION_REQUIRES_STOPPED_HOSTS")
        for component, unit in UNITS.items():
            source = subprocess.check_output(
                [*git, "show", args.commit + ":infra/systemd/" + unit], text=True
            )
            properties = sandbox_properties(source, component)
            data = probe_data(properties, component)
            program = (
                "from __future__ import annotations\nimport json\n"
                + inspect.getsource(probe)
                + "\nprobe(json.loads("
                + repr(json.dumps(data))
                + "))"
            )
            command = [
                "systemd-run",
                "--wait",
                "--pipe",
                "--collect",
                "--quiet",
                "--unit=eom-chat-isolation-" + component + "-" + uuid4().hex,
            ]
            for key, value in properties.items():
                command.append("--property=" + key + "=" + value)
            command.extend([PYTHON, "-I", "-c", program])
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=50,
                check=False,
            )
            for line in completed.stdout.splitlines():
                if re.fullmatch(
                    r"(?:PASS|FAIL|SKIP_HOST_ABSENT|CHAT_ISOLATION_NAMESPACE_PASS) [A-Za-z0-9_:]+",
                    line,
                ):
                    print(component + " " + line)
            if (
                completed.returncode
                or "CHAT_ISOLATION_NAMESPACE_PASS " + component not in completed.stdout.splitlines()
            ):
                raise IsolationProbeError("CHAT_ISOLATION_NAMESPACE_FAILED")
        print("CHAT_OS_ISOLATION=PASS\nnative_calls=0\nservice_activation=NONE")
        return 0
    except IsolationProbeError as error:
        print(str(error), file=sys.stderr)
    except Exception:
        print("CHAT_ISOLATION_VERIFIER_FAILED", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
