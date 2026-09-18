#!/usr/bin/env python3
"""Create the immutable Graph-review Content Pack successor from 1.16.1."""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "content/packs/generated-knowledge-item/1.16.1"
TARGET = ROOT / "content/packs/generated-knowledge-item/1.17.0"
REVIEW_INSERTION = """정답과 해설을 맞다고 전제하지 말고 문항을 처음부터 독립적으로 풀어라.
자유로운 사고 기록이나 숨은 추론 전문을 출력하지 말고, 검증 가능한 짧은 conclusion, rationale,
canonical draft JSON pointer와 evidence_id만 independent_review_report에 남긴다.

Evidence Bundle manifest/5.0 entry의 solution_evidence는 기존 승인 기출의 additive 풀이보고서
포인터다. graph_grounded 검토에서는 최소 하나의 solution_evidence가 연결된 entry를
SCIENTIFIC_VALIDATION에 사용하고, context.md의 assessment_design_summary와
reusable_generation_guidance를 과학 관계와 출제요소 검증에 활용한다. final answer나 원문 해설을
복제하지 않는다. answer_bearing=true 근거는 ORIGINALITY_CHECK 외의 긍정적 판정에 사용하지 않는다.

①~⑤를 각각 정확히 한 번 판정하고 독립적으로 도출한 정답 하나만 CORRECT로 둔다. ㄱ/ㄴ/ㄷ 진술이
있으면 세 진술을 각각 TRUE/FALSE로 판정하고, 없으면 statement_diagnostics를 빈 배열로 둔다.
정답·오답 해설 일관성, curriculum_scope 적합성, 기출과의 과도한 유사성, 표·그림·DATA와 본문 간
일관성을 서로 독립된 assessment로 작성한다. 모든 경로는 실제 authoring draft의 non-null scalar
leaf로 해석되어야 한다.

독립 정답이 다르면 INDEPENDENT_ANSWER_MISMATCH, 해설이 모순이면 EXPLANATION_INCONSISTENT,
범위 밖이거나 불확실하면 CURRICULUM_SCOPE_INVALID, 기출을 지나치게 복제하면 ORIGINALITY_RISK,
비교 근거가 부족하면 ORIGINALITY_EVIDENCE_INSUFFICIENT, 시각자료가 본문과 모순이면
VISUAL_CONTENT_INCONSISTENT를 blocking finding으로 정확히 추가한다."""


def _replace(path: Path, replacements: tuple[tuple[str, str], ...]) -> None:
    value = path.read_text(encoding="utf-8")
    for old, new in replacements:
        if old not in value:
            raise ValueError(f"expected predecessor text is missing from {path}: {old}")
        value = value.replace(old, new)
    path.write_text(value, encoding="utf-8")


def main() -> None:
    if TARGET.exists():
        raise FileExistsError(f"successor already exists: {TARGET}")
    shutil.copytree(SOURCE, TARGET)

    pack_path = TARGET / "pack.yaml"
    pack = yaml.safe_load(pack_path.read_text(encoding="utf-8"))
    pack["pack"]["version"] = "1.17.0"
    pack["pack"]["description"] = (
        "Solution-enriched Graph RAG with independent answer, choice, curriculum, "
        "originality, visual, and explanation review"
    )
    pack["compatibility"]["protocol"] = {
        "minimum": "1.23.0",
        "maximum_exclusive": "1.24.0",
    }
    pack["compatibility"]["workflow_definitions"][0]["versions"] = ["1.11.0"]
    pack_path.write_text(
        yaml.safe_dump(pack, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    profile_changes = {
        "generated-knowledge-authoring.yaml": (
            ('version: "10.1.1"', 'version: "11.0.0"'),
            ("authoring-input@1.20", "authoring-input@1.23"),
            ("authoring-result@10.0", "authoring-result@11.0"),
        ),
        "generated-stimulus-drawing.yaml": (
            ('version: "10.0.7"', 'version: "11.0.0"'),
            ("image-input@1.20", "image-input@1.23"),
            ("image-result@10.0", "image-result@11.0"),
        ),
        "generated-knowledge-review.yaml": (
            ('version: "10.1.1"', 'version: "11.0.0"'),
            ("review-input@1.20", "review-input@1.23"),
            ("review-result@10.0", "review-result@11.0"),
        ),
        "generated-structured-registration.yaml": (
            ('version: "10.0.0"', 'version: "11.0.0"'),
            ("registration-input@1.20", "registration-input@1.23"),
            ("registration-result@10.0", "registration-result@11.0"),
        ),
    }
    for name, replacements in profile_changes.items():
        _replace(TARGET / "profiles" / name, replacements)

    _replace(
        TARGET / "prompt-templates/authoring.md",
        (("authoring-result@10.0", "authoring-result@11.0"),),
    )
    _replace(
        TARGET / "prompt-templates/image.md",
        (("authoring-result@10.0", "authoring-result@11.0"),),
    )
    _replace(
        TARGET / "prompt-templates/registration.md",
        (("registration-result@10.0", "registration-result@11.0"),),
    )
    _replace(
        TARGET / "prompt-templates/review.md",
        (
            ("authoring-result@10.0", "authoring-result@11.0"),
            (
                "그 밖의 문제가 없으면 review.decision=`ready_for_human`, review.findings=[], "
                "한국어 summary를 반환하라.",
                REVIEW_INSERTION + "\n\n"
                "그 밖의 문제가 없으면 review.decision=`ready_for_human`, review.findings=[], "
                "한국어 summary를 반환하라.",
            ),
        ),
    )


if __name__ == "__main__":
    main()
