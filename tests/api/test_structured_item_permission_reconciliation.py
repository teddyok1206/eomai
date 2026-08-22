from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from eom_operator_identity import ROLE_PERMISSIONS, PermissionKey, RoleKey

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _reconciler() -> ModuleType:
    path = REPOSITORY_ROOT / "scripts/api/reconcile_structured_item_permission.py"
    specification = importlib.util.spec_from_file_location(
        "structured_item_permission_reconciler",
        path,
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _expected() -> tuple[set[str], set[str], set[tuple[str, str]]]:
    roles = {role.value for role in RoleKey}
    permissions = {permission.value for permission in PermissionKey}
    pairs = {
        (role.value, permission.value)
        for role, role_permissions in ROLE_PERMISSIONS.items()
        for permission in role_permissions
    }
    return roles, permissions, pairs


def test_reconciliation_allows_only_new_structured_item_admin_delta() -> None:
    reconciler = _reconciler()
    roles, permissions, pairs = _expected()
    new_permission = PermissionKey.ITEM_STRUCTURED_CONTENT_IMPORT.value

    assert reconciler.verify_allowed_delta(  # type: ignore[attr-defined]
        roles,
        permissions - {new_permission},
        pairs - {(RoleKey.ADMIN.value, new_permission)},
    ) == (1, 1)
    assert reconciler.verify_allowed_delta(roles, permissions, pairs) == (0, 0)  # type: ignore[attr-defined]


def test_reconciliation_rejects_unrelated_or_unexpected_rbac_drift() -> None:
    reconciler = _reconciler()
    roles, permissions, pairs = _expected()

    with pytest.raises(SystemExit, match="unrelated missing permission"):
        reconciler.verify_allowed_delta(  # type: ignore[attr-defined]
            roles,
            permissions - {PermissionKey.ITEM_READ.value},
            pairs,
        )
    with pytest.raises(SystemExit, match="unexpected permission"):
        reconciler.verify_allowed_delta(  # type: ignore[attr-defined]
            roles,
            permissions | {"unexpected:permission"},
            pairs,
        )
    with pytest.raises(SystemExit, match="unrelated missing role-permission"):
        reconciler.verify_allowed_delta(  # type: ignore[attr-defined]
            roles,
            permissions,
            pairs - {(RoleKey.ADMIN.value, PermissionKey.ITEM_READ.value)},
        )


def test_reconciler_is_root_only_clean_head_bound_and_secret_safe() -> None:
    source = (REPOSITORY_ROOT / "scripts/api/reconcile_structured_item_permission.py").read_text(
        encoding="utf-8"
    )

    assert "os.geteuid() != 0" in source
    assert '"status", "--porcelain"' in source
    assert "O_NOFOLLOW" in source
    assert "EOM_API_DATABASE_URL" in source
    assert "print(values" not in source
    assert "seed_builtin_rbac(session)" in source
