"""A later shared install must not leave a scoped API shadowing new packages."""

from pathlib import Path


def test_shared_installer_rejects_scoped_api_before_any_runtime_mutation() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "scripts/api/deploy_release.sh").read_text()
    guard = source.index("Scoped API release is active;")
    assert source.index('if [[ "$ACTION" == "install"') < guard
    assert "45-eom-api-installed-release.conf" in source[:guard]
    assert guard < source.index('[[ -r "${WORKFLOW_RUNNER_HOLD_LIBRARY}" ]]')
    assert (root / "docs/operations/ITEM_DB_REGISTRATION_PARITY_RELEASE_2026-10-31.md").is_file()
