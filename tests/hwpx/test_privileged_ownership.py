from __future__ import annotations

import os
import pwd
from pathlib import Path

import pytest
from eom_hwpx_manager.adapter import HwpxBuilderAdapter
from eom_hwpx_manager.settings import HwpxSettings

pytestmark = [
    pytest.mark.integration,
    pytest.mark.privileged,
    pytest.mark.hwpx_privileged,
]


def test_hwpx_workspace_and_staged_file_receive_builder_ownership(tmp_path: Path) -> None:
    if os.environ.get("EOM_RUN_HWPX_PRIVILEGED") != "1":
        pytest.skip("set EOM_RUN_HWPX_PRIVILEGED=1 for the isolated root ownership check")
    if os.geteuid() != 0:
        pytest.skip("HWPX ownership integration requires root in an isolated temporary workspace")

    account = pwd.getpwnam("eom-hwpx")
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    source = tmp_path / "input.json"
    source.write_text("{}", encoding="ascii")
    adapter = HwpxBuilderAdapter(
        HwpxSettings(workspace_root=workspace_root, builder_user="eom-hwpx")
    )

    workspace = adapter.create_workspace("hwpxbuild_" + "b" * 32)
    target = adapter.stage_file(workspace, "input/document.json", source)

    for path in (workspace, target.parent, target):
        metadata = path.stat()
        assert (metadata.st_uid, metadata.st_gid) == (account.pw_uid, account.pw_gid)
    assert target.stat().st_mode & 0o777 == 0o400
