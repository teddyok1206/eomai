from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest
from eom_web_gui import release_integrity
from eom_web_gui.release_integrity import ReleaseIntegrityError, verify_recorded_package_files

ROOT = Path(__file__).resolve().parents[2]


def _descriptor(path: Path) -> str:
    digest = (
        base64.urlsafe_b64encode(hashlib.sha256(path.read_bytes()).digest()).decode().rstrip("=")
    )
    return f"sha256={digest},{path.stat().st_size}"


def _record(root: Path, relative_files: tuple[str, ...]) -> str:
    return "\n".join(
        f"eom_web_gui/{name},{_descriptor(root / 'eom_web_gui' / name)}" for name in relative_files
    )


def test_release_inventory_exactly_covers_source_runtime_files() -> None:
    package_root = ROOT / "apps/web_gui/eom_web_gui"
    assert not [path for path in package_root.rglob("*") if path.is_symlink()]
    observed = {
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
    }

    assert observed == release_integrity.REQUIRED_RUNTIME_FILES


def test_installed_release_verifier_checks_record_hashes_and_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "eom_web_gui"
    static = package / "static"
    static.mkdir(parents=True)
    (package / "__init__.py").write_text("VERSION = 'test'\n", encoding="utf-8")
    (static / "app.js").write_text("export const ready = true;\n", encoding="utf-8")
    files = ("__init__.py", "static/app.js")
    monkeypatch.setattr(release_integrity, "REQUIRED_RUNTIME_FILES", frozenset(files))
    record = _record(tmp_path, files)

    assert (
        verify_recorded_package_files(
            distribution_root=tmp_path,
            package_root=package,
            record_text=record,
        )
        == 2
    )

    (static / "app.js").write_text("export const ready = null;\n", encoding="utf-8")
    with pytest.raises(ReleaseIntegrityError, match="hash differs"):
        verify_recorded_package_files(
            distribution_root=tmp_path,
            package_root=package,
            record_text=record,
        )


def test_installed_release_verifier_rejects_recorded_unknown_package_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "eom_web_gui"
    package.mkdir()
    (package / "__init__.py").write_text("VERSION = 'test'\n", encoding="utf-8")
    (package / "unknown.py").write_text("VALUE = 'unexpected'\n", encoding="utf-8")
    monkeypatch.setattr(
        release_integrity,
        "REQUIRED_RUNTIME_FILES",
        frozenset({"__init__.py"}),
    )
    record = _record(tmp_path, ("__init__.py", "unknown.py"))

    with pytest.raises(ReleaseIntegrityError, match="unknown entries"):
        verify_recorded_package_files(
            distribution_root=tmp_path,
            package_root=package,
            record_text=record,
        )


def test_installed_release_verifier_rejects_stale_unrecorded_static_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "eom_web_gui"
    package.mkdir()
    (package / "__init__.py").write_text("VERSION = 'test'\n", encoding="utf-8")
    monkeypatch.setattr(
        release_integrity,
        "REQUIRED_RUNTIME_FILES",
        frozenset({"__init__.py"}),
    )
    record = _record(tmp_path, ("__init__.py",))
    (package / "removed-feature.js").write_text("stale\n", encoding="utf-8")

    with pytest.raises(ReleaseIntegrityError, match="unrecorded"):
        verify_recorded_package_files(
            distribution_root=tmp_path,
            package_root=package,
            record_text=record,
        )
