#!/usr/bin/env python3
"""Generate immutable PDF review preset snapshots for runtime and source review."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from eom_identifiers import content_sha256

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "config/document-review-presets"
PACKAGED = ROOT / "packages/workflow/eom_workflow/resources/document-review-presets"

PRESETS: dict[str, tuple[str, tuple[str, ...]]] = {
    "PROBLEM_SET": (
        "N제",
        (
            "각 문항을 독립적으로 풀어 정답의 유일성, 조건의 충분성, 과학적 정확성을 검증한다.",
            "정답과 오답 해설이 문항 조건, 자료, 표, 그림과 모두 일치하는지 검증한다.",
            "교육과정 범위와 의도 난이도에 맞는지, 불필요한 계산 또는 억지 함정이 없는지 검토한다.",
            "기출 또는 인접 문항의 표현만 바꾼 과도한 복제가 아닌지 검토한다.",
            "그림과 표의 수치, 단위, 축, 범례, 기호가 본문과 모순되지 않는지 먼저 확인한다.",
            "학생에게 공개되는 내용과 편집자·제작자용 지시가 섞이지 않았는지 검토한다.",
        ),
    ),
    "WEEKLY_WORKBOOK": (
        "주간지",
        (
            "주차·차시 안에서 개념 도입, 예제, 연습, 심화의 학습 흐름이 자연스러운지 검토한다.",
            "같은 용어, 기호, 단위, 서술 관습이 문서 전체에서 일관되는지 검토한다.",
            "주간 학습량과 문항 난이도 상승이 과도하거나 갑작스럽지 않은지 검토한다.",
            "각 문항의 정답 유일성, 풀이 논리, 정답·오답 해설의 과학적 정확성을 독립 검증한다.",
            "반복 문항이 단순 중복인지 의도된 간격 반복인지 구분하고 근거 위치를 제시한다.",
            "표·그림·참고 박스가 인접 본문 및 해설과 정확히 연결되는지 검토한다.",
        ),
    ),
    "MOCK_EXAM": (
        "모의고사",
        (
            "시험지 공통 지시, 문항 번호, 선택지 표기, 배점, 정답표와 해설의 대응을 검증한다.",
            "각 문항을 독립적으로 풀어 정답 유일성과 조건 충분성을 확인한다.",
            "문항 간 영역·난이도·자료 유형·풀이 시간의 균형과 과도한 중복을 검토한다.",
            "그림과 표의 수치, 단위, 축, 범례, 기호 및 인쇄 가독성을 본문보다 먼저 확인한다.",
            "교육과정 범위, 과학적 정확성, 기출과의 과도한 유사성을 검토한다.",
            "실제 시험 배포를 막는 편집, 페이지 나눔, 누락, 순서, 참조 오류를 우선 표시한다.",
        ),
    ),
}


def snapshot(key: str, display_name: str, criteria: tuple[str, ...]) -> dict[str, Any]:
    identity_seed = json.dumps(
        {"preset_key": key, "version": "1.0"}, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    value: dict[str, Any] = {
        "schema_version": "pdf-review-preset/1.0",
        "preset_key": key,
        "preset_revision_id": "reviewpresetrev_" + hashlib.sha256(identity_seed).hexdigest()[:32],
        "display_name": display_name,
        "criteria": list(criteria),
    }
    value["preset_sha256"] = content_sha256(value)
    return value


def main() -> None:
    for directory in (SOURCE, PACKAGED):
        directory.mkdir(parents=True, exist_ok=True)
    for key, (display_name, criteria) in PRESETS.items():
        payload = (
            json.dumps(snapshot(key, display_name, criteria), ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        name = key.lower().replace("_", "-") + "-v1.json"
        (SOURCE / name).write_bytes(payload)
        (PACKAGED / name).write_bytes(payload)


if __name__ == "__main__":
    main()
