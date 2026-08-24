from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _installer() -> ModuleType:
    path = REPOSITORY_ROOT / "scripts/catalog/install_application_runner.py"
    specification = importlib.util.spec_from_file_location("catalog_application_installer", path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _bootstrapper() -> ModuleType:
    path = REPOSITORY_ROOT / "scripts/catalog/bootstrap_runtime_role.py"
    specification = importlib.util.spec_from_file_location("catalog_runtime_bootstrap", path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _runtime_secret(path: Path, *, username: str, hostname: str = "127.0.0.1") -> None:
    path.write_text(
        f"EOM_DATABASE_URL=postgresql+psycopg://{username}:synthetic@{hostname}:5432/eom\n",
        encoding="utf-8",
    )
    path.chmod(0o640)


def test_catalog_manager_accepts_only_its_dedicated_database_identity() -> None:
    installer = _installer()
    installer._validate_catalog_secret(
        b"EOM_DATABASE_URL=postgresql+psycopg://"
        b"eom_catalog_manager_runtime:synthetic@127.0.0.1:5432/eom\n"
    )


def test_catalog_manager_secret_projection_rejects_extra_keys() -> None:
    installer = _installer()
    with pytest.raises(SystemExit, match="key set is invalid"):
        installer._validate_catalog_secret(
            b"EOM_DATABASE_URL=postgresql+psycopg://"
            b"eom_catalog_manager_runtime:synthetic@127.0.0.1:5432/eom\n"
            b"UNEXPECTED=value\n"
        )


def test_catalog_manager_rejects_api_or_remote_database_identity() -> None:
    installer = _installer()
    for value in (
        b"postgresql+psycopg://eom_api_runtime:synthetic@127.0.0.1:5432/eom",
        b"postgresql+psycopg://eom_catalog_manager_runtime:synthetic@db.invalid:5432/eom",
    ):
        with pytest.raises(SystemExit, match="identity is invalid"):
            installer._validate_catalog_secret(b"EOM_DATABASE_URL=" + value + b"\n")


def test_catalog_runtime_role_bootstrap_is_exact_and_separate_from_api() -> None:
    source = (REPOSITORY_ROOT / "scripts/catalog/bootstrap_runtime_role.py").read_text(
        encoding="utf-8"
    )

    assert 'ROLE = "eom_catalog_manager_runtime"' in source
    assert 'LEGACY_ROLE = "eom_api_runtime"' in source
    assert "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA app" in source
    assert "TABLE_PRIVILEGES" in source
    assert "sql.Identifier(LEGACY_ROLE)" not in source
    assert "api.env" not in source
    assert "TOKEN_HASH" not in source
    assert "FINGERPRINT" not in source


def test_catalog_runtime_bootstrap_migrates_only_the_exact_legacy_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bootstrapper = _bootstrapper()
    target = tmp_path / "catalog-manager.env"
    monkeypatch.setattr(bootstrapper, "TARGET_ENV", target)

    _runtime_secret(target, username="eom_catalog_manager_runtime")
    assert bootstrapper._existing_password(os.getuid(), os.getgid(), "eom") == "synthetic"

    _runtime_secret(target, username="eom_api_runtime")
    assert bootstrapper._existing_password(os.getuid(), os.getgid(), "eom") is None

    for username, hostname in (
        ("unexpected_runtime", "127.0.0.1"),
        ("eom_api_runtime", "db.invalid"),
    ):
        _runtime_secret(target, username=username, hostname=hostname)
        with pytest.raises(SystemExit, match="database URL is invalid"):
            bootstrapper._existing_password(os.getuid(), os.getgid(), "eom")


def test_catalog_manager_unit_owns_nas_commit_boundary_without_api_secret() -> None:
    catalog_unit = (
        REPOSITORY_ROOT / "infra/systemd/eom-catalog-application-runner.service"
    ).read_text(encoding="utf-8")
    api_unit = (REPOSITORY_ROOT / "infra/systemd/eom-api.service").read_text(encoding="utf-8")

    assert "EnvironmentFile=/etc/eom/secrets/catalog-manager.env" in catalog_unit
    assert "User=eom-catalog-manager" in catalog_unit
    assert "SupplementaryGroups=eom" in catalog_unit
    assert "ReadWritePaths=/srv/eom/staging/catalog" in catalog_unit
    assert "ReadWritePaths=/mnt/nas/eom/artifacts" in catalog_unit
    assert "InaccessiblePaths=/etc/eom/secrets/api.env" in catalog_unit
    assert "EnvironmentFile=/etc/eom/secrets/catalog-manager.env" not in api_unit
    assert "ReadWritePaths=/srv/eom/staging/catalog" not in api_unit
    assert "ReadWritePaths=/mnt/nas" not in api_unit
    client = (
        REPOSITORY_ROOT / "apps/application_api/eom_api/services/catalog_application_client.py"
    ).read_text(encoding="utf-8")
    assert 'pwd.getpwnam("eom-catalog-manager")' in client


def test_standalone_catalog_runner_resolves_every_registered_foreign_key() -> None:
    probe = """
import eom_catalog_service.application_runner
from eom_orchestrator.models import Base

assert "operators" in Base.metadata.tables
for table in Base.metadata.tables.values():
    for foreign_key in table.foreign_keys:
        foreign_key.column
"""
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )

    assert completed.returncode == 0, completed.stderr
