from __future__ import annotations

import grp
import os
import pwd
import stat
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_orchestrator.errors import PlatformError
from eom_orchestrator.settings import Settings
from eom_orchestrator.worker import CodexWorkerAdapter
from eom_orchestrator.worker_entry import finalize_result
from eom_orchestrator.worker_entry import main as worker_entry_main
from eom_orchestrator.worker_registry import WorkerSlot


def _settings(tmp_path: Path) -> Settings:
    workspaces = tmp_path / "workspaces"
    workspaces.mkdir()
    return Settings(
        worker_config=Path("config/worker-slots.example.yaml").resolve(),
        staging_root=tmp_path / "staging",
        workspace_root=workspaces,
        worker_home_root=tmp_path / "homes",
        nas_artifact_root=tmp_path / "artifacts",
        codex_binary=Path("/usr/local/bin/codex"),
    )


def _identity(monkeypatch: pytest.MonkeyPatch) -> tuple[int, int]:
    uid = os.getuid() + 1000
    gid = os.getgid()
    monkeypatch.setattr(pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=uid, pw_gid=gid))
    monkeypatch.setattr(grp, "getgrnam", lambda _: SimpleNamespace(gr_gid=gid))
    return uid, gid


def _worker_root(settings: Settings, gid: int) -> Path:
    root = settings.workspace_root / "eom-cdx-01"
    root.mkdir(mode=0o2770)
    os.chown(root, -1, gid)
    root.chmod(0o2770)
    return root


def test_workspace_uses_private_group_without_cross_uid_chown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    worker_uid, worker_gid = _identity(monkeypatch)
    _worker_root(settings, worker_gid)
    calls: list[tuple[int, int]] = []
    real_chown = os.chown

    def record_chown(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes], uid: int, gid: int
    ) -> None:
        calls.append((uid, gid))
        assert uid == -1 and gid == worker_gid and uid != worker_uid
        real_chown(path, uid, gid)

    monkeypatch.setattr(os, "chown", record_chown)
    adapter = CodexWorkerAdapter(settings)
    workspace, schema, prompt = adapter._prepare_workspace_document(
        job_id="job_0123456789abcdef0123456789abcdef",
        input_document={"test": True},
        output_schema={"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"},
        prompt_text="PLACEHOLDER",
        slot=WorkerSlot(slot_id="01", linux_user="eom-cdx-01", role="authoring", enabled=True),
    )

    assert stat.S_IMODE(workspace.stat().st_mode) == 0o2770
    assert workspace.stat().st_gid == worker_gid
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o640
        for path in (schema, prompt, workspace / "worker-input.json")
    )
    assert calls and all(uid == -1 for uid, _ in calls)


def test_workspace_rejects_symlink_and_non_setgid_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _, gid = _identity(monkeypatch)
    real = tmp_path / "real"
    real.mkdir()
    (settings.workspace_root / "eom-cdx-01").symlink_to(real, target_is_directory=True)
    adapter = CodexWorkerAdapter(settings)
    arguments = {
        "job_id": "job_0123456789abcdef0123456789abcdef",
        "input_document": {"test": True},
        "output_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
        },
        "prompt_text": "PLACEHOLDER",
        "slot": WorkerSlot(slot_id="01", linux_user="eom-cdx-01", role="authoring", enabled=True),
    }
    with pytest.raises(PlatformError, match="private-group boundary"):
        adapter._prepare_workspace_document(**arguments)  # type: ignore[arg-type]

    (settings.workspace_root / "eom-cdx-01").unlink()
    root = settings.workspace_root / "eom-cdx-01"
    root.mkdir(mode=0o770)
    os.chown(root, -1, gid)
    root.chmod(0o770)
    with pytest.raises(PlatformError, match="private-group boundary"):
        adapter._prepare_workspace_document(**arguments)  # type: ignore[arg-type]


def test_worker_command_starts_only_fixed_template_instance(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    adapter = CodexWorkerAdapter(settings)
    argv = adapter._argv(
        slot=WorkerSlot(slot_id="01", linux_user="eom-cdx-01", role="authoring", enabled=True),
        job_id="job_0123456789abcdef0123456789abcdef",
    )

    assert argv == [
        "/usr/bin/systemctl",
        "--no-ask-password",
        "--wait",
        "start",
        "eom-worker-01@job_0123456789abcdef0123456789abcdef.service",
    ]
    assert "systemd-run" not in argv
    assert not any(value.startswith(("--uid", "--gid", "--property")) for value in argv)


def test_worker_result_finalization_makes_result_group_readable(tmp_path: Path) -> None:
    result = tmp_path / "result.json"
    result.write_text("{}", encoding="ascii")
    result.chmod(0o600)

    finalize_result(result, tmp_path)

    assert stat.S_IMODE(result.stat().st_mode) == 0o640


def test_worker_result_finalization_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="ascii")
    result = tmp_path / "result.json"
    result.symlink_to(target)

    with pytest.raises(OSError):
        finalize_result(result, tmp_path)


def test_worker_entry_normalizes_result_inside_worker_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = tmp_path / "result.json"
    code = (
        "from pathlib import Path; p=Path('result.json'); "
        "p.write_text('{}', encoding='ascii'); p.chmod(0o600)"
    )
    monkeypatch.chdir(tmp_path)
    with tempfile.TemporaryFile() as prompt:
        monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=prompt))
        exit_code = worker_entry_main(["--result", str(result), "--", sys.executable, "-c", code])

    assert exit_code == 0
    assert stat.S_IMODE(result.stat().st_mode) == 0o640
