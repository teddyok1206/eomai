from __future__ import annotations

from eomctl.cli import app
from typer.testing import CliRunner


def test_legacy_usage_operator_commands_are_bounded_and_explicit() -> None:
    runner = CliRunner()

    root = runner.invoke(app, ["usage", "legacy", "--help"])
    assert root.exit_code == 0
    for command in ("mapping", "import", "review", "item-history"):
        assert command in root.stdout

    imports = runner.invoke(app, ["usage", "legacy", "import", "--help"])
    assert imports.exit_code == 0
    for command in ("create", "inspect", "proposals", "commit"):
        assert command in imports.stdout

    proposals = runner.invoke(
        app,
        [
            "usage",
            "legacy",
            "import",
            "proposals",
            "legacyimport_" + "1" * 32,
            "--help",
        ],
    )
    assert proposals.exit_code == 0
    assert "--limit" in proposals.stdout
    assert "--after-row-number" in proposals.stdout
