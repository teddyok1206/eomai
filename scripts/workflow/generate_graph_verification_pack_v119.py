#!/usr/bin/env python3
"""Create immutable Content Pack 1.19 for Graph verification-planned review."""

# ruff: noqa: E501 -- Exact Korean prompt lines are hashed immutable release input.

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "content/packs/generated-knowledge-item/1.18.0"
TARGET = ROOT / "content/packs/generated-knowledge-item/1.19.0"

REVIEW_VERIFICATION = r"""

REVIEW_ESCALATION_DIRECTIVE_JSON: {{ escalation.directive_json }}
SOURCE_PRIMARY_REVIEW_RESULT_JSON: {{ escalation.source_review_result_json }}

이 검토는 다음 네 단계를 기계적으로 감사 가능하게 수행한다. (1) 결론 전에 검증 대상을 먼저 고정하고,
(2) IMAGE가 있으면 시각자료와 본문·수치·라벨의 관계부터 검사하며, (3) 의심 지적을 즉시 blocking으로
확정하지 않고 CONFIRMED/DEMOTED/UNCERTAIN 중 하나로 재검증하고, (4) 오케스트레이터가 제공한 정확한
강화 지시가 있을 때만 동일 검토 step의 한 번뿐인 강화 검토를 수행한다. 자유로운 사고 전문은 출력하지
말고 짧은 결론, exact draft leaf, Evidence ID만 남긴다.

verification_targets는 target_id 오름차순으로 정렬하고 과학 주장, 정답 도출, ①~⑤ 각각의 선택지,
해설 일관성, 교육과정 범위, 독창성을 모두 포함한다. ㄱ/ㄴ/ㄷ가 있으면 각 진술 target도 포함한다.
시각자료가 있으면 VISUAL_RELATION target을 정확히 하나 추가하고 배열의 첫 target으로 두며
inspection_order=`VISUAL_FIRST`로 한다. 시각자료가 없으면 `CONTENT_FIRST`다. 각 target의 모든 path는
실제 non-null primitive scalar leaf여야 한다. Graph-grounded이면 선택한 evidence_id는 오직 핀된
manifest/context와 solution-report 포인터 안에서 고르고 evidence_references의 부분집합으로 둔다.
필요한 핀 근거가 없으면 일반지식이나 최신 Graph로 보완하지 말고 evidence_status=`INSUFFICIENT`로 둔다.

candidate_findings는 candidate_id 오름차순으로 정렬한다. 각 후보를 독립 풀이, 선택지/진술/해설 대조,
교육과정·기출 패턴·시각 관계와 다시 대조한 뒤 disposition을 정한다. CONFIRMED 후보의 finding_code만
review.findings의 blocking code와 정확히 같아야 한다. DEMOTED는 감사 기록으로 남기되 blocking이나
재작업 근거로 사용하지 않는다. PRIMARY에서 근거만으로 닫을 수 없는 후보는 UNCERTAIN으로 남기되,
ESCALATED에서는 모든 source candidate를 같은 ID/path/evidence로 재검증해 CONFIRMED 또는 DEMOTED로
닫고 UNCERTAIN을 남기지 않는다.

structural_complexity_score는 typed draft에서 다음을 각각 1점으로 계산하고 10 이하로 제한한다: 시각자료
존재, 시각자료 정확히 2개, statements 존재, inquiry 존재, equation_sources 존재, labeled_blocks 정확히
2개. PRIMARY reason_codes는 candidate CONFIRMED/UNCERTAIN이면 CANDIDATE_FINDING_PRESENT, score>=4면
COMPLEX_ITEM, 필수 과학/정답/교육과정 target의 근거 부족이면 EVIDENCE_GAP, UNCERTAIN이면
EVIDENCE_UNCERTAINTY, 시각 후보가 CONFIRMED/UNCERTAIN이면 VISUAL_RISK를 정렬·중복 없이 정확히 둔다.
reason이 있으면 decision=`REQUIRED`, 없으면 `NOT_REQUIRED`다.

REVIEW_ESCALATION_DIRECTIVE_JSON이 `null`이면 PRIMARY다. 이때 review_pass=`PRIMARY`,
source_review_artifact=null로 둔다. 값이 있으면 오케스트레이터가 self-hash와 exact source Artifact,
attempt, 모델 핀을 검증한 ESCALATED pass다. SOURCE_PRIMARY_REVIEW_RESULT_JSON을 처음부터 독립적으로
재검토하되 target/candidate ID와 immutable path/evidence 선택은 바꾸지 않는다. source의 reason_codes와
complexity를 그대로 반복하고 source_review_artifact에는 지시의 exact logical Artifact ID, revision ID,
content hash, result_schema를 기록하며 decision=`COMPLETED`로 둔다. worker끼리 직접 대화한 것으로
간주하거나 추가 강화 실행을 요청하지 않는다.
"""


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
    pack["pack"]["version"] = "1.19.0"
    pack["pack"]["description"] = (
        "Graph verification-planned independent review with bounded stronger-model escalation"
    )
    pack["compatibility"]["protocol"] = {
        "minimum": "1.24.0",
        "maximum_exclusive": "1.25.0",
    }
    pack["compatibility"]["workflow_definitions"][0]["versions"] = ["1.13.0"]
    pack_path.write_text(
        yaml.safe_dump(pack, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    profile_names = {
        "generated-knowledge-authoring.yaml": ("authoring", "12.0.0"),
        "generated-stimulus-drawing.yaml": ("image", "12.0.0"),
        "generated-knowledge-review.yaml": ("review", "12.0.0"),
        "generated-structured-registration.yaml": ("registration", "12.0.0"),
    }
    for name, (role, version) in profile_names.items():
        path = target / "profiles" / name
        profile = yaml.safe_load(path.read_text(encoding="utf-8"))
        profile["profile"]["version"] = version
        profile["input_schema_ref"] = f"eom://workflow/{role}-input@1.24"
        result_role = "item_management" if role == "registration" else role
        result_name = "registration" if result_role == "item_management" else result_role
        profile["output_schema_ref"] = f"{result_name}-result@12.0"
        if role == "review":
            profile["required_context"].extend(
                ("escalation.directive_json", "escalation.source_review_result_json")
            )
        path.write_text(
            yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    for role in ("authoring", "image", "review", "registration"):
        path = target / "prompt-templates" / f"{role}.md"
        text = path.read_text(encoding="utf-8")
        text = text.replace("result@11.0", "result@12.0")
        if role == "review":
            marker = "그 밖의 문제가 없으면 review.decision=`ready_for_human`"
            if marker not in text:
                raise ValueError("review insertion marker is missing")
            text = text.replace(marker, REVIEW_VERIFICATION + "\n" + marker, 1)
        path.write_text(text, encoding="utf-8")


def main() -> None:
    if not TARGET.exists():
        _generate(TARGET)
        return
    with tempfile.TemporaryDirectory(prefix="eom-graph-verification-pack-") as temp_dir:
        generated = Path(temp_dir) / "1.19.0"
        _generate(generated)
        if _tree_bytes(TARGET) != _tree_bytes(generated):
            raise ValueError("generated Content Pack 1.19.0 has drifted")


if __name__ == "__main__":
    main()
