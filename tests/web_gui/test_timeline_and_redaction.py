from __future__ import annotations

from datetime import UTC, datetime, timedelta

from eom_web_gui.redaction import sanitize_mapping, sanitize_text
from eom_web_gui.timeline import map_timeline

NOW = datetime(2026, 8, 21, 8, 0, tzinfo=UTC)


def test_timeline_maps_steps_and_events_without_raw_bodies() -> None:
    timeline = map_timeline(
        steps=[
            {
                "step_run_id": "steprun_test",
                "step_key": "authoring",
                "attempt": 1,
                "state": "SUCCEEDED",
                "started_at": NOW.isoformat(),
                "finished_at": (NOW + timedelta(seconds=2)).isoformat(),
                "platform_job_id": "job_test",
                "result_body": "must not render",
            }
        ],
        events=[
            {
                "event_id": "event_test",
                "event_type": "APPROVAL_REQUESTED",
                "new_state": "AWAITING_HUMAN_APPROVAL",
                "created_at": (NOW + timedelta(seconds=3)).isoformat(),
                "prompt": "must not render",
            }
        ],
        observe=None,
    )
    encoded = " ".join(item.model_dump_json() for item in timeline)
    assert "authoring 완료" in encoded
    assert "승인 대기" in encoded
    assert "must not render" not in encoded
    assert timeline[0].elapsed_ms == 2000


def test_redaction_removes_credentials_prompts_and_chain_of_thought() -> None:
    value = sanitize_mapping(
        {
            "status": "SUCCEEDED",
            "token": "sensitive",
            "prompt": "private",
            "chain_of_thought": "private",
            "summary": "Authorization: Bearer example",
        }
    )
    assert value == {"status": "SUCCEEDED", "summary": "Authorization: [REDACTED]"}
    assert "eom_at_" not in sanitize_text("eom_at_example")
