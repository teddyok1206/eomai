from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/workflow/manage_runner_scale_out.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("manage_runner_scale_out", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("scale-out module is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fixture(tmp_path: Path) -> tuple[ModuleType, Path, Path]:
    module = _load()
    source = tmp_path / "base.service"
    target_root = tmp_path / "run"
    target_root.mkdir(mode=0o755)
    source.write_bytes(b"[Service]\nExecStart=/bin/true\n")
    source.chmod(0o644)
    target = target_root / "accelerator.service"
    return module, source, target


def test_runtime_unit_publish_adopts_only_exact_bytes(tmp_path: Path) -> None:
    module, source, target = _fixture(tmp_path)
    expected = module._sha256(source.read_bytes())
    identity = {"expected_uid": os.getuid(), "expected_gid": os.getgid()}

    assert (
        module.publish_runtime_unit(source, target, expected_sha256=expected, **identity)
        == "CREATED"
    )
    assert target.read_bytes() == source.read_bytes()
    assert target.stat().st_nlink == 1
    assert target.stat().st_mode & 0o777 == 0o644
    assert (
        module.publish_runtime_unit(source, target, expected_sha256=expected, **identity)
        == "ADOPTED_EXACT_EXISTING"
    )


def test_runtime_unit_publish_rejects_conflict_and_symlink(tmp_path: Path) -> None:
    module, source, target = _fixture(tmp_path)
    expected = module._sha256(source.read_bytes())
    identity = {"expected_uid": os.getuid(), "expected_gid": os.getgid()}
    target.write_bytes(b"conflict")
    target.chmod(0o644)

    with pytest.raises(module.ScaleOutError, match="Conflicting"):
        module.publish_runtime_unit(source, target, expected_sha256=expected, **identity)

    target.unlink()
    target.symlink_to(source)
    with pytest.raises(module.ScaleOutError):
        module.publish_runtime_unit(source, target, expected_sha256=expected, **identity)


def test_runtime_unit_remove_is_exact_and_idempotent(tmp_path: Path) -> None:
    module, source, target = _fixture(tmp_path)
    expected = module._sha256(source.read_bytes())
    identity = {"expected_uid": os.getuid(), "expected_gid": os.getgid()}
    module.publish_runtime_unit(source, target, expected_sha256=expected, **identity)

    assert (
        module.remove_runtime_unit(source, target, expected_sha256=expected, **identity)
        == "REMOVED"
    )
    assert not target.exists()
    assert (
        module.remove_runtime_unit(source, target, expected_sha256=expected, **identity)
        == "ALREADY_ABSENT"
    )


def test_runtime_unit_rejects_source_hash_drift(tmp_path: Path) -> None:
    module, source, target = _fixture(tmp_path)
    identity = {"expected_uid": os.getuid(), "expected_gid": os.getgid()}

    with pytest.raises(module.ScaleOutError, match="hash mismatch"):
        module.publish_runtime_unit(
            source,
            target,
            expected_sha256="sha256:" + "0" * 64,
            **identity,
        )


def test_scale_out_script_pins_deployment_fenced_unit_family() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    deployment = (ROOT / "scripts/api/deploy_release.sh").read_text(encoding="utf-8")
    canonical_unit = (ROOT / "infra/systemd/eom-workflow-runner.service").read_bytes()
    module = _load()

    assert module.ACCELERATOR_UNIT_NAME == "eom-workflow-runner-accelerator.service"
    assert '"eom-workflow-runner-*.service"' in deployment
    assert (
        'WORKFLOW_RUNNER_ACCELERATOR_RUNTIME_UNIT="/run/systemd/system/'
        'eom-workflow-runner-accelerator.service"' in deployment
    )
    assert "require_no_staged_workflow_runner_accelerator" in deployment
    assert module._sha256(canonical_unit) == module.EXPECTED_UNIT_SHA256
    assert "os.link(temporary, target, follow_symlinks=False)" in source
    assert '_systemctl("daemon-reload")' in source
    assert '_systemctl("start", ACCELERATOR_UNIT_NAME)' in source
    assert '_systemctl("stop", ACCELERATOR_UNIT_NAME)' in source
    assert '"eom-workflow-runner-*.service"' in source


def test_staged_accelerator_is_an_explicit_inactive_state() -> None:
    module = _load()
    module._require_staged_accelerator(
        {
            "LoadState": "loaded",
            "FragmentPath": str(module.ACCELERATOR_UNIT_PATH),
            "DropInPaths": "",
            "User": "eom-workflow-runner",
            "Group": "eom",
            "ActiveState": "inactive",
            "SubState": "dead",
            "MainPID": "0",
            "NRestarts": "0",
            "ExecMainStatus": "0",
        }
    )

    with pytest.raises(module.ScaleOutError, match="inactive"):
        module._require_staged_accelerator(
            {
                "LoadState": "loaded",
                "FragmentPath": str(module.ACCELERATOR_UNIT_PATH),
                "DropInPaths": "",
                "User": "eom-workflow-runner",
                "Group": "eom",
                "ActiveState": "activating",
                "SubState": "start",
                "MainPID": "123",
                "NRestarts": "0",
                "ExecMainStatus": "0",
            }
        )


def test_active_transient_inventory_is_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load()
    monkeypatch.setattr(
        module,
        "_systemctl",
        lambda *_arguments, **_keywords: SimpleNamespace(
            stdout=("eom-workflow-runner-accelerator.service loaded active running description\n")
        ),
    )
    assert module._active_transient_units() == frozenset(
        {"eom-workflow-runner-accelerator.service"}
    )

    monkeypatch.setattr(
        module,
        "_systemctl",
        lambda *_arguments, **_keywords: SimpleNamespace(
            stdout="foreign.service loaded active running description\n"
        ),
    )
    with pytest.raises(module.ScaleOutError, match="unexpected"):
        module._active_transient_units()
