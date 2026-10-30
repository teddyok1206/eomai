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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import FrameType, ModuleType

    from eom_identity_service import AuthenticatedOperatorSession
    from eom_identity_service.installed_owner_session_provider import (
        InstalledIdentityProviderObservation,
    )
    from eom_orchestrator.reference_query_prepare_ports import ReferenceQueryPreparationPort
    from eom_workflow.reference_query_owner_configuration import ReferenceQueryServiceConfiguration
    from eom_workflow.reference_query_routed_owner_configuration import (
        SupportedRoutedReferenceQueryOwnerConfiguration,
    )

_RELEASES = Path("/opt/eom/embedding-owner-releases")
_CONFIGURATION = Path("/etc/eom/reference-query-owner.json")
_MIXED_CONFIGURATION = Path("/etc/eom/mixed-reference-query-owner.json")
_PUBLIC_CONFIGURATION = Path("/etc/eom/public-reference-query-owner.json")
_SOCKET_PARENT = Path("/run/eom-reference-query-owner")
_PRIVATE_CONFIGURATION = Path("/etc/eom/private-chat-query-owner.json")
_PRIVATE_SOCKET_PARENT = Path("/run/eom-private-chat-query-owner")


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


def _private_configuration_bytes() -> bytes | None:
    expected = os.environ.get("EOM_PRIVATE_CHAT_QUERY_CONFIGURATION_SHA256")
    if expected is None:
        return None  # Opt-in absence preserves reference-only startup.
    if re.fullmatch(r"sha256:[0-9a-f]{64}", expected) is None:
        raise ValueError("PRIVATE_CHAT_QUERY_OWNER_CONFIGURATION_UNAVAILABLE")
    from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots

    return NumericalRuntimeFileSnapshots().read(
        _PRIVATE_CONFIGURATION, sha256=expected, maximum=16 * 1024
    )


def _mixed_configuration_bytes() -> bytes | None:
    expected = os.environ.get("EOM_MIXED_REFERENCE_QUERY_CONFIGURATION_SHA256")
    if expected is None:
        return None
    if re.fullmatch(r"sha256:[0-9a-f]{64}", expected) is None:
        raise ValueError("REFERENCE_QUERY_MIXED_CONFIGURATION_UNAVAILABLE")
    from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots

    return NumericalRuntimeFileSnapshots().read(
        _MIXED_CONFIGURATION, sha256=expected, maximum=64 * 1024
    )


def _public_configuration_bytes() -> bytes | None:
    expected = os.environ.get("EOM_PUBLIC_REFERENCE_QUERY_CONFIGURATION_SHA256")
    if expected is None:
        return None
    if re.fullmatch(r"sha256:[0-9a-f]{64}", expected) is None:
        raise ValueError("REFERENCE_QUERY_PUBLIC_CONFIGURATION_UNAVAILABLE")
    from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots

    return NumericalRuntimeFileSnapshots().read(
        _PUBLIC_CONFIGURATION, sha256=expected, maximum=64 * 1024
    )


def _provision_query_socket_parent(parent: Path, group_name: str) -> None:
    owner, group = pwd.getpwnam("eom-workflow-runner"), grp.getgrnam(group_name)
    if owner.pw_uid <= 0 or group.gr_gid <= 0:
        raise ValueError("REFERENCE_QUERY_OWNER_SOCKET_LAYOUT_INVALID")
    # /run is a root-owned fixed parent; never chmod/chown an existing directory
    # into compliance. A missing transient directory is a bounded boot action.
    metadata = parent.parent.lstat()
    if (
        parent.parent.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_mode & 0o022
    ):
        raise ValueError("REFERENCE_QUERY_OWNER_SOCKET_LAYOUT_INVALID")
    try:
        parent.mkdir(mode=0o700)
    except FileExistsError:
        pass
    else:
        os.chown(parent, owner.pw_uid, group.gr_gid, follow_symlinks=False)
        parent.chmod(0o2750)
    metadata = parent.lstat()
    if (
        parent.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or (metadata.st_uid, metadata.st_gid) != (owner.pw_uid, group.gr_gid)
        or stat.S_IMODE(metadata.st_mode) != 0o2750
    ):
        raise ValueError("REFERENCE_QUERY_OWNER_SOCKET_LAYOUT_INVALID")


def _provision_socket_parent() -> None:
    _provision_query_socket_parent(_SOCKET_PARENT, "eom-api")


def _provision_private_socket_parent() -> None:
    _provision_query_socket_parent(_PRIVATE_SOCKET_PARENT, "eom-general-chat")


