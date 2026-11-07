"""User-requested, removable ten-minute development status, never runtime control.

Consume the existing bounded read-only observer snapshots. No DB/NAS/worker
credential access, workflow submission, retries or service restarts are allowed.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from typing import Any, Final
from zoneinfo import ZoneInfo

from eom_dev_reporter.sender import load_reporter_config, send_webhook

OBSERVERS = (
    "eom-creative-learning-observe.service",
    "eom-unified-embedding-observe.service",
)

# The separate root-owned metadata observer embeds this read-only query at
# installation. This reporter still has no database or credential access.
ACTIVE_SLOT_JOBS_SQL: Final = """
SELECT job.worker_slot_id AS slot_id, job.status, count(*) AS count
FROM app.jobs job
JOIN app.worker_leases lease
  ON lease.job_id = job.job_id AND lease.worker_slot_id = job.worker_slot_id
WHERE job.worker_slot_id IS NOT NULL
  AND job.status IN ('CLAIMED', 'RUNNING', 'VALIDATING_RESULT', 'COMMITTING')
  AND lease.state IN ('ACTIVE', 'RECONCILING')
  AND lease.expires_at > clock_timestamp()
GROUP BY job.worker_slot_id, job.status
"""


def _run(arguments: list[str]) -> str:
    result = subprocess.run(arguments, capture_output=True, text=True, check=False, timeout=20)
    if result.returncode or len(result.stdout.encode()) > 256 * 1024:
        raise ValueError("BACKGROUND_MONITOR_READ_UNAVAILABLE")
    return result.stdout


def _snapshot(unit: str) -> dict[str, Any]:
    output = _run(
        [
            "/usr/bin/journalctl",
            "-u",
            unit,
            "--since",
            "-25min",
            "-n",
            "40",
            "--no-pager",
            "-o",
            "json",
        ]
    )
    for line in reversed(output.splitlines()):
        try:
            envelope = json.loads(line)
            if not isinstance(envelope, dict) or not isinstance(envelope.get("MESSAGE"), str):
                continue
            value = json.loads(envelope["MESSAGE"])
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict) and isinstance(value.get("observed_at"), str):
            try:
                checked_at = datetime.fromtimestamp(
                    int(envelope["__REALTIME_TIMESTAMP"]) / 1_000_000, UTC
                )
                source_at = datetime.fromisoformat(value["observed_at"])
                if source_at.tzinfo is None:
                    raise ValueError("producer observation needs an explicit timezone")
            except (KeyError, TypeError, ValueError, OverflowError, OSError):
                raise ValueError("BACKGROUND_MONITOR_SNAPSHOT_TIME_INVALID") from None
            age = (datetime.now(UTC) - checked_at).total_seconds()
            if not 0 <= age <= 20 * 60:
                raise ValueError("BACKGROUND_MONITOR_SNAPSHOT_STALE")
            # A fresh read can correctly observe a stopped producer's old status.
            # Keep its original timestamp and mark it stale, rather than hide the
            # independent fresh Graph/GPU counts or invent fresh producer progress.
            source_age = (datetime.now(UTC) - source_at).total_seconds()
            if not 0 <= source_age <= 20 * 60:
                value = {**value, "check": "ATTENTION_REQUIRED", "status_stale": True}
            return value
    raise ValueError("BACKGROUND_MONITOR_SNAPSHOT_MISSING")


def _count(value: object) -> str:
    return str(value) if type(value) is int and 0 <= value <= 1000000 else "?"


def summary_line(creative: dict[str, Any], embedding: dict[str, Any], gpu: str) -> str:
    state = creative.get("state")
    creative_state = (
        "진행"
        if creative.get("check") == "OK"
        else "원본 확인 대기"
        if creative.get("check") == "SOURCE_WAIT"
        else "자원 대기"
        if creative.get("check") == "RESOURCE_WAIT"
        else "점검 필요"
    )
    if state == "STOPPED_TECHNICAL_FAILURE" and creative.get("service_active") == "failed":
        creative_state = "중단"
    elif state == "COMPLETED" and not creative.get("status_stale"):
        creative_state = "완료"
    slots = embedding.get("slot_jobs", [])
    busy = {
        str(row.get("slot_id"))
        for row in slots
        if isinstance(row, dict)
        and row.get("status") in {"CLAIMED", "RUNNING", "VALIDATING_RESULT", "COMMITTING"}
    }
    slot_text = (
        f"슬롯 작업 {len(busy)}개"
        if isinstance(slots, list) and "slot_jobs" in embedding
        else "슬롯 실행 수 확인 불가"
    )
    cumulative = embedding.get("creative_graph_registered_items")
    graph_text = (
        f"창작 Graph 누적 {cumulative}건"
        if type(cumulative) is int and 0 <= cumulative <= 1000000
        else "창작 Graph 누적 확인 필요"
    )
    return (
        "슬롯·GPU 작업을 점검했습니다. "
        f"{graph_text} · 등록 작업 {creative_state}"
        f"(원본 보류 {_count(creative.get('blocked_source_count'))}) · {slot_text} · "
        f"GPU 기출 임베딩 {_count(embedding.get('gpu_registered_targets'))}"
        f"/{_count(embedding.get('target_count'))} · {gpu}"
    )


def current_gpu_usage() -> str:
    """One current device sample, not idle percentage or embedding progress."""
    try:
        output = _run(
            [
                "/usr/bin/nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used",
                "--format=csv,noheader,nounits",
            ]
        )
        utilization, memory = (int(field.strip()) for field in output.splitlines()[0].split(","))
        if not 0 <= utilization <= 100 or memory < 0:
            raise ValueError("BACKGROUND_MONITOR_GPU_SAMPLE_INVALID")
        return f"GPU 현재 사용률 {utilization}% · VRAM {memory}MiB"
    except (ValueError, IndexError, OSError, subprocess.TimeoutExpired):
        return "GPU 현재 사용률 확인 불가"


def main() -> None:
    gpu = current_gpu_usage()
    try:
        creative, embedding = (_snapshot(unit) for unit in OBSERVERS)
        try:
            properties = _run(
                [
                    "/usr/bin/systemctl",
                    "show",
                    "eom-embedding-index-owner.service",
                    "--property=ActiveState",
                    "--property=MainPID",
                ]
            )
            owner = dict(row.split("=", 1) for row in properties.splitlines() if "=" in row)
            if owner.get("ActiveState") != "active" or int(owner.get("MainPID", "0")) <= 0:
                gpu += " · 임베딩 담당 작업 중단(점검 필요)"
        except (ValueError, OSError, subprocess.TimeoutExpired):
            gpu += " · 임베딩 담당 상태 확인 불가"
        line = summary_line(creative, embedding, gpu)
    except (ValueError, OSError, subprocess.TimeoutExpired):
        line = f"슬롯·임베딩 관측 결과를 확인하지 못해 점검이 필요합니다. {gpu}"
    timestamp = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%m/%d %H:%M")
    text = f"{line} ({timestamp} 한국시간)"
    delivery = send_webhook({"text": text, "blocks": []}, load_reporter_config())
    # Only the one-line sanitized operational summary is archived in journal.
    print(
        json.dumps(
            {
                "summary": text,
                "delivery": delivery.status.value,
                "http_status": delivery.http_status,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
