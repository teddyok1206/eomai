"""Installed root supervisor; all actual request handling runs as the native owner."""

from __future__ import annotations

import grp
import hashlib
import importlib.abc
import importlib.machinery
import json
import os
import pwd
import re
import signal
import stat
import sys
from collections.abc import Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import FrameType, ModuleType

    from eom_identity_service import AuthenticatedOperatorSession
    from eom_identity_service.installed_owner_session_provider import (
        InstalledIdentityProviderObservation,
    )
    from eom_orchestrator.reference_query_prepare_ports import ReferenceQueryPreparationPort
    from eom_workflow.reference_query_owner_configuration import ReferenceQueryServiceConfiguration

_RELEASES = Path("/opt/eom/embedding-owner-releases")
_CONFIGURATION = Path("/etc/eom/reference-query-owner.json")
_SOCKET_PARENT = Path("/run/eom-reference-query-owner")


def _installed_site() -> Path:
    # This bootstrap must use stdlib only: importing a shared EOM helper before
    # validating its installed prefix would invert this trust boundary.
    entry = Path(__file__)
    site, release = entry.parent.parent, entry.parent.parent.parent
    if (
        not sys.flags.isolated
        or not sys.dont_write_bytecode
        or sys.argv != [str(entry)]
        or entry.name != "reference_query_owner_entry.py"
        or entry.parent.name != "eom_workflow_runner"
        or site.name != "site-packages"
        or release.parent != _RELEASES
        or re.fullmatch(r"[0-9a-f]{40}", release.name) is None
    ):
        raise ValueError("REFERENCE_QUERY_OWNER_INSTALLATION_UNAVAILABLE")
    for parent in entry.parents:
        metadata = parent.lstat()
        if (
            parent.is_symlink()
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_mode & 0o022
        ):
            raise ValueError("REFERENCE_QUERY_OWNER_INSTALLATION_UNAVAILABLE")
    metadata = entry.lstat()
    if (
        entry.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_mode & 0o022
        or metadata.st_nlink != 1
    ):
        raise ValueError("REFERENCE_QUERY_OWNER_INSTALLATION_UNAVAILABLE")
    return site


class _InstalledOwnerImports(importlib.abc.MetaPathFinder):
    def __init__(self, site: Path):
        self.site = site

    def find_spec(
        self, fullname: str, path: Sequence[str] | None = None, target: ModuleType | None = None
    ) -> importlib.machinery.ModuleSpec | None:
        if fullname.split(".", 1)[0] in {"torch", "transformers", "sentence_transformers"}:
            raise ModuleNotFoundError("REFERENCE_QUERY_OWNER_NUMERICAL_IMPORT_DENIED")
        if fullname.startswith("eom_") or fullname == "eomctl" or fullname.startswith("eomctl."):
            spec = importlib.machinery.PathFinder.find_spec(fullname, path)
            if (
                spec is None
                or not isinstance(spec.origin, str)
                or not Path(spec.origin).resolve().is_relative_to(self.site)
            ):
                raise ModuleNotFoundError("REFERENCE_QUERY_OWNER_IMPORT_UNAVAILABLE")
            return spec
        return None


def _configuration_bytes() -> bytes:
    expected = os.environ.get("EOM_REFERENCE_QUERY_CONFIGURATION_SHA256", "")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", expected) is None:
        raise ValueError("REFERENCE_QUERY_OWNER_CONFIGURATION_UNAVAILABLE")
    # Existing protected-file snapshots check ancestors, no symlink, root owner,
    # immutable metadata and the independently selected raw hash.
    from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots

    snapshots = NumericalRuntimeFileSnapshots()
    return snapshots.read(_CONFIGURATION, sha256=expected, maximum=64 * 1024)


def _provision_socket_parent() -> None:
    owner, api = pwd.getpwnam("eom-workflow-runner"), grp.getgrnam("eom-api")
    # /run is a root-owned fixed parent; never chmod/chown an existing directory
    # into compliance. A missing transient directory is a bounded boot action.
    metadata = _SOCKET_PARENT.parent.lstat()
    if (
        _SOCKET_PARENT.parent.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_mode & 0o022
    ):
        raise ValueError("REFERENCE_QUERY_OWNER_SOCKET_LAYOUT_INVALID")
    try:
        _SOCKET_PARENT.mkdir(mode=0o700)
    except FileExistsError:
        pass
    else:
        os.chown(_SOCKET_PARENT, owner.pw_uid, api.gr_gid, follow_symlinks=False)
        _SOCKET_PARENT.chmod(0o2750)
    metadata = _SOCKET_PARENT.lstat()
    if (
        _SOCKET_PARENT.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or (metadata.st_uid, metadata.st_gid) != (owner.pw_uid, api.gr_gid)
        or stat.S_IMODE(metadata.st_mode) != 0o2750
    ):
        raise ValueError("REFERENCE_QUERY_OWNER_SOCKET_LAYOUT_INVALID")


def _emit(event: str, *, error: BaseException | None = None) -> None:
    metadata: dict[str, str] = {"event": event, "at": datetime.now(UTC).isoformat()}
    if error is not None:
        metadata["error_type"] = type(error).__name__
        code = getattr(error, "code", None)
        if type(code) is str and re.fullmatch(r"[A-Z][A-Z0-9_]{1,95}", code):
            metadata["code"] = code
    print(json.dumps(metadata, sort_keys=True), flush=True)


