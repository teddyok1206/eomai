#!/srv/eom/conda/envs/eom-api/bin/python
"""Stage/activate the fixed dedicated Codex slot after the existing release install.

No migrations, wheel installation, authentication transfer or six-slot mutation.
Root-owned targets are first-install-or-exact-replay. Nonsecret release/model
configuration and source-pinned units can advance from verified predecessors
while both chat services are stopped. Credentials and history are never replaced.
"""

from __future__ import annotations

import argparse
import os
import pwd
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from eom_identifiers import sha256_bytes
from eom_orchestrator.codex_cli_identity import (
    CodexCliIdentityGuard,
    capture_codex_cli_identity,
)
from eom_orchestrator.general_chat_owner_runtime import (
    ChatOwnerConfiguration,
    chat_owner_engine,
    require_chat_owner_database,
)
from eom_orchestrator.general_chat_private_query_client import PRIVATE_CHAT_QUERY_SOURCE_SOCKET
from eom_orchestrator.general_chat_protected_environment import (
    install_chat_environment,
    read_chat_environment,
    read_chat_preparation_file,
)
from eom_orchestrator.general_chat_runtime_selection import RUNTIME_ENVIRONMENT_KEYS
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint
from eom_orchestrator.general_chat_state import ChatError, safe_chat_error_code
from eom_protocol.general_chat_rag_knowledge import ChatRagPolicy
from eom_protocol.general_chat_worker_messages import CodexCliIdentity

REPOSITORY = Path("/home/eom/EOM")
PYTHON = "/srv/eom/conda/envs/eom-api/bin/python"
UNITS = ("eom-general-chat-worker.service", "eom-general-chat.service")
UNIT_ROOT = Path("/etc/systemd/system")
CONFIG_ROOT = Path("/etc/eom")
SOURCE_TMPFILE = Path("/etc/tmpfiles.d/eom-general-chat-query-read.conf")
SECRET = CONFIG_ROOT / "secrets/general-chat.env"
AUTH = Path("/srv/eom/worker-homes/eom-cdx-chat/.codex/auth.json")
CODEX_BINARY = Path("/usr/local/bin/codex")
NATIVE_RUNTIME_KEYS = tuple(RUNTIME_ENVIRONMENT_KEYS.values())


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
    require_chat_services_stopped()


def require_chat_services_stopped() -> None:
    for unit in UNITS:
        state = output(["systemctl", "show", unit, "--property=ActiveState", "--value"])
        pid = output(["systemctl", "show", unit, "--property=MainPID", "--value"])
        # A terminal failed startup is quiescent, not permission to erase its
        # journal or operation history. Never stage over a live process.
        if state not in {"inactive", "failed"} or pid != "0":
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


def configuration_payloads(
    commit: str,
    model: str,
    *,
    rag_policy: ChatRagPolicy | None = None,
    native_runtime: CodexCliIdentity | None = None,
    private_query_source: bool = False,
    similarity_search: bool = False,
) -> dict[Path, bytes]:
    model_value = f"EOM_GENERAL_CHAT_MODEL={model}\n"
    if rag_policy is not None:
        # These are public, exact retrieval pins, not worker-supplied authority.
        rag_policy = ChatRagPolicy.model_validate(rag_policy.model_dump(mode="json"))
        model_value += (
            "EOM_GENERAL_CHAT_PROTOCOL_VERSION=4\n"
            f"EOM_GENERAL_CHAT_RAG_POLICY_REVISION_ID={rag_policy.access_policy_revision_id}\n"
            f"EOM_GENERAL_CHAT_RAG_POLICY_SHA256={rag_policy.sha256}\n"
        )
    if native_runtime is not None:
        if rag_policy is None:
            raise ChatError("GENERAL_CHAT_OWNER_CONFIGURATION_INVALID")
        native_runtime = CodexCliIdentity.model_validate(native_runtime.model_dump(mode="json"))
        runtime_values = native_runtime.model_dump(mode="json")
        model_value += "".join(
            f"{key}={runtime_values[field]}\n" for field, key in RUNTIME_ENVIRONMENT_KEYS.items()
        )
    if private_query_source:
        if rag_policy is None:
            raise ChatError("GENERAL_CHAT_OWNER_CONFIGURATION_INVALID")
        model_value += "EOM_GENERAL_CHAT_PRIVATE_QUERY_SOURCE=READ_ONLY\n"
    if similarity_search:
        if not private_query_source:
            raise ChatError("GENERAL_CHAT_OWNER_CONFIGURATION_INVALID")
        model_value += "EOM_GENERAL_CHAT_SIMILARITY_SEARCH=NATIVE_TOPIC\n"
    return {
        CONFIG_ROOT / "general-chat-model.env": model_value.encode(),
        CONFIG_ROOT / "general-chat-release.env": f"EOM_RUNTIME_SOURCE_COMMIT={commit}\n".encode(),
    }


