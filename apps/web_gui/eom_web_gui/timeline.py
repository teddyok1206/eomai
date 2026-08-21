"""Map API projections into a stable, human-readable operational timeline."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from eom_web_gui.contracts import TimelineEvent

EVENT_LABELS = {
    "WORKFLOW_CREATED": "Workflow 생성",
    "WORKFLOW_STARTED": "Workflow 생성",
    "CONTENT_PACK_RESOLVED": "Content Pack resolve",
    "PROMPT_ARTIFACT_CREATED": "prompt Artifact 생성",
    "JOB_CREATED": "Job 시작",
    "JOB_STARTED": "Job 시작",
    "JOB_SUCCEEDED": "Job 종료",
    "STEP_COMPLETED": "단계 완료",
    "APPROVAL_REQUESTED": "승인 대기",
    "WORKFLOW_APPROVED": "승인 command",
    "ITEM_REGISTERED": "Item/Revision 생성",
    "WORKFLOW_COMPLETED": "완료",
}
STEP_LABELS = {
    "authoring": "authoring 완료",
    "review": "review 완료",
    "registration": "registration",
    "item_management": "Item/Revision 생성",
    "hwpx": "HWPX build",
}


def map_timeline(
    *, steps: list[dict[str, Any]], events: list[dict[str, Any]], observe: dict[str, Any] | None
) -> tuple[TimelineEvent, ...]:
    mapped: dict[str, TimelineEvent] = {}
    for event in events:
        event_id = str(event.get("event_id") or "")
        timestamp = _timestamp(event.get("created_at"))
        if not event_id or timestamp is None:
            continue
        event_type = str(event.get("event_type") or "EVENT")
        state = str(event.get("new_state") or "RECORDED")
        mapped[event_id] = TimelineEvent(
            event_id=event_id,
            timestamp=timestamp,
            label=EVENT_LABELS.get(event_type, _safe_label(event_type)),
            state=state,
            error_code=_error_code(event.get("error_code")),
        )
    for step in steps:
        step_id = str(step.get("step_run_id") or "")
        timestamp = _timestamp(step.get("finished_at") or step.get("started_at"))
        if not step_id or timestamp is None:
            continue
        step_key = str(step.get("step_key") or "step")
        started = _timestamp(step.get("started_at"))
        finished = _timestamp(step.get("finished_at"))
        elapsed = (
            max(0, int((finished - started).total_seconds() * 1000))
            if started is not None and finished is not None
            else None
        )
        mapped[f"step:{step_id}"] = TimelineEvent(
            event_id=f"step:{step_id}",
            timestamp=timestamp,
            label=STEP_LABELS.get(step_key, f"{_safe_label(step_key)} 단계"),
            state=str(step.get("state") or "UNKNOWN"),
            step=step_key,
            job_id=_optional_string(step.get("platform_job_id")),
            attempt=_optional_int(step.get("attempt")),
            elapsed_ms=elapsed,
            error_code=_error_code(step.get("error_code")),
        )
    if observe:
        for event in observe.get("events", []):
            if not isinstance(event, dict):
                continue
            event_id = str(event.get("event_id") or "")
            timestamp = _timestamp(event.get("timestamp"))
            if not event_id or timestamp is None or event_id in mapped:
                continue
            mapped[f"observe:{event_id}"] = TimelineEvent(
                event_id=f"observe:{event_id}",
                timestamp=timestamp,
                label=EVENT_LABELS.get(
                    str(event.get("event_type") or ""),
                    _safe_label(str(event.get("event_type") or "운영 event")),
                ),
                state=str(event.get("status") or "RECORDED"),
                step=_optional_string(event.get("step_run_id")),
                worker_slot=_optional_string(event.get("worker_slot_id")),
                job_id=_optional_string(event.get("job_id")),
                artifact_id=_optional_string(event.get("artifact_id")),
                error_code=_error_code(event.get("error_code")),
            )
    return tuple(sorted(mapped.values(), key=lambda item: (item.timestamp, item.event_id)))


def _timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _safe_label(value: str) -> str:
    cleaned = " ".join(value.replace("_", " ").split())
    return cleaned[:120] or "운영 event"


def _error_code(value: object) -> str | None:
    text = _optional_string(value)
    if text and text.replace("_", "").isalnum() and text.upper() == text:
        return text[:64]
    return None


def _optional_string(value: object) -> str | None:
    return str(value)[:128] if isinstance(value, (str, int)) and str(value) else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and value >= 1 else None
