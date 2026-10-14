"""Named runner access to exactly the existing Catalog runtime directory/socket."""

from __future__ import annotations

import os
import stat
import struct
from pathlib import Path

_UNDEFINED_ID = 2**32 - 1


def grant_catalog_workflow_socket_access(
    path: Path, *, runner_uid: int, owner_uid: int, group_gid: int
) -> None:
    """Catalog-owned startup side effect; no group membership or secret/file grant.

    Preserve existing 0750/0660 group permissions and add only a named user entry.
    The fixed private server must independently limit that UID to its one operation.
    """
    if (
        type(runner_uid) is not int
        or not 0 < runner_uid < _UNDEFINED_ID
        or runner_uid == owner_uid
        or not path.is_absolute()
        or ".." in path.parts
    ):
        raise ValueError("CATALOG_WORKFLOW_SOCKET_ACCESS_INVALID")
    prepared: list[tuple[Path, os.stat_result, bytes, bool]] = []
    for target, directory in ((path.parent, True), (path, False)):
        before = target.lstat()
        expected_mode = 0o750 if directory else 0o660
        if (
            not (stat.S_ISDIR(before.st_mode) if directory else stat.S_ISSOCK(before.st_mode))
            or before.st_uid != owner_uid
            or before.st_gid != group_gid
            or stat.S_IMODE(before.st_mode) != expected_mode
            or "system.posix_acl_default" in os.listxattr(target, follow_symlinks=False)
        ):
            raise ValueError("CATALOG_WORKFLOW_SOCKET_ACCESS_INVALID")
        permission = 5 if directory else 6
        acl = struct.pack("<I", 2) + b"".join(
            struct.pack("<HHI", tag, access, identity)
            for tag, access, identity in (
                (1, 7 if directory else 6, _UNDEFINED_ID),
                (2, permission, runner_uid),
                (4, permission, _UNDEFINED_ID),
                (16, permission, _UNDEFINED_ID),
                (32, 0, _UNDEFINED_ID),
            )
        )
        present = "system.posix_acl_access" in os.listxattr(target, follow_symlinks=False)
        # Exact replay is safe; never overwrite an unreviewed grant on restart.
        if present and os.getxattr(target, "system.posix_acl_access", follow_symlinks=False) != acl:
            raise ValueError("CATALOG_WORKFLOW_SOCKET_ACCESS_NOT_FRESH")
        prepared.append((target, before, acl, present))
    # Validate both targets before writing either grant. A bad socket must not
    # acquire directory traversal as a side effect of the rejected installation.
    for target, before, acl, present in prepared:
        current = target.lstat()
        if (current.st_dev, current.st_ino, current.st_mode, current.st_uid, current.st_gid) != (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_uid,
            before.st_gid,
        ):
            raise ValueError("CATALOG_WORKFLOW_SOCKET_ACCESS_CHANGED")
        if not present:
            os.setxattr(target, "system.posix_acl_access", acl, follow_symlinks=False)
        after = target.lstat()
        if (before.st_dev, before.st_ino, before.st_mode, before.st_uid, before.st_gid) != (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_uid,
            after.st_gid,
        ) or os.getxattr(target, "system.posix_acl_access", follow_symlinks=False) != acl:
            raise ValueError("CATALOG_WORKFLOW_SOCKET_ACCESS_CHANGED")