def _emit(event: str, *, error: BaseException | None = None) -> None:
    metadata: dict[str, str] = {"event": event, "at": datetime.now(UTC).isoformat()}
    if error is not None:
        metadata["error_type"] = type(error).__name__
        # Installed startup failures need a bounded source location, not opaque
        # retries or a traceback that could retain credentials/path arguments.
        if isinstance(error, OSError) and type(error.errno) is int:
            metadata["errno"] = str(error.errno)
        frame = error.__traceback__
        for _ in range(32):
            if frame is None:
                break
            module = frame.tb_frame.f_globals.get("__name__")
            if module == "__main__":
                module = "eom_workflow_runner.reference_query_owner_entry"
            if type(module) is str and re.fullmatch(r"eom_[a-z0-9_.]{1,120}", module):
                metadata["error_site"] = f"{module}:{frame.tb_lineno}"
            frame = frame.tb_next
        code = getattr(error, "code", None)
        if type(code) is str and re.fullmatch(r"[A-Z][A-Z0-9_]{1,95}", code):
            metadata["code"] = code
    print(json.dumps(metadata, sort_keys=True), flush=True)


def _serve_child(
    configuration: ReferenceQueryServiceConfiguration,
    observation: InstalledIdentityProviderObservation,
    raw_sha256: str,
    restore_mask: set[int | signal.Signals],
    *,
    private_raw: bytes | None = None,
    mixed_raw: bytes | None = None,
    public_raw: bytes | None = None,
    routed_configuration: SupportedRoutedReferenceQueryOwnerConfiguration | None = None,
) -> int:
    owner = pwd.getpwnam("eom-workflow-runner")
    api = pwd.getpwnam("eom-api")
    os.setgroups([])
    os.setresgid(owner.pw_gid, owner.pw_gid, owner.pw_gid)
    os.setresuid(owner.pw_uid, owner.pw_uid, owner.pw_uid)
    _require_dropped_identity(owner.pw_uid, owner.pw_gid)

    # Application/adapter imports run only after the verified privilege drop.
    from eom_catalog_contracts.reference_query_prepare import REFERENCE_QUERY_PREPARE_SOCKET
    from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots
    from eom_catalog_service.inference_transfer_read_timing import configure_read_stage_logging
    from eom_identity_service.installed_owner_session_provider import (
        ProtectedInstalledIdentityProviderAdmission,
    )
    from eom_orchestrator.general_chat_socket import ChatSocketEndpoint
    from eom_orchestrator.reference_query_owner_server import (
        PrivateChatQueryListener,
        ReferenceQueryOwnerServer,
    )

    from eom_workflow_runner.reference_query_owner_runtime import (
        build_reference_query_owner_runtime,
    )

    stop = False
    server = None
    runtime = None
    mixed_runtime = None
    public_runtime = None

    def stop_child(_signum: int, _frame: FrameType | None) -> None:
        # Parent forwarding and cgroup delivery may reenter this handler. Do not
        # acquire Event/socket locks from a Python signal handler.
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, stop_child)
    signal.signal(signal.SIGINT, stop_child)
    signal.pthread_sigmask(signal.SIG_SETMASK, restore_mask)
    try:
        configure_read_stage_logging()
        snapshots = NumericalRuntimeFileSnapshots()
        snapshots.read(_CONFIGURATION, sha256=raw_sha256, maximum=64 * 1024)
        admission = ProtectedInstalledIdentityProviderAdmission(observation)
        runtime = build_reference_query_owner_runtime(configuration, admission)
        from eom_workflow_runner.reference_query_routed_runtime import (
            build_routed_reference_query_owner_factory,
        )

        routed_factory = (
            None
            if routed_configuration is None
            else build_routed_reference_query_owner_factory(
                runtime, routed_configuration, configuration_guard=snapshots.assert_unchanged
            )
        )
        mixed_snapshots = None
        mixed_routed_factory = None
        public_snapshots = None
        public_routed_factory = None
        if mixed_raw is not None:
            from eom_workflow.reference_query_owner_configuration import (
                ReferenceQueryServiceConfigurationV2,
                require_mixed_reference_query_cohost,
            )
            from eom_workflow.reference_query_routed_owner_configuration import (
                parse_reference_query_installed_owner_selection,
            )

            mixed_snapshots = NumericalRuntimeFileSnapshots()
            current_mixed = mixed_snapshots.read(
                _MIXED_CONFIGURATION,
                sha256="sha256:" + hashlib.sha256(mixed_raw).hexdigest(),
                maximum=64 * 1024,
            )
            mixed_selection, mixed_routed = parse_reference_query_installed_owner_selection(
                current_mixed
            )
            if not isinstance(mixed_selection, ReferenceQueryServiceConfigurationV2):
                raise ValueError("REFERENCE_QUERY_MIXED_CONFIGURATION_UNAVAILABLE")
            require_mixed_reference_query_cohost(configuration, mixed_selection)
            mixed_runtime = build_reference_query_owner_runtime(mixed_selection, admission)
            if mixed_routed is not None:
                mixed_routed_factory = build_routed_reference_query_owner_factory(
                    mixed_runtime,
                    mixed_routed,
                    configuration_guard=mixed_snapshots.assert_unchanged,
                )
        if public_raw is not None:
            from eom_workflow.reference_query_owner_configuration import (
                ReferenceQueryPublicServiceConfiguration,
                require_public_reference_query_cohost,
            )
            from eom_workflow.reference_query_routed_owner_configuration import (
                PublicRoutedReferenceQueryOwnerConfiguration,
                parse_reference_query_installed_owner_selection,
            )

            public_snapshots = NumericalRuntimeFileSnapshots()
            current_public = public_snapshots.read(
                _PUBLIC_CONFIGURATION,
                sha256="sha256:" + hashlib.sha256(public_raw).hexdigest(),
                maximum=64 * 1024,
            )
            public_selection, public_routed = parse_reference_query_installed_owner_selection(
                current_public
            )
            if not isinstance(
                public_selection, ReferenceQueryPublicServiceConfiguration
            ) or not isinstance(public_routed, PublicRoutedReferenceQueryOwnerConfiguration):
                raise ValueError("REFERENCE_QUERY_PUBLIC_CONFIGURATION_UNAVAILABLE")
            require_public_reference_query_cohost(configuration, public_selection)
            public_runtime = build_reference_query_owner_runtime(public_selection, admission)
            public_routed_factory = build_routed_reference_query_owner_factory(
                public_runtime, public_routed, configuration_guard=public_snapshots.assert_unchanged
            )
        private_listener = None
        if private_raw is not None:
            from eom_orchestrator.private_chat_query_prepare_client import (
                fixed_private_chat_query_prepare_endpoint,
            )
            from eom_workflow.private_chat_query_owner_configuration import (
                parse_private_chat_query_service_configuration,
            )

            from eom_workflow_runner.private_chat_query_owner_runtime import (
                build_private_chat_query_owner_factory,
            )

            current_private = snapshots.read(
                _PRIVATE_CONFIGURATION,
                sha256="sha256:" + hashlib.sha256(private_raw).hexdigest(),
                maximum=16 * 1024,
            )
            private_factory = build_private_chat_query_owner_factory(
                runtime,
                parse_private_chat_query_service_configuration(current_private),
                configuration_guard=snapshots.assert_unchanged,
            )
            private_listener = PrivateChatQueryListener(
                fixed_private_chat_query_prepare_endpoint(),
                pwd.getpwnam("eom-general-chat").pw_uid,
                private_factory,
            )
        if stop:
            return 0

        def application(capture: AuthenticatedOperatorSession) -> ReferenceQueryPreparationPort:
            snapshots.assert_unchanged()
            assert runtime is not None
            from eom_workflow_runner.reference_query_family_selection import (
                ReferenceQueryFamilyPreparation,
            )
            from eom_workflow_runner.reference_query_routed_application import (
                RoutedNativeReferenceQueryPreparation,
            )

            def primary_application() -> ReferenceQueryPreparationPort:
                assert runtime is not None
                if routed_factory is not None:
                    return RoutedNativeReferenceQueryPreparation(routed_factory.session(capture))
                return runtime.application(capture)

            def mixed_application() -> ReferenceQueryPreparationPort:
                assert mixed_snapshots is not None and mixed_runtime is not None
                mixed_snapshots.assert_unchanged()
                if mixed_routed_factory is not None:
                    return RoutedNativeReferenceQueryPreparation(
                        mixed_routed_factory.session(capture)
                    )
                return mixed_runtime.application(capture)

            def public_application() -> ReferenceQueryPreparationPort:
                assert public_snapshots is not None and public_routed_factory is not None
                public_snapshots.assert_unchanged()
                return RoutedNativeReferenceQueryPreparation(public_routed_factory.session(capture))

            return ReferenceQueryFamilyPreparation(
                primary_application,
                None if mixed_runtime is None else mixed_application,
                None if public_runtime is None else public_application,
            )

        server = ReferenceQueryOwnerServer(
            endpoint=ChatSocketEndpoint(
                Path(REFERENCE_QUERY_PREPARE_SOCKET), owner.pw_uid, api.pw_gid, parent_mode=0o2750
            ),
            api_uid=api.pw_uid,
            admission=admission,
            application=application,
            private_queries=private_listener,
        )
        _emit("REFERENCE_QUERY_OWNER_READY")
        server.serve(stop_requested=lambda: stop)
        return 0
    except Exception as error:
        _emit("REFERENCE_QUERY_OWNER_STOPPED", error=error)
        return 1
    finally:
        if server is not None:
            server.close()
        if runtime is not None:
            runtime.close()
        if mixed_runtime is not None:
            mixed_runtime.close()
        if public_runtime is not None:
            public_runtime.close()


