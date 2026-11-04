"""User-requested, removable ten-minute development status, never runtime control.

Consume the existing bounded read-only observer snapshots. No DB/NAS/worker
credential access, workflow submission, retries or service restarts are allowed.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from eom_dev_reporter.sender import load_reporter_config, send_webhook

OBSERVERS = (
    "eom-creative-learning-observe.service",
    "eom-unified-embedding-observe.service",
)


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
            "cat",
        ]
    )
    for line in reversed(output.splitlines()):
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and isinstance(value.get("observed_at"), str):
            age = (datetime.now(UTC) - datetime.fromisoformat(value["observed_at"])).total_seconds()
            if not 0 <= age <= 20 * 60:
                raise ValueError("BACKGROUND_MONITOR_SNAPSHOT_STALE")
            return value
    raise ValueError("BACKGROUND_MONITOR_SNAPSHOT_MISSING")


def _count(value: object) -> str:
    return str(value) if type(value) is int and 0 <= value <= 1000000 else "?"


def summary_line(creative: dict[str, Any], embedding: dict[str, Any], gpu: str) -> str:
    state = creative.get("state")
    creative_state = (
        "진행"
        if creative.get("check") == "OK"
        else "자원 대기"
        if creative.get("check") == "RESOURCE_WAIT"
        else "점검 필요"
    )
    if state == "COMPLETED":
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
    return (
        "슬롯·GPU 작업을 점검했습니다. "
        f"풀이·Graph {creative_state} {_count(creative.get('verified_count'))}"
        f"/{_count(creative.get('target_count'))}"
        f"(원본 보류 {_count(creative.get('blocked_source_count'))}) · {slot_text} · "
        f"GPU 기출 임베딩 {_count(embedding.get('gpu_registered_targets'))}"
        f"/{_count(embedding.get('target_count'))} · {gpu}"
    )


def main() -> None:
    try:
        creative, embedding = (_snapshot(unit) for unit in OBSERVERS)
        try:
            output = _run(
                [
                    "/usr/bin/nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used",
                    "--format=csv,noheader,nounits",
                ]
            )
            fields = output.splitlines()[0].split(",")
            utilization, memory = (int(field.strip()) for field in fields)
            gpu = f"GPU {'연산 중' if utilization else '현재 대기'} {utilization}%/{memory}MiB"
        except (ValueError, IndexError, OSError, subprocess.TimeoutExpired):
            gpu = "GPU 사용률 확인 불가"
        line = summary_line(creative, embedding, gpu)
    except (ValueError, OSError, subprocess.TimeoutExpired):
        line = "슬롯·GPU 관측 결과를 확인하지 못해 점검이 필요합니다."
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
