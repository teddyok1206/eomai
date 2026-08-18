from pathlib import Path

import pytest
from eom_catalog_service.workflow_catalog import _prepare_prompt_staging


def test_runtime_requires_bootstrapped_prompt_staging_root(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    catalog.mkdir(mode=0o750)
    prompt_staging = catalog / "workflow-prompts"

    with pytest.raises(OSError, match="prompt staging root is not prepared"):
        _prepare_prompt_staging(prompt_staging, "workflow_test", "authoring", 1)

    assert not (catalog / "workflow-prompts").exists()


def test_runtime_creates_only_workflow_and_attempt_directories(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    prompt_staging = catalog / "workflow-prompts"
    prompt_staging.mkdir(parents=True, mode=0o750)
    prompt_staging.chmod(0o750)

    staging = _prepare_prompt_staging(prompt_staging, "workflow_test", "authoring", 1)

    assert staging == prompt_staging / "workflow_test" / "authoring-1"
    assert staging.stat().st_mode & 0o777 == 0o750
    assert staging.parent.stat().st_mode & 0o777 == 0o750
    assert prompt_staging.stat().st_mode & 0o777 == 0o750


def test_runtime_rejects_prompt_staging_symlink(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    (catalog / "workflow-prompts").symlink_to(tmp_path)

    with pytest.raises(OSError, match="prompt staging root is not prepared"):
        _prepare_prompt_staging(catalog / "workflow-prompts", "workflow_test", "authoring", 1)