def _require_dropped_identity(uid: int, gid: int) -> None:
    """No saved root identity/capability may reach application imports or requests."""
    if (
        type(uid) is not int
        or type(gid) is not int
        or uid <= 0
        or gid <= 0
        or os.getresuid() != (uid, uid, uid)
        or os.getresgid() != (gid, gid, gid)
        or os.getgroups()
    ):
        raise ValueError("REFERENCE_QUERY_OWNER_CHILD_PRIVILEGES_RETAINED")
    with Path("/proc/self/status").open("rb") as stream:
        raw = stream.read(8193)
    fields: dict[bytes, bytes] = {}
    expected = {b"CapPrm", b"CapEff", b"CapAmb", b"NoNewPrivs"}
    for row in raw.splitlines():
        name, _, value = row.partition(b":")
        if name in expected:
            if name in fields:
                raise ValueError("REFERENCE_QUERY_OWNER_CHILD_PRIVILEGES_RETAINED")
            fields[name] = value.strip()
    if (
        len(raw) > 8192
        or set(fields) != expected
        or fields[b"NoNewPrivs"] != b"1"
        or any(
            re.fullmatch(rb"0{1,32}", fields[name]) is None
            for name in (b"CapPrm", b"CapEff", b"CapAmb")
        )
    ):
        raise ValueError("REFERENCE_QUERY_OWNER_CHILD_PRIVILEGES_RETAINED")


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
            ReferenceQueryServiceConfiguration,
        )
        from eom_workflow.reference_query_routed_owner_configuration import (
            parse_reference_query_installed_owner_selection,
        )

        raw = _configuration_bytes()
        configuration, routed_configuration = parse_reference_query_installed_owner_selection(raw)
        if not isinstance(configuration, ReferenceQueryServiceConfiguration):
            raise ValueError("REFERENCE_QUERY_OWNER_CONFIGURATION_UNAVAILABLE")
        if configuration.owner_source_commit != site.parent.name:
            raise ValueError("REFERENCE_QUERY_OWNER_SOURCE_MISMATCH")
        mixed_raw = _mixed_configuration_bytes()
        if mixed_raw is not None:
            from eom_workflow.reference_query_owner_configuration import (
                ReferenceQueryServiceConfigurationV2,
                require_mixed_reference_query_cohost,
            )

            mixed_selection, _mixed_routed = parse_reference_query_installed_owner_selection(
                mixed_raw
            )
            if not isinstance(mixed_selection, ReferenceQueryServiceConfigurationV2):
                raise ValueError("REFERENCE_QUERY_MIXED_CONFIGURATION_UNAVAILABLE")
            require_mixed_reference_query_cohost(configuration, mixed_selection)
        private_raw = _private_configuration_bytes()
        public_raw = _public_configuration_bytes()
        if public_raw is not None:
            from eom_workflow.reference_query_owner_configuration import (
                ReferenceQueryPublicServiceConfiguration,
                require_public_reference_query_cohost,
            )
            from eom_workflow.reference_query_routed_owner_configuration import (
                PublicRoutedReferenceQueryOwnerConfiguration,
            )

            public_selection, public_routed = parse_reference_query_installed_owner_selection(
                public_raw
            )
            if not isinstance(
                public_selection, ReferenceQueryPublicServiceConfiguration
            ) or not isinstance(public_routed, PublicRoutedReferenceQueryOwnerConfiguration):
                raise ValueError("REFERENCE_QUERY_PUBLIC_CONFIGURATION_UNAVAILABLE")
            require_public_reference_query_cohost(configuration, public_selection)
        if private_raw is not None:
            from eom_workflow.private_chat_query_owner_configuration import (
                parse_private_chat_query_service_configuration,
                require_private_chat_query_reference_configuration,
            )

            require_private_chat_query_reference_configuration(
                parse_private_chat_query_service_configuration(private_raw), configuration
            )
            _provision_private_socket_parent()
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
                    private_raw=private_raw,
                    mixed_raw=mixed_raw,
                    public_raw=public_raw,
                    routed_configuration=routed_configuration,
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