def _serve_child(
    configuration: ReferenceQueryServiceConfiguration,
    observation: InstalledIdentityProviderObservation,
    raw_sha256: str,
    restore_mask: set[int | signal.Signals],
) -> int:
    from eom_catalog_contracts.reference_query_prepare import REFERENCE_QUERY_PREPARE_SOCKET
    from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots
    from eom_identity_service.installed_owner_session_provider import (
        ProtectedInstalledIdentityProviderAdmission,
    )
    from eom_orchestrator.general_chat_socket import ChatSocketEndpoint
    from eom_orchestrator.reference_query_owner_server import ReferenceQueryOwnerServer

    from eom_workflow_runner.reference_query_owner_runtime import (
        build_reference_query_owner_runtime,
    )

    owner = pwd.getpwnam("eom-workflow-runner")
    api = pwd.getpwnam("eom-api")
    os.setgroups([])
    os.setresgid(owner.pw_gid, owner.pw_gid, owner.pw_gid)
    os.setresuid(owner.pw_uid, owner.pw_uid, owner.pw_uid)
    stop = Event()
    server = None
    runtime = None

    def stop_child(_signum: int, _frame: FrameType | None) -> None:
        stop.set()
        if server is not None:
            server.stop()

    signal.signal(signal.SIGTERM, stop_child)
    signal.signal(signal.SIGINT, stop_child)
    signal.pthread_sigmask(signal.SIG_SETMASK, restore_mask)
    try:
        snapshots = NumericalRuntimeFileSnapshots()
        snapshots.read(_CONFIGURATION, sha256=raw_sha256, maximum=64 * 1024)
        admission = ProtectedInstalledIdentityProviderAdmission(observation)
        runtime = build_reference_query_owner_runtime(configuration, admission)
        if stop.is_set():
            return 0

        def application(capture: AuthenticatedOperatorSession) -> ReferenceQueryPreparationPort:
            snapshots.assert_unchanged()
            assert runtime is not None
            return runtime.application(capture)

        server = ReferenceQueryOwnerServer(
            endpoint=ChatSocketEndpoint(
                Path(REFERENCE_QUERY_PREPARE_SOCKET), owner.pw_uid, api.pw_gid, parent_mode=0o2750
            ),
            api_uid=api.pw_uid,
            admission=admission,
            application=application,
        )
        _emit("REFERENCE_QUERY_OWNER_READY")
        server.serve()
        return 0
    except Exception as error:
        _emit("REFERENCE_QUERY_OWNER_STOPPED", error=error)
        return 1
    finally:
        if server is not None:
            server.close()
        if runtime is not None:
            runtime.close()


def main() -> int:
    restore_mask: set[int | signal.Signals] | None = None
    try:
        if os.geteuid() != 0:
            raise ValueError("REFERENCE_QUERY_OWNER_SUPERVISOR_REQUIRED")
        site = _installed_site()
        if any(
            name.startswith("eom_")
            or name == "eomctl"
            or name.startswith("eomctl.")
            or name.split(".", 1)[0] in {"torch", "transformers", "sentence_transformers"}
            for name in sys.modules
        ):
            # A finder cannot constrain modules already supplied by ambient site
            # initialization. Reject, do not delete/replace those cached modules.
            raise ValueError("REFERENCE_QUERY_OWNER_PRELOADED_IMPORT_UNAVAILABLE")
        sys.path.insert(0, str(site))
        sys.meta_path.insert(0, _InstalledOwnerImports(site))
        from eom_identity_service import open_installed_identity_provider_observation
        from eom_identity_service.owner_session_transport import FixedIdentityProviderPin
        from eom_workflow.reference_query_owner_configuration import (
            parse_reference_query_service_configuration,
        )

        raw = _configuration_bytes()
        configuration = parse_reference_query_service_configuration(raw)
        if configuration.owner_source_commit != site.parent.name:
            raise ValueError("REFERENCE_QUERY_OWNER_SOURCE_MISMATCH")
        selected = configuration.api_provider
        _provision_socket_parent()
        with open_installed_identity_provider_observation(
            FixedIdentityProviderPin(
                selected.source_commit, selected.wheel_sha256, selected.configuration_sha256
            ),
            code_sha256=tuple((pin.member, pin.sha256) for pin in selected.code_members),
        ) as observation:
            # Install parent/child stop handlers before exposing pending signals;
            # no orphan request owner is created in the fork-to-handler window.
            restore_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT})
            child = os.fork()
            if child == 0:
                status = _serve_child(
                    configuration,
                    observation,
                    "sha256:" + hashlib.sha256(raw).hexdigest(),
                    restore_mask,
                )
                sys.stdout.flush()
                os._exit(status)

            def stop_parent(signum: int, _frame: FrameType | None) -> None:
                with suppress(ProcessLookupError):
                    os.kill(child, signum)

            signal.signal(signal.SIGTERM, stop_parent)
            signal.signal(signal.SIGINT, stop_parent)
            signal.pthread_sigmask(signal.SIG_SETMASK, restore_mask)
            restore_mask = None
            _, status = os.waitpid(child, 0)
            return os.waitstatus_to_exitcode(status)
    except Exception as error:
        _emit("REFERENCE_QUERY_OWNER_SUPERVISOR_STOPPED", error=error)
        return 1
    finally:
        if restore_mask is not None:
            signal.pthread_sigmask(signal.SIG_SETMASK, restore_mask)


if __name__ == "__main__":
    raise SystemExit(main())
