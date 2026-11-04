import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from eom_dev_reporter import background_monitor
from eom_dev_reporter.background_monitor import ACTIVE_SLOT_JOBS_SQL, summary_line


def test_one_line_report_distinguishes_real_work_and_original_source_blocks():
    line = summary_line(
        {
            "state": "PROCESSING",
            "check": "OK",
            "verified_count": 104,
            "target_count": 1053,
            "blocked_source_count": 22,
        },
        {
            "creative_graph_registered_items": 687,
            "gpu_registered_targets": 271,
            "target_count": 520,
            "slot_jobs": [
                {"slot_id": "03", "status": "RUNNING"},
                {"slot_id": "03", "status": "COMMITTING"},
            ],
        },
        "GPU 현재 대기 0%/2MiB",
    )
    assert "\n" not in line
    assert "창작 Graph 누적 687건" in line and "271/520" in line
    assert "104/1053" not in line
    assert "원본 보류 22" in line and "슬롯 작업 1개" in line
    assert "GPU 현재 대기" in line


def test_unknown_slot_observation_is_not_reported_idle_or_healthy():
    line = summary_line({"check": "ATTENTION_REQUIRED"}, {}, "GPU 사용률 확인 불가")
    assert "점검 필요" in line and "슬롯 실행 수 확인 불가" in line
    assert "창작 Graph 누적 확인 필요" in line


def test_process_restart_cannot_reset_canonical_graph_count():
    embedding = {"creative_graph_registered_items": 687}
    for process_count in (120, 2, 6, 0):
        line = summary_line(
            {"check": "OK", "verified_count": process_count, "target_count": 1053},
            embedding,
            "GPU 현재 대기",
        )
        assert "창작 Graph 누적 687건" in line
        assert f"{process_count}/1053" not in line


def test_slot_observation_ignores_expired_released_missing_or_mismatched_leases():
    # Exact observer SELECT against in-memory relational fixtures, not a claim
    # about PostgreSQL migrations, permissions or production state.
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        connection.create_function("clock_timestamp", 0, lambda: 100)
        connection.executescript("""
            ATTACH DATABASE ':memory:' AS app;
            CREATE TABLE app.jobs (job_id TEXT, worker_slot_id TEXT, status TEXT);
            CREATE TABLE app.worker_leases
                (job_id TEXT, worker_slot_id TEXT, state TEXT, expires_at INTEGER);
        """)
        connection.executemany(
            "INSERT INTO app.jobs VALUES (?, ?, ?)",
            [
                ("held", "03", "RUNNING"),
                ("expired", "04", "RUNNING"),
                ("released", "05", "COMMITTING"),
                ("missing", "06", "RUNNING"),
                ("wrong-slot", "01", "RUNNING"),
                ("terminal", "02", "SUCCEEDED"),
                ("reconciling", "04", "CLAIMED"),
                ("boundary", "05", "RUNNING"),
            ],
        )
        connection.executemany(
            "INSERT INTO app.worker_leases VALUES (?, ?, ?, ?)",
            [
                ("held", "03", "ACTIVE", 101),
                ("held", "03", "EXPIRED", 99),
                ("expired", "04", "ACTIVE", 99),
                ("released", "05", "RELEASED", 101),
                ("wrong-slot", "02", "ACTIVE", 101),
                ("terminal", "02", "ACTIVE", 101),
                ("reconciling", "04", "RECONCILING", 101),
                ("boundary", "05", "ACTIVE", 100),
            ],
        )
        rows = [dict(row) for row in connection.execute(ACTIVE_SLOT_JOBS_SQL)]
        assert sorted(rows, key=lambda row: row["slot_id"]) == [
            {"slot_id": "03", "status": "RUNNING", "count": 1},
            {"slot_id": "04", "status": "CLAIMED", "count": 1},
        ]
        connection.execute("UPDATE app.worker_leases SET state = 'RELEASED'")
        assert list(connection.execute(ACTIVE_SLOT_JOBS_SQL)) == []


def test_fresh_observation_of_stopped_producer_does_not_hide_fresh_graph_and_gpu(monkeypatch):
    now = datetime.now(UTC)
    producer_at = (now - timedelta(days=1)).isoformat()
    envelope = {
        "__REALTIME_TIMESTAMP": str(int(now.timestamp() * 1_000_000)),
        "MESSAGE": json.dumps(
            {
                "observed_at": producer_at,
                "state": "STOPPED_TECHNICAL_FAILURE",
                "service_active": "failed",
                "check": "ATTENTION_REQUIRED",
            }
        ),
    }
    monkeypatch.setattr(background_monitor, "_run", lambda _arguments: json.dumps(envelope))
    value = background_monitor._snapshot("eom-creative-learning-observe.service")
    assert value["observed_at"] == producer_at and value["status_stale"] is True
    line = summary_line(
        value,
        {
            "creative_graph_registered_items": 701,
            "slot_jobs": [],
            "gpu_registered_targets": 271,
            "target_count": 520,
        },
        "GPU 현재 대기",
    )
    assert "창작 Graph 누적 701건" in line and "슬롯 작업 0개" in line
    assert "등록 작업 중단" in line and "271/520" in line


def test_old_journal_observation_is_not_refreshed_by_fresh_producer_timestamp(monkeypatch):
    now = datetime.now(UTC)
    envelope = {
        "__REALTIME_TIMESTAMP": str(int((now - timedelta(hours=1)).timestamp() * 1_000_000)),
        "MESSAGE": json.dumps({"observed_at": now.isoformat(), "check": "OK"}),
    }
    monkeypatch.setattr(background_monitor, "_run", lambda _arguments: json.dumps(envelope))
    with pytest.raises(ValueError, match="SNAPSHOT_STALE"):
        background_monitor._snapshot("eom-creative-learning-observe.service")