def require_pinned_model_selection(
    model: str,
    *,
    rag_policy: ChatRagPolicy | None,
    secret: dict[str, str],
    source_commit: str,
) -> ChatOwnerConfiguration:
    """Pin-only selection preserves the existing released model and RAG authority."""
    values = read_chat_environment(CONFIG_ROOT / "general-chat-model.env", uid=0, gid=0, mode=0o600)
    allowed = {
        "EOM_GENERAL_CHAT_MODEL",
        "EOM_GENERAL_CHAT_PROTOCOL_VERSION",
        "EOM_GENERAL_CHAT_RAG_POLICY_REVISION_ID",
        "EOM_GENERAL_CHAT_RAG_POLICY_SHA256",
        *NATIVE_RUNTIME_KEYS,
        "EOM_GENERAL_CHAT_PRIVATE_QUERY_SOURCE",
        "EOM_GENERAL_CHAT_SIMILARITY_SEARCH",
    }
    if set(values) - allowed:
        raise ChatError("GENERAL_CHAT_OWNER_CONFIGURATION_INVALID")
    current = ChatOwnerConfiguration.from_environment(
        secret | {"EOM_RUNTIME_SOURCE_COMMIT": source_commit} | values
    )
    if (
        current.model != model
        or current.rag_policy is None
        or (rag_policy is not None and rag_policy != current.rag_policy)
    ):
        raise ChatError("GENERAL_CHAT_INSTALL_TARGET_CONFLICT")
    return current


def source_endpoint_preflight(commit: str) -> tuple[bytes, bool]:
    """Exact fixed tmpfiles policy; conflict checks precede all staging mutations."""
    require_root_directory(SOURCE_TMPFILE.parent)
    require_root_directory(Path("/run"))
    payload = subprocess.check_output(
        [
            "git",
            "-C",
            str(REPOSITORY),
            "show",
            f"{commit}:infra/tmpfiles/eom-general-chat-query-read.conf",
        ],
        timeout=20,
    )
    present = require_replay(SOURCE_TMPFILE, payload, mode=0o644)
    endpoint = source_endpoint()
    if endpoint.path.parent.exists() or endpoint.path.parent.is_symlink():
        endpoint.require_parent()
    # Never reclaim an existing or substituted endpoint, even if services appear stopped.
    if endpoint.path.exists() or endpoint.path.is_symlink():
        raise ChatError("GENERAL_CHAT_INSTALL_TARGET_CONFLICT")
    return payload, present


def source_endpoint() -> ChatSocketEndpoint:
    import grp

    return ChatSocketEndpoint(
        PRIVATE_CHAT_QUERY_SOURCE_SOCKET,
        pwd.getpwnam("eom-general-chat").pw_uid,
        grp.getgrnam("eom").gr_gid,
    )


def stage_source_endpoint(payload: bytes, *, present: bool) -> None:
    if not present:
        install_chat_environment(SOURCE_TMPFILE, payload, uid=0, gid=0, mode=0o644)
    require_replay(SOURCE_TMPFILE, payload, mode=0o644)
    subprocess.run(["systemd-tmpfiles", "--create", str(SOURCE_TMPFILE)], timeout=20, check=True)
    source_endpoint().require_parent()


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
            "infra/tmpfiles/eom-general-chat-query-read.conf",
        ],
        timeout=20,
        check=True,
    )
    require_installed_release(runtime_commit)


def require_release_update(path: Path, *, previous: str, selected: str) -> None:
    if re.fullmatch(r"[0-9a-f]{40}", previous) is None or previous == selected:
        raise ChatError("GENERAL_CHAT_INSTALL_SOURCE_MISMATCH")
    expected = f"EOM_RUNTIME_SOURCE_COMMIT={previous}\n".encode()
    if not require_replay(path, expected, mode=0o600):
        raise ChatError("GENERAL_CHAT_INSTALL_TARGET_CONFLICT")


def update_release_pin(path: Path, payload: bytes, *, previous: str, selected: str) -> None:
    """Atomic nonsecret pin advance; auth/model/unit bytes are never overwritten."""
    with tempfile.TemporaryDirectory(prefix=".general-chat-release-", dir=path.parent) as staging:
        temporary = Path(staging) / path.name
        install_chat_environment(temporary, payload, uid=0, gid=0)
        require_release_update(path, previous=previous, selected=selected)
        os.replace(temporary, path)
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)


