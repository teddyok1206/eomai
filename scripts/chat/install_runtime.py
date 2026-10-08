#!/srv/eom/conda/envs/eom-api/bin/python
"""Stage/activate the fixed dedicated Codex slot after the existing release install.

No migrations, wheel installation, authentication transfer or six-slot mutation.
Root-owned targets are first-install-or-exact-replay, not an implicit upgrade.
"""

from __future__ import annotations

import argparse
import os
import pwd
import re
import stat
import subprocess
import sys
from pathlib import Path

from eom_orchestrator.general_chat_owner_runtime import (
    ChatOwnerConfiguration,
    chat_owner_engine,
    require_chat_owner_database,
)
from eom_orchestrator.general_chat_protected_environment import (
    install_chat_environment,
    read_chat_environment,
    read_chat_preparation_file,
)
from eom_orchestrator.general_chat_state import ChatError, safe_chat_error_code

REPOSITORY = Path("/home/eom/EOM")
PYTHON = "/srv/eom/conda/envs/eom-api/bin/python"
UNITS = ("eom-general-chat-worker.service", "eom-general-chat.service")
UNIT_ROOT = Path("/etc/systemd/system")
CONFIG_ROOT = Path("/etc/eom")
SECRET = CONFIG_ROOT / "secrets/general-chat.env"
AUTH = Path("/srv/eom/worker-homes/eom-cdx-chat/.codex/auth.json")


def output(arguments: list[str]) -> str:
    return subprocess.check_output(arguments, text=True, timeout=20).strip()


def require_root_directory(path: Path) -> None:
    value = path.lstat()
    if not stat.S_ISDIR(value.st_mode) or value.st_uid != 0 or stat.S_IMODE(value.st_mode) & 0o022:
        raise ChatError("GENERAL_CHAT_INSTALL_TARGET_INVALID")


def require_replay(path: Path, payload: bytes, *, mode: int) -> bool:
    """Refuse foreign bytes, links and unsafe metadata before staging anything."""
    if not path.exists() and not path.is_symlink():
        return False
    if read_chat_preparation_file(path, uid=0, gid=0, mode=mode) != payload:
        raise ChatError("GENERAL_CHAT_INSTALL_TARGET_CONFLICT")
    return True


def require_source(commit: str, model: str) -> None:
    if os.geteuid() != 0:
        raise ChatError("GENERAL_CHAT_INSTALL_REQUIRES_ROOT")
    if (
        re.fullmatch(r"[0-9a-f]{40}", commit) is None
        or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", model) is None
        or output(["git", "-C", str(REPOSITORY), "rev-parse", "HEAD"]) != commit
        or output(["git", "--no-optional-locks", "-C", str(REPOSITORY), "status", "--porcelain"])
    ):
        raise ChatError("GENERAL_CHAT_INSTALL_SOURCE_MISMATCH")
    for unit in UNITS:
        if output(["systemctl", "show", unit, "--property=ActiveState", "--value"]) != "inactive":
            raise ChatError("GENERAL_CHAT_INSTALL_MUST_BE_STOPPED")


def require_installed_release(commit: str) -> None:
    # Isolated interpreter import: never certify a source checkout as installed.
    program = """
import pwd, stat, sys
from pathlib import Path
from eom_api.build_info import get_build_info
from eom_orchestrator import general_chat_owner_main, general_chat_worker_main
if get_build_info().source_commit != sys.argv[1]:
    raise SystemExit(1)
installer = pwd.getpwnam('eom')
for module in (general_chat_owner_main, general_chat_worker_main):
    path = Path(module.__file__)
    value = path.lstat()
    if (not str(path).startswith('/srv/eom/conda/envs/eom-api/lib/python3.12/site-packages/')
        or not stat.S_ISREG(value.st_mode)
        or (value.st_uid, value.st_gid) != (installer.pw_uid, installer.pw_gid)
        or stat.S_IMODE(value.st_mode) != 0o644 or value.st_nlink != 1):
        raise SystemExit(1)
"""
    subprocess.run(
        [PYTHON, "-I", "-c", program, commit],
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=20,
        check=True,
    )


def configuration_payloads(commit: str, model: str) -> dict[Path, bytes]:
    return {
        CONFIG_ROOT / "general-chat-model.env": f"EOM_GENERAL_CHAT_MODEL={model}\n".encode(),
        CONFIG_ROOT / "general-chat-release.env": f"EOM_RUNTIME_SOURCE_COMMIT={commit}\n".encode(),
    }


