"""Derived status output is bounded, atomic and never an admission authority."""

import json
import socket
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service import creative_learning_runner as runner
from eom_catalog_service.creative_cohort_execution import CreativeCohortProgress

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
        runner.write_status(root, COHORT_ID, {"text": "x" * (runner.MAX_STATUS_BYTES + 1)})
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
    assert "TimeoutStopSec=1800" in unit
    assert "Type=notify" in unit and "NotifyAccess=main" in unit
    assert "TimeoutStartSec=300" in unit


def test_owner_ready_uses_real_local_datagram_without_work_or_status_payload(tmp_path, monkeypatch):
    address = str(tmp_path / "notify")
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as receiver:
        receiver.bind(address)
        receiver.settimeout(1)
        monkeypatch.setenv("NOTIFY_SOCKET", address)
        runner.notify_owner_ready()
        assert receiver.recv(128) == b"READY=1"


def test_direct_cli_needs_no_systemd_and_missing_notification_socket_fails_closed(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    runner.notify_owner_ready()
    monkeypatch.setenv("NOTIFY_SOCKET", str(tmp_path / "missing"))
    with pytest.raises(ValueError, match="CREATIVE_COHORT_STARTUP_NOTIFY_FAILED"):
        runner.notify_owner_ready()


def test_stop_status_is_written_only_after_publication_drain():
    # Actual future waiting is covered by the parallel driver's stop tests.
    # Keep this thin adapter's derived status ordered around the application close.
    source = Path(runner.__file__).read_text()
    assert source.index('"state": "DRAINING"') < source.index("service.close()")
    assert source.index("service.close()") < source.index('"state": "STOPPED"')


@pytest.mark.parametrize("failure", [None, "pins", "advance", "close"])
def test_runner_keeps_fence_until_close_and_never_overwrites_failure(
    tmp_path, monkeypatch, failure
):
    root = state_root(tmp_path)
    scope = SimpleNamespace(
        cohort=SimpleNamespace(cohort_id=COHORT_ID, targets=(object(),)),
        cohort_id=COHORT_ID,
        max_in_flight_sources=1,
    )
    events, signals = [], {}
    engine, owner = Mock(), Mock()
    monkeypatch.setattr(runner, "STATE_ROOT", root)
    monkeypatch.setattr(
        "sys.argv", ["runner", "--cohort-revision-id", "rev_" + "a" * 32, "--verified-limit", "1"]
    )
    monkeypatch.setattr(runner.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        runner.os, "fstat", lambda fd: SimpleNamespace(st_mode=0o100600, st_uid=0, st_nlink=1)
    )
    monkeypatch.setattr(runner, "validate_state_root", lambda _: None)
    monkeypatch.setattr(runner.Settings, "from_environment", Mock())
    monkeypatch.setattr(runner.CatalogSettings, "from_environment", Mock())
    monkeypatch.setattr(runner, "build_engine", lambda: engine)
    monkeypatch.setattr(runner, "CatalogArtifactService", Mock())
    monkeypatch.setattr(runner, "ControlFileSetPublisher", Mock())
    monkeypatch.setattr(runner, "read_creative_execution_scope", lambda *args: (scope, None))
    monkeypatch.setattr(
        runner,
        "CreativeCohortExecutionService",
        Mock(
            return_value=owner,
            side_effect=ValueError("CREATIVE_COHORT_PRESET_PIN_MISMATCH")
            if failure == "pins"
            else None,
        ),
    )
    monkeypatch.setattr(runner, "notify_owner_ready", lambda: events.append("READY"))
    monkeypatch.setattr(runner, "require_background_write_capacity", lambda _: None)
    monkeypatch.setattr(
        runner.signal, "signal", lambda number, handler: signals.update({number: handler})
    )
    monkeypatch.setattr(
        runner, "write_status", lambda root, cohort, status: events.append(status["state"])
    )
    original_close = runner.os.close

    def release_fence(fd):
        events.append("FENCE_RELEASED")
        original_close(fd)

    monkeypatch.setattr(runner.os, "close", release_fence)

    def advance():
        assert events.count("READY") == 1
        signals[runner.signal.SIGTERM](None, None)
        if failure == "advance":
            raise ValueError("CREATIVE_COHORT_SOURCE_MISMATCH")
        return CreativeCohortProgress(
            cohort_id=COHORT_ID,
            state="PROCESSING",
            verified_count=0,
            target_count=1,
            external_number=None,
            workflow_id=None,
            item_revision_id=None,
            analysis_run_id=None,
            graph_snapshot_revision_id=None,
        )

    def close():
        events.append("CLOSE")
        assert "FENCE_RELEASED" not in events
        if failure == "close":
            raise ValueError("KNOWLEDGE_GRAPH_STALE_CURRENT")

    owner.advance_once.side_effect, owner.close.side_effect = advance, close
    if failure:
        with pytest.raises(SystemExit) as error:
            runner.main()
        assert error.value.code == 78
        assert "STOPPED" not in events
        assert "STOPPED_TECHNICAL_FAILURE" in events
    else:
        runner.main()
        assert events[-4:] == ["DRAINING", "CLOSE", "STOPPED", "FENCE_RELEASED"]
    assert events[-1] == "FENCE_RELEASED"
    assert events.count("READY") == (0 if failure == "pins" else 1)
    engine.dispose.assert_called_once()


@pytest.mark.parametrize("state", ["EXTRACTING", "ANALYZING", "STARTING", "UNKNOWN"])
def test_actual_pending_work_retains_bounded_observation_delay(state):
    assert runner.progress_poll_delay_seconds(state) == 10


def test_verified_history_reconstruction_has_no_per_item_idle_sleep():
    assert runner.progress_poll_delay_seconds("VERIFIED") == 0


def test_unready_source_waits_without_fabricating_work_or_crashing_owner():
    assert runner.progress_poll_delay_seconds("BLOCKED_SOURCES") == 300
    source = Path(runner.__file__).read_text()
    assert 'raise ValueError("CREATIVE_COHORT_SOURCE_PREVIEWS_PENDING")' not in source
