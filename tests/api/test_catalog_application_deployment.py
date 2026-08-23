from __future__ import annotations

import importlib.util
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


def test_catalog_manager_secret_projection_contains_only_database_url() -> None:
    installer = _installer()
    values = installer._parse_source(  # type: ignore[attr-defined]
        b"EOM_API_DATABASE_URL=postgresql://synthetic.invalid/eom\n"
        b"EOM_API_TOKEN_HASH_KEY=synthetic-token-key\n"
        b"EOM_API_FINGERPRINT_KEY=synthetic-fingerprint-key\n"
    )

    projected = f"EOM_DATABASE_URL={values['EOM_API_DATABASE_URL']}\n"
    assert projected == "EOM_DATABASE_URL=postgresql://synthetic.invalid/eom\n"
    assert "TOKEN" not in projected
    assert "FINGERPRINT" not in projected


def test_catalog_manager_secret_projection_rejects_extra_keys() -> None:
    installer = _installer()
    with pytest.raises(SystemExit, match="key set is invalid"):
        installer._parse_source(  # type: ignore[attr-defined]
            b"EOM_API_DATABASE_URL=postgresql://synthetic.invalid/eom\n"
            b"EOM_API_TOKEN_HASH_KEY=synthetic-token-key\n"
            b"EOM_API_FINGERPRINT_KEY=synthetic-fingerprint-key\n"
            b"UNEXPECTED=value\n"
        )


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
