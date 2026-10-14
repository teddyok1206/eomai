"""Real local POSIX ACL writes only; no system identity, group or production path changes."""

import os
import socket
import struct
from types import SimpleNamespace

import pytest
from eom_catalog_service.application_server import CatalogApplicationServer
from eom_catalog_service.catalog_workflow_socket_access import grant_catalog_workflow_socket_access


def socket_case(tmp_path):
    directory = tmp_path / "runtime"
    directory.mkdir(mode=0o750)
    directory.chmod(0o750)
    path = directory / "manager.sock"
    connection = socket.socket(socket.AF_UNIX)
    connection.bind(str(path))
    path.chmod(0o660)
    return path, connection


def test_named_uid_only_keeps_modes_and_exact_replay(tmp_path):
    path, connection = socket_case(tmp_path)
    uid = os.getuid() + 100000
    try:
        for _ in range(2):
            grant_catalog_workflow_socket_access(
                path, runner_uid=uid, owner_uid=os.getuid(), group_gid=os.getgid()
            )
        for target, expected in ((path.parent, 0o750), (path, 0o660)):
            assert target.stat().st_mode & 0o777 == expected
            raw = os.getxattr(target, "system.posix_acl_access", follow_symlinks=False)
            assert struct.unpack_from("<HHI", raw, 12)[2] == uid
            assert "system.posix_acl_default" not in os.listxattr(target)
    finally:
        connection.close()


@pytest.mark.parametrize("enabled", (False, True))
def test_actual_server_constructor_grants_only_separately_enabled_runner(tmp_path, enabled):
    directory = tmp_path / "server-runtime"
    directory.mkdir(mode=0o750)
    directory.chmod(0o750)
    server = CatalogApplicationServer(
        *(SimpleNamespace() for _ in range(5)),
        workflow_similarity_reads=SimpleNamespace(read=lambda request: None) if enabled else None,
        workflow_runner_uid=os.getuid() + 100000,
        chat_owner_uid=os.getuid() + 200001,
        allowed_uid=os.getuid() + 200000,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
        socket_path=directory / "manager.sock",
    )
    try:
        for path in (directory, server.socket_path):
            assert ("system.posix_acl_access" in os.listxattr(path)) is enabled
        assert server.workflow_runner_uid == (os.getuid() + 100000 if enabled else None)
    finally:
        server.server_close()


@pytest.mark.parametrize(
    "fault", ("root", "owner", "wrong_owner", "wrong_group", "mode", "symlink", "existing_grant")
)
def test_invalid_or_existing_grants_fail_without_overwriting(tmp_path, fault):
    path, connection = socket_case(tmp_path)
    uid, owner, group = os.getuid() + 100000, os.getuid(), os.getgid()
    try:
        if fault == "root":
            uid = 0
        elif fault == "owner":
            uid = owner
        elif fault == "wrong_owner":
            owner += 1
        elif fault == "wrong_group":
            group += 1
        elif fault == "mode":
            path.chmod(0o666)
        elif fault == "symlink":
            alias = path.parent / "alias.sock"
            alias.symlink_to(path)
            path = alias
        else:
            grant_catalog_workflow_socket_access(
                path, runner_uid=uid + 1, owner_uid=owner, group_gid=group
            )
        before = {
            target: os.getxattr(target, "system.posix_acl_access", follow_symlinks=False)
            for target in (path.parent, path)
            if "system.posix_acl_access" in os.listxattr(target, follow_symlinks=False)
        }
        with pytest.raises((ValueError, OSError)):
            grant_catalog_workflow_socket_access(
                path, runner_uid=uid, owner_uid=owner, group_gid=group
            )
        for target, raw in before.items():
            assert os.getxattr(target, "system.posix_acl_access", follow_symlinks=False) == raw
        for target in (path.parent, path):
            if target not in before:
                assert "system.posix_acl_access" not in os.listxattr(target, follow_symlinks=False)
    finally:
        connection.close()
