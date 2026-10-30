"""Derived status output is bounded, atomic and never an admission authority."""

import json
from pathlib import Path

import pytest
from eom_catalog_service import creative_learning_runner as runner

COHORT_ID = "creativecohort_" + "a" * 32


def state_root(tmp_path):
    root = tmp_path / "state"
    root.mkdir(mode=0o750)
    return root


def test_status_is_atomic_small_metadata_and_replaces_without_partial_json(tmp_path):
    root = state_root(tmp_path)
    runner.write_status(root, COHORT_ID, {"state": "EXTRACTING", "verified_count": 0})
    path = root / (COHORT_ID + ".json")
    first = path.stat().st_ino
    runner.write_status(root, COHORT_ID, {"state": "VERIFIED", "verified_count": 1})
    assert path.stat().st_ino != first
    assert path.stat().st_mode & 0o777 == 0o640
    value = json.loads(path.read_text())
    assert value["verified_count"] == 1 and value["observed_at"].endswith("+00:00")
    assert list(root.glob(".status-*")) == []


@pytest.mark.parametrize("kind", ["root", "symlink", "mode", "hardlink"])
def test_status_rejects_unsafe_roots_and_targets_without_overwriting(tmp_path, kind):
    root = state_root(tmp_path)
    outside = tmp_path / "outside"
    outside.write_text("preserve")
    target = root / (COHORT_ID + ".json")
    if kind == "root":
        root.chmod(0o777)
    elif kind == "symlink":
        target.symlink_to(outside)
    else:
        target.write_text("old")
        target.chmod(0o640 if kind == "hardlink" else 0o666)
        if kind == "hardlink":
            (root / "linked").hardlink_to(target)
    with pytest.raises(ValueError):
        runner.write_status(root, COHORT_ID, {"state": "STARTING"})
    assert outside.read_text() == "preserve"


def test_long_status_and_untrusted_identity_are_not_written(tmp_path):
    root = state_root(tmp_path)
    with pytest.raises(ValueError, match="TOO_LARGE"):
        runner.write_status(root, COHORT_ID, {"text": "x" * 17000})
    with pytest.raises(ValueError):
        runner.write_status(root, "../outside", {"state": "STARTING"})
    assert not tuple(root.iterdir())


@pytest.mark.parametrize(
    "error",
    [ValueError("password=private"), RuntimeError("item contents"), RuntimeError("cookie secret")],
)
def test_unstructured_error_messages_never_enter_status_or_logs(error):
    assert runner.stable_error_code(error) == "CREATIVE_COHORT_EXECUTION_FAILED"


def test_structured_error_codes_are_allowed_but_not_arbitrary_messages():
    assert (
        runner.stable_error_code(ValueError("CREATIVE_COHORT_SOURCE_MISMATCH"))
        == "CREATIVE_COHORT_SOURCE_MISMATCH"
    )
    error = RuntimeError()
    error.code = "HAS_NEWLINE\nsecret"
    assert runner.stable_error_code(error) == "CREATIVE_COHORT_EXECUTION_FAILED"


def test_owner_template_pins_installed_code_and_cannot_read_worker_auth():
    root = Path(__file__).resolve().parents[2]
    unit = (root / "infra/systemd/eom-creative-learning.service.in").read_text()
    assert "@PREFIX@/site-packages" in unit and " -I -B " in unit
    assert "NoNewPrivileges=true" in unit and "ProtectHome=true" in unit
    assert "/srv/eom/worker-homes" in unit and "/etc/eom/secrets/api.env" in unit
    assert "IPAddressDeny=any" in unit and "RestartPreventExitStatus=78" in unit
    assert "EOM_DATABASE_URL" not in unit and "auth.json" not in unit


@pytest.mark.parametrize("state", ["EXTRACTING", "ANALYZING", "STARTING", "UNKNOWN"])
def test_actual_pending_work_retains_bounded_observation_delay(state):
    assert runner.progress_poll_delay_seconds(state) == 10


def test_verified_history_reconstruction_has_no_per_item_idle_sleep():
    assert runner.progress_poll_delay_seconds("VERIFIED") == 0