def require_configuration_predecessor(path: Path, *, digest: str, mode: int) -> None:
    allowed = {CONFIG_ROOT / "general-chat-model.env", *(UNIT_ROOT / unit for unit in UNITS)}
    if (
        path not in allowed
        or mode not in {0o600, 0o644}
        or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
        or sha256_bytes(read_chat_preparation_file(path, uid=0, gid=0, mode=mode)) != digest
    ):
        raise ChatError("GENERAL_CHAT_INSTALL_TARGET_CONFLICT")


def update_prepared_configuration(path: Path, payload: bytes, *, digest: str, mode: int) -> None:
    require_configuration_predecessor(path, digest=digest, mode=mode)
    with tempfile.TemporaryDirectory(prefix=".general-chat-config-", dir=path.parent) as staging:
        temporary = Path(staging) / path.name
        install_chat_environment(temporary, payload, uid=0, gid=0)
        os.chmod(temporary, mode, follow_symlinks=False)
        require_configuration_predecessor(path, digest=digest, mode=mode)
        os.replace(temporary, path)
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)


def stage(
    commit: str,
    model: str,
    *,
    runtime_commit: str | None = None,
    previous_runtime_commit: str | None = None,
    rag_policy: ChatRagPolicy | None = None,
    previous_model_config_sha256: str | None = None,
    pin_codex_runtime: bool = False,
    private_query_source: bool | None = None,
    similarity_search: bool | None = None,
) -> None:
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
    native_guard: CodexCliIdentityGuard | None = None
    if pin_codex_runtime:
        pinned = require_pinned_model_selection(
            model, rag_policy=rag_policy, secret=secret, source_commit=selected
        )
        if private_query_source is not None and private_query_source != pinned.private_query_source:
            raise ChatError("GENERAL_CHAT_INSTALL_TARGET_CONFLICT")
        if similarity_search is not None and similarity_search != pinned.similarity_search:
            raise ChatError("GENERAL_CHAT_INSTALL_TARGET_CONFLICT")
        rag_policy = pinned.rag_policy
        private_query_source = pinned.private_query_source
        similarity_search = pinned.similarity_search
        native_guard = capture_codex_cli_identity(CODEX_BINARY)
    configs = configuration_payloads(
        selected,
        model,
        rag_policy=rag_policy,
        native_runtime=native_guard.identity if native_guard is not None else None,
        private_query_source=private_query_source is True,
        similarity_search=similarity_search is True,
    )
    model_settings = dict(
        line.split("=", 1)
        for line in configs[CONFIG_ROOT / "general-chat-model.env"].decode("ascii").splitlines()
    )
    config = ChatOwnerConfiguration.from_environment(
        secret | {"EOM_RUNTIME_SOURCE_COMMIT": selected} | model_settings
    )
    engine = chat_owner_engine(config, pool_size=1)
    try:
        require_chat_owner_database(engine)
    finally:
        engine.dispose()

    unit_sources = {UNIT_ROOT / unit: REPOSITORY / "infra/systemd" / unit for unit in UNITS}
    unit_payloads = {
        target: subprocess.check_output(
            ["git", "-C", str(REPOSITORY), "show", f"{commit}:infra/systemd/{target.name}"],
            timeout=20,
        )
        for target in unit_sources
    }
    # Complete all conflict checks before the first filesystem mutation.
    release_target = CONFIG_ROOT / "general-chat-release.env"
    updates: dict[Path, tuple[str, int]] = {}
    if previous_model_config_sha256 is not None:
        if re.fullmatch(r"sha256:[0-9a-f]{64}", previous_model_config_sha256) is None or (
            previous_runtime_commit is None and not pin_codex_runtime
        ):
            raise ChatError("GENERAL_CHAT_INSTALL_TARGET_CONFLICT")
        model_target = CONFIG_ROOT / "general-chat-model.env"
        if not (
            pin_codex_runtime
            and read_chat_preparation_file(model_target, uid=0, gid=0, mode=0o600)
            == configs[model_target]
        ):
            require_configuration_predecessor(
                model_target, digest=previous_model_config_sha256, mode=0o600
            )
            updates[model_target] = (previous_model_config_sha256, 0o600)
    advance_release = previous_runtime_commit is not None and not (
        pin_codex_runtime and previous_runtime_commit == selected
    )
    existing_configs = {}
    for target, payload in configs.items():
        if target == release_target and advance_release:
            assert previous_runtime_commit is not None
            if (
                pin_codex_runtime
                and read_chat_preparation_file(target, uid=0, gid=0, mode=0o600) == payload
            ):
                advance_release = False
            else:
                require_release_update(target, previous=previous_runtime_commit, selected=selected)
            existing_configs[target] = True
        elif target in updates:
            existing_configs[target] = True
        else:
            existing_configs[target] = require_replay(target, payload, mode=0o600)
    existing_units = {}
    for target, payload in unit_payloads.items():
        if (
            pin_codex_runtime
            and read_chat_preparation_file(target, uid=0, gid=0, mode=0o644) == payload
        ):
            existing_units[target] = True
            continue
        if previous_runtime_commit is not None:
            prior = subprocess.check_output(
                [
                    "git",
                    "-C",
                    str(REPOSITORY),
                    "show",
                    f"{previous_runtime_commit}:infra/systemd/{target.name}",
                ],
                timeout=20,
            )
            if prior != payload:
                require_configuration_predecessor(target, digest=sha256_bytes(prior), mode=0o644)
                updates[target] = (sha256_bytes(prior), 0o644)
                existing_units[target] = True
                continue
        existing_units[target] = require_replay(target, payload, mode=0o644)
    source_prepared = source_endpoint_preflight(commit) if config.private_query_source else None
    source_needs_staging = source_prepared is not None and (
        not source_prepared[1] or not source_endpoint().path.parent.exists()
    )
    if native_guard is not None:
        # Capture is not permission to race service startup or a CLI replacement.
        # Recheck the same file epoch and stopped services before any mutation.
        native_guard.assert_unchanged()
        require_chat_services_stopped()
        if (
            all(existing_configs.values())
            and all(existing_units.values())
            and not updates
            and not advance_release
            and not source_needs_staging
        ):
            return
    if source_needs_staging:
        assert source_prepared is not None
        stage_source_endpoint(source_prepared[0], present=source_prepared[1])
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
    for target, (digest, mode) in updates.items():
        if native_guard is not None:
            native_guard.assert_unchanged()
            require_chat_services_stopped()
        update_prepared_configuration(
            target,
            configs[target] if target in configs else unit_payloads[target],
            digest=digest,
            mode=mode,
        )
    for target, payload in unit_payloads.items():
        require_replay(target, payload, mode=0o644)
    if advance_release:
        assert previous_runtime_commit is not None
        if native_guard is not None:
            native_guard.assert_unchanged()
            require_chat_services_stopped()
        update_release_pin(
            release_target,
            configs[release_target],
            previous=previous_runtime_commit,
            selected=selected,
        )
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
    parser.add_argument(
        "--previous-runtime-commit",
        help="Exact stopped-runtime predecessor for nonsecret pin update",
    )
    parser.add_argument("--rag-policy-revision-id")
    parser.add_argument("--rag-policy-sha256")
    parser.add_argument("--previous-model-config-sha256")
    parser.add_argument(
        "--private-query-source",
        choices=("DISABLED", "READ_ONLY"),
        help="Explicit source-only socket selection; Codex-only repins preserve the current value",
    )
    parser.add_argument(
        "--similarity-search",
        choices=("DISABLED", "NATIVE_TOPIC"),
        help="Optional native TOPIC enrichment; requires the private source endpoint",
    )
    parser.add_argument(
        "--pin-codex-runtime",
        action="store_true",
        help="Pin the protected installed CLI while preserving the existing protocol-4 model/RAG",
    )
    args = parser.parse_args()
    try:
        rag_policy = None
        if args.rag_policy_revision_id is not None or args.rag_policy_sha256 is not None:
            rag_policy = ChatRagPolicy.model_validate(
                {
                    "access_policy_revision_id": args.rag_policy_revision_id,
                    "sha256": args.rag_policy_sha256,
                }
            )
        stage(
            args.commit,
            args.model,
            runtime_commit=args.runtime_commit,
            previous_runtime_commit=args.previous_runtime_commit,
            rag_policy=rag_policy,
            previous_model_config_sha256=args.previous_model_config_sha256,
            pin_codex_runtime=args.pin_codex_runtime,
            private_query_source=(
                None
                if args.private_query_source is None
                else args.private_query_source == "READ_ONLY"
            ),
            similarity_search=(
                None if args.similarity_search is None else args.similarity_search == "NATIVE_TOPIC"
            ),
        )
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
