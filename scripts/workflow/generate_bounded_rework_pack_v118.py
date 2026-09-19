#!/usr/bin/env python3
# ruff: noqa: E501
"""Create immutable Content Pack 1.18 for orchestrator-mediated bounded rework."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "content/packs/generated-knowledge-item/1.17.0"
TARGET = ROOT / "content/packs/generated-knowledge-item/1.18.0"

AUTHORING_REWORK = """

REWORK_FEEDBACK_JSON: {{ rework.feedback_json }}
PRIOR_AUTHORING_RESULT_JSON: {{ rework.prior_authoring_result_json }}
SOURCE_REVIEW_RESULT_JSON: {{ rework.source_review_result_json }}

REWORK_FEEDBACK_JSON이 `null`이면 최초 출제이므로 이전 결과를 추측하지 않는다. 값이 있으면 이는
오케스트레이터가 exact prior authoring/review Artifact revision에 결속하고 self-hash를 검증한 bounded
재작업 지시다. worker끼리 직접 대화한다고 간주하지 말고 제공된 두 immutable 결과와 지시만 읽는다.
`repairable_finding_codes`의 실제 finding을 새 완전한 draft에서 해소하되, 맞았던 정답·해설·근거·구조는
불필요하게 훼손하지 않는다. `disregarded_finding_codes`는 application이 계약과 대조해 허위 양성으로
판정한 것이므로 그 지적에 맞추려고 올바른 draft를 바꾸지 않는다. 이전 결과를 patch 형식으로 반환하지
말고 현재 역할의 전체 authoring-result를 새 Artifact revision으로 반환한다.
"""

REVIEW_REWORK = """

REWORK_FEEDBACK_JSON: {{ rework.feedback_json }}
PRIOR_AUTHORING_RESULT_JSON: {{ rework.prior_authoring_result_json }}
SOURCE_REVIEW_RESULT_JSON: {{ rework.source_review_result_json }}

REWORK_FEEDBACK_JSON이 `null`이면 최초 독립 검토다. 값이 있으면 이전 검토 결론을 그대로 반복하지 말고
새 authoring Artifact를 처음부터 독립적으로 검토한다. 이전 `repairable_finding_codes`가 실제로
해소됐는지 확인하고, 해소되지 않은 경우에만 새 결과에 해당 blocking finding을 다시 선언한다.
`disregarded_finding_codes`는 application이 typed request와 canonical draft에 대조해 허위 양성으로
판정한 코드이므로 동일한 잘못된 근거로 반복하지 않는다. 새로운 결함은 증거와 canonical draft leaf에
근거해 별도로 기록한다. 최대 횟수와 다음 단계는 오케스트레이터가 결정하며 reviewer가 지시하지 않는다.
"""


def _append_before_output_contract(path: Path, insertion: str, marker: str) -> None:
    text = path.read_text(encoding="utf-8")
    if marker not in text:
        raise ValueError(f"expected marker is missing from {path}: {marker}")
    path.write_text(text.replace(marker, insertion + "\n" + marker, 1), encoding="utf-8")


def _tree_bytes(root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(root): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _generate(target: Path) -> None:
    if target.exists():
        raise FileExistsError(target)
    shutil.copytree(SOURCE, target)
    pack_path = target / "pack.yaml"
    pack = yaml.safe_load(pack_path.read_text(encoding="utf-8"))
    pack["pack"]["version"] = "1.18.0"
    pack["pack"]["description"] = (
        "Solution-enriched Graph review with orchestrator-mediated bounded authoring rework"
    )
    pack["compatibility"]["workflow_definitions"][0]["versions"] = ["1.12.0"]
    pack_path.write_text(
        yaml.safe_dump(pack, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    additions = (
        "rework.feedback_json",
        "rework.prior_authoring_result_json",
        "rework.source_review_result_json",
    )
    for name in ("generated-knowledge-authoring.yaml", "generated-knowledge-review.yaml"):
        profile_path = target / "profiles" / name
        profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
        profile["profile"]["version"] = "11.1.0"
        profile["required_context"].extend(additions)
        profile_path.write_text(
            yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    _append_before_output_contract(
        target / "prompt-templates" / "authoring.md",
        AUTHORING_REWORK,
        "출력은 authoring-result@11.0 JSON Schema를 정확히 만족해야 한다.",
    )
    _append_before_output_contract(
        target / "prompt-templates" / "review.md",
        REVIEW_REWORK,
        "아래 exact authoring Artifact Revision과 authoring-result@11.0의 typed editorial draft를 검토한다.",
    )


def main() -> None:
    if not TARGET.exists():
        _generate(TARGET)
        return
    with tempfile.TemporaryDirectory(prefix="eom-bounded-rework-pack-") as temp_dir:
        generated = Path(temp_dir) / "1.18.0"
        _generate(generated)
        if _tree_bytes(TARGET) != _tree_bytes(generated):
            raise ValueError("generated Content Pack 1.18.0 has drifted")


if __name__ == "__main__":
    main()
