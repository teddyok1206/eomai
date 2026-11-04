"""Catch a stale installed-wheel gate before an expensive release build."""

import ast
import re
from pathlib import Path

import pytest
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION


def _source_reader():
    root = Path(__file__).resolve().parents[2]
    source = (root / "scripts/api/deploy_release.sh").read_text()
    start = source.index("def source_migration_revision(root: Path)")
    stop = source.index("\nexpected_migration_revision =", start)
    namespace = {"ast": ast, "re": re, "Path": Path}
    exec(compile(ast.parse(source[start:stop]), "release-source-head-reader", "exec"), namespace)
    return root, source, namespace["source_migration_revision"]


def test_installed_simulation_expected_head_matches_the_reviewed_source_head():
    root, source, reader = _source_reader()
    assert reader(root) == CURRENT_MIGRATION_REVISION
    assert (
        'expected_migration_revision = source_migration_revision('
        'Path(os.environ["REPOSITORY_ROOT"]))'
        in source
    )
    assert "expected_migration_revision = sys.argv.pop()" in source
    assert "if CURRENT_MIGRATION_REVISION != expected_migration_revision:" in source


@pytest.mark.parametrize(
    "declaration",
    [
        "CURRENT_MIGRATION_REVISION = 'not-a-revision'",
        "CURRENT_MIGRATION_REVISION = '20261104_0072'\n"
        "CURRENT_MIGRATION_REVISION = '20261103_0071'",
        "CURRENT_MIGRATION_REVISION = 72",
        "# no declared head",
    ],
)
def test_source_head_reader_rejects_missing_duplicate_or_invalid_declaration(tmp_path, declaration):
    _root, _source, reader = _source_reader()
    path = tmp_path / "services/orchestrator/eom_orchestrator/migration.py"
    path.parent.mkdir(parents=True)
    path.write_text(declaration)
    with pytest.raises(SystemExit, match="declaration is invalid"):
        reader(tmp_path)


def test_source_head_reader_does_not_execute_source_expressions(tmp_path):
    _root, _source, reader = _source_reader()
    path = tmp_path / "services/orchestrator/eom_orchestrator/migration.py"
    path.parent.mkdir(parents=True)
    marker = tmp_path / "must-not-exist"
    path.write_text(f"CURRENT_MIGRATION_REVISION = Path({str(marker)!r}).touch()")
    with pytest.raises(SystemExit, match="declaration is invalid"):
        reader(tmp_path)
    assert not marker.exists()
