"""Verifier IO framing with synthetic protected-file/process seams; no actual run."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_workflow.local_indexing_owner_configuration import LocalIndexingRuntimeVerifierPin
from eom_workflow_runner import local_indexing_runtime_verification as verification


@pytest.fixture
def verifier(monkeypatch):
    files = Mock(spec=verification.NumericalRuntimeFileSnapshots)
    monkeypatch.setattr(verification, "NumericalRuntimeFileSnapshots", lambda: files)
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(verification.subprocess, "run", run)
    monkeypatch.setenv("EOM_DATABASE_URL", "synthetic-sensitive-value")
    pin = LocalIndexingRuntimeVerifierPin(
        source_commit="a" * 40, script_raw_sha256="sha256:" + "b" * 64
    )
    value = verification.FixedIndexingRuntimeVerification(pin)
    return value, files, run


def test_fixed_verifier_keeps_credentials_out_and_has_no_cached_success(verifier):
    value, files, run = verifier
    value.assert_current()
    value.assert_current()
    assert run.call_count == 2 and files.assert_unchanged.call_count == 4
    command = run.call_args.args[0]
    assert command[1:3] == ("-I", "-B")
    assert command[3] == "/opt/eom/embedding-owner-releases/" + "a" * 40 + "/verify-runtime.py"
    options = run.call_args.kwargs
    assert set(options["env"]) == {"PATH", "TZ", "LANG", "LC_ALL"}
    assert "synthetic-sensitive-value" not in repr(options)
    assert (
        options["stdin"]
        == options["stdout"]
        == options["stderr"]
        == verification.subprocess.DEVNULL
    )
    assert options["timeout"] == 60


@pytest.mark.parametrize("fault", ["exit", "timeout", "changed"])
def test_verifier_failure_never_becomes_runtime_ready(verifier, fault):
    value, files, run = verifier
    if fault == "exit":
        run.return_value.returncode = 1
    elif fault == "timeout":
        run.side_effect = TimeoutError("sensitive child detail")
    else:
        files.assert_unchanged.side_effect = ValueError("sensitive filesystem detail")
    with pytest.raises(ValueError) as error:
        value.assert_current()
    assert str(error.value) == "LOCAL_INDEXING_NUMERICAL_RUNTIME_UNAVAILABLE"
    if fault == "changed":
        run.assert_not_called()
