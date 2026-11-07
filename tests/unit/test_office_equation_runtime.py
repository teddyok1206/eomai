"""Closed fixed-unit/profile deployment surface, no live systemd mutation."""

from pathlib import Path

import pytest
from eom_catalog_service.office_conversion_profiles import (
    CHOICE_LAYOUT_OFFICE_PROFILE,
    EQUATION_OFFICE_PROFILE,
    LEGACY_OFFICE_PROFILE,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("unit", "profile", "argument"),
    [
        ("eom-office-equation-converter@.service", EQUATION_OFFICE_PROFILE, "--equations-v2"),
        ("eom-office-choice-converter@.service", CHOICE_LAYOUT_OFFICE_PROFILE, "--choices-v3"),
    ],
)
def test_corrected_unit_keeps_the_legacy_sandbox_and_uses_a_fixed_profile(
    unit, profile, argument
) -> None:
    legacy = (ROOT / "infra/systemd/eom-office-converter@.service").read_text()
    current = (ROOT / "infra/systemd" / unit).read_text()
    for marker in (
        "User=eom-catalog-manager",
        "Group=eom-api",
        "PrivateNetwork=true",
        "PrivateTmp=true",
        "NoNewPrivileges=true",
        "ProtectSystem=strict",
        "ProtectHome=true",
        "CapabilityBoundingSet=",
        "InaccessiblePaths=/mnt/nas",
        "InaccessiblePaths=/etc/eom",
        "InaccessiblePaths=/home/eom/EOM",
        "InaccessiblePaths=/srv/eom/worker-homes",
        "RestrictAddressFamilies=AF_UNIX",
        "CPUQuota=200%",
    ):
        assert marker in legacy and marker in current
    assert argument + " %i" in current
    assert str(profile.h2orestart_bundle) in current
    assert str(LEGACY_OFFICE_PROFILE.h2orestart_bundle) in legacy
    assert "SupplementaryGroups=eom" not in current


@pytest.mark.parametrize(
    ("rule_name", "prefix"),
    [
        ("45-eom-office-equations.rules", "eom-office-equation-converter"),
        ("45-eom-office-choices.rules", "eom-office-choice-converter"),
    ],
)
def test_new_profile_rule_does_not_change_the_shared_worker_allowlist(rule_name, prefix) -> None:
    rule_path = ROOT / "infra/polkit" / rule_name
    rule = rule_path.read_text()
    assert rule_path.name < "50-eom-worker-units.rules"
    assert 'subject.user === "eom-catalog-manager"' in rule
    assert 'action.lookup("verb") === "start"' in rule
    assert "^" + prefix + r"@officeconv_[0-9a-f]{32}\.service$" in rule
    assert "return polkit.Result.NOT_HANDLED" in rule
    assert 'subject.user === "eom-codex' not in rule


def test_installer_pins_bundle_source_and_does_not_restart_other_services() -> None:
    script = (ROOT / "scripts/catalog/install_office_equation_converter.sh").read_text()
    template = (ROOT / "infra/systemd/eom-office-equation-installed-release.conf.in").read_text()
    assert EQUATION_OFFICE_PROFILE.h2orestart_sha256 in script
    assert CHOICE_LAYOUT_OFFICE_PROFILE.h2orestart_sha256 in script
    assert "--verify" in script and "--source-commit" in script
    assert "stat -c '%U:%G:%a'" in script and "cmp -s" in script
    assert "systemctl daemon-reload" in script
    assert "systemctl restart" not in script and "systemctl stop" not in script
    assert "-I -B -c" in template and "is_relative_to" in template
    assert "@EOM_EQUATION_SOURCE@" in template and "--equations-v2 %i" in template


def test_current_ui_preview_does_not_reinterpret_frozen_learning_inputs() -> None:
    import ast

    source = (
        ROOT / "services/catalog_service/eom_catalog_service/application_runner.py"
    ).read_text()
    tree = ast.parse(source)
    authorization = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "CatalogExternalItemLearningAuthorizationService"
    )
    assert isinstance(authorization.args[1], ast.Call)
    assert isinstance(authorization.args[1].func, ast.Name)
    assert authorization.args[1].func.id == "ExternalItemPreviewProjectionService"
    assert not authorization.args[1].keywords  # Frozen learning keeps the legacy default.
    assert "engine, profile=CHOICE_LAYOUT_OFFICE_PROFILE" in source


@pytest.mark.parametrize(
    ("argument", "profile"),
    [
        ("--equations-v2", EQUATION_OFFICE_PROFILE),
        ("--choices-v3", CHOICE_LAYOUT_OFFICE_PROFILE),
    ],
)
def test_fixed_worker_argument_selects_only_its_own_bundle(monkeypatch, argument, profile) -> None:
    from unittest.mock import Mock

    from eom_catalog_service import office_converter_worker as worker

    convert, outcome = Mock(), Mock()
    monkeypatch.setattr(worker, "convert_workspace", convert)
    monkeypatch.setattr(worker, "_write_outcome", outcome)
    instance = "officeconv_" + "a" * 32
    assert worker.main([argument, instance]) == 0
    convert.assert_called_once_with(
        instance,
        h2orestart_bundle=profile.h2orestart_bundle,
        h2orestart_bundle_sha256=profile.h2orestart_sha256,
        pdf_quality_validator=worker.require_office_pdf_math_quality,
    )
    outcome.assert_called_once_with(
        instance, error=None, h2orestart_bundle=profile.h2orestart_bundle
    )
    assert worker.main(["--arbitrary", instance]) == 64