def require_compatible_runtime(commit: str, runtime_commit: str) -> None:
    if re.fullmatch(r"[0-9a-f]{40}", runtime_commit) is None:
        raise ChatError("GENERAL_CHAT_INSTALL_SOURCE_MISMATCH")
    # A helper-only follow-up need not reinstall an identical application release.
    # Exact runtime pins remain distinct from the deployment-helper source pin.
    subprocess.run(
        [
            "git",
            "-C",
            str(REPOSITORY),
            "diff",
            "--quiet",
            runtime_commit,
            commit,
            "--",
            "apps/application_api",
            "packages/protocol",
            "packages/identifiers",
            "packages/api_contracts",
            "services/orchestrator",
            "infra/chat",
            "infra/systemd",
        ],
        timeout=20,
        check=True,
    )
    require_installed_release(runtime_commit)


def stage(commit: str, model: str, *, runtime_commit: str | None = None) -> None:
    require_source(commit, model)
    selected = runtime_commit or commit
    require_compatible_runtime(commit, selected)
    for parent in (UNIT_ROOT, CONFIG_ROOT):
        require_root_directory(parent)
    # Enrolled worker auth is inspected only for metadata; never read/copy tokens.
    worker = pwd.getpwnam("eom-cdx-chat")
    auth = AUTH.lstat()
    if (
        not stat.S_ISREG(auth.st_mode)
        or (auth.st_uid, auth.st_gid, stat.S_IMODE(auth.st_mode))
        != (worker.pw_uid, worker.pw_gid, 0o600)
        or auth.st_nlink != 1
        or auth.st_size <= 0
    ):
        raise ChatError("GENERAL_CHAT_ENROLLMENT_REQUIRED")
    secret = read_chat_environment(SECRET, uid=0, gid=0, mode=0o600)
    if set(secret) != {"EOM_GENERAL_CHAT_DATABASE_URL"}:
        raise ChatError("GENERAL_CHAT_OWNER_CONFIGURATION_INVALID")
    config = ChatOwnerConfiguration.from_environment(
        secret | {"EOM_RUNTIME_SOURCE_COMMIT": selected, "EOM_GENERAL_CHAT_MODEL": model}
    )
    engine = chat_owner_engine(config, pool_size=1)
    try:
        require_chat_owner_database(engine)
    finally:
        engine.dispose()

    configs = configuration_payloads(selected, model)
    unit_sources = {UNIT_ROOT / unit: REPOSITORY / "infra/systemd" / unit for unit in UNITS}
    unit_payloads = {
        target: subprocess.check_output(
            ["git", "-C", str(REPOSITORY), "show", f"{commit}:infra/systemd/{target.name}"],
            timeout=20,
        )
        for target in unit_sources
    }
    # Complete all conflict checks before the first filesystem mutation.
    existing_configs = {
        target: require_replay(target, payload, mode=0o600) for target, payload in configs.items()
    }
    existing_units = {
        target: require_replay(target, payload, mode=0o644)
        for target, payload in unit_payloads.items()
    }
    for target, payload in configs.items():
        if not existing_configs[target]:
            install_chat_environment(target, payload, uid=0, gid=0)
    for target, source in unit_sources.items():
        if not existing_units[target]:
            # Protected root-owned parent and clean source, then verify exact bytes.
            subprocess.run(
                ["install", "-o", "root", "-g", "root", "-m", "0644", str(source), str(target)],
                timeout=20,
                check=True,
            )
        require_replay(target, unit_payloads[target], mode=0o644)
    subprocess.run(["systemctl", "daemon-reload"], timeout=20, check=True)


def activate() -> None:
    try:
        subprocess.run(["systemctl", "start", *UNITS], timeout=60, check=True)
        # Only read actual owner admission under the API UID. No inference/retry.
        program = """
import time
from eom_orchestrator.general_chat_client import GeneralChatOwnerClient
for _ in range(40):
    try:
        if GeneralChatOwnerClient().slot().state == 'READY':
            raise SystemExit(0)
    except Exception:
        pass
    time.sleep(1)
raise SystemExit(1)
"""
        subprocess.run(
            ["runuser", "-u", "eom-api", "--", PYTHON, "-I", "-c", program],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=50,
            check=True,
        )
        subprocess.run(["systemctl", "enable", *UNITS], timeout=20, check=True)
    except Exception:
        # Withdraw only the newly activated capacity; never change turns/history.
        subprocess.run(["systemctl", "stop", *UNITS], timeout=60, check=False)
        raise ChatError("GENERAL_CHAT_RUNTIME_ACTIVATION_FAILED") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stage", "activate"))
    parser.add_argument("commit")
    parser.add_argument("model")
    parser.add_argument(
        "--runtime-commit", help="Installed compatible release pin; no latest fallback"
    )
    args = parser.parse_args()
    try:
        stage(args.commit, args.model, runtime_commit=args.runtime_commit)
        if args.action == "activate":
            activate()
        print("general_chat_runtime=" + ("READY" if args.action == "activate" else "STAGED"))
        print(
            "external_api_client=NONE\nexisting_six_slots=UNCHANGED\ninstaller_model_submissions=0"
        )
        return 0
    except Exception as error:
        print(safe_chat_error_code(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
