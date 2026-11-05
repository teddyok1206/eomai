"""Explicit historical policy snapshots for model-free compatibility tests only.

These fixtures do not represent current production admission. Current-policy
tests run without them and must continue to reject retired identities.
"""

import os
from pathlib import Path
from types import MappingProxyType
from urllib.parse import unquote, urlsplit

import pytest
from eom_workflow import admission

from scripts.api.testdb_guard import TestDatabaseManifest, validate_state_directory


def _historical_policy(
    monkeypatch: pytest.MonkeyPatch, values: tuple[admission.WorkflowAdmission, ...]
) -> None:
    if os.environ.get("EOM_RUN_API_INTEGRATION") != "1":
        pytest.skip("historical policy replay requires the guarded disposable API database")
    state_path = os.environ.get("EOM_API_TEST_RUNTIME_ENV")
    if state_path is None:
        pytest.fail("historical policy fixture requires a disposable runtime receipt")
    state = validate_state_directory(Path(state_path).parent)
    manifest = TestDatabaseManifest.load(state / "manifest.json")
    url = os.environ["EOM_DATABASE_URL"]
    parsed = urlsplit(url)
    assert parsed.username == manifest.owner_role
    assert unquote(parsed.path.removeprefix("/")) == manifest.database
    policy = dict(admission.WORKFLOW_ADMISSION_BY_IDENTITY)
    policy.update({(value.definition_key, value.definition_version): value for value in values})
    monkeypatch.setattr(admission, "WORKFLOW_ADMISSION_BY_IDENTITY", MappingProxyType(policy))
    # Newly imported test definitions capture that historical policy. Never
    # toggle their immutable stored active flag afterward: production admission
    # already combines that snapshot with the separately restored current policy.


@pytest.fixture
def historical_document_workflow_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    _historical_policy(
        monkeypatch,
        (
            admission.WorkflowAdmission("knowledge-analysis", "2.0.0", "workflow-role/1.5.0"),
            admission.WorkflowAdmission("knowledge-analysis", "3.0.0", "workflow-role/1.6.0"),
            admission.WorkflowAdmission("knowledge-analysis", "5.0.0", "workflow-role/1.8.0"),
            admission.WorkflowAdmission("knowledge-analysis", "6.0.0", "workflow-role/1.9.0"),
            admission.WorkflowAdmission("knowledge-analysis", "7.0.0", "workflow-role/1.10.0"),
        ),
    )


@pytest.fixture
def historical_item_workflow_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    _historical_policy(
        monkeypatch,
        (admission.WorkflowAdmission("generic-item-development", "1.0.0", "workflow-role/1.0.1"),),
    )
