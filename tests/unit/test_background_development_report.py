from eom_dev_reporter.background_monitor import summary_line


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
