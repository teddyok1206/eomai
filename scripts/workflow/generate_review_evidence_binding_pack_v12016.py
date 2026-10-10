#!/usr/bin/env python3
"""Create the immutable review evidence-binding clarification successor."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "content/packs/generated-knowledge-item/1.20.15"
TARGET = ROOT / "content/packs/generated-knowledge-item/1.20.16"
RULE_HEADING = "### 검토 근거 교차참조의 exact coverage와 manifest use 결속"

REVIEW_RULE = """

### 검토 근거 교차참조의 exact coverage와 manifest use 결속

`independent_review_report`의 evidence reference는 검색된 모든 근거나 authoring citation의
복사본이 아니다. 검토자가 실제로 내린 판정에 사용한 근거만 기록하며, 다음 집합 관계를 결과
제출 전에 정확히 대조한다. 원본 manifest와 기존 결과 schema의 규칙을 바꾸는 지시가 아니다.
이 절의 Graph 자료 선택 규칙은 `knowledge_source_mode=graph_grounded`일 때 적용한다.
`general_model_knowledge`이면 기존 계약대로 evidence_references와 모든 evidence ID 배열을
비워두며, 이 검사를 채우기 위해 Graph 자료나 ID를 새로 만들지 마라.

```text
U = union(answer_review.claims[*].evidence_ids,
          choice_diagnostics[*].evidence_ids,
          statement_diagnostics[*].evidence_ids,
          explanation_assessment.evidence_ids,
          curriculum_assessment.evidence_ids,
          originality_assessment.evidence_ids,
          visual_assessment.evidence_ids)
R = set(evidence_references[*].evidence_id)
require R == U
require each verification_targets[*].selected_evidence_ids is a subset of R
require each candidate_findings[*].evidence_ids is a subset of R
```

`R == U`는 포함 관계가 아니라 정확한 같음이다. 실제 판정에 사용되지 않은 reference를 남기지
말고, 판정에 사용한 ID의 reference를 빠뜨리지 마라. verification target 또는 candidate에만
등장하는 ID를 추가했다고 해서 U에 포함된 것은 아니다. 이 경우 어떤 실제 판정에 어떤 근거가
필요한지 다시 확인한다. 집합을 맞추기 위해 근거 없는 판정에 ID를 임의로 붙이거나, 필요한
근거·target·candidate를 무조건 지우지 마라. 실제 근거 연결이 확인된 경우에만 관련 판정과
reference를 함께 정정한다. reference 배열은 evidence_id 사전순으로 정렬하고 고유하게 둔다.

각 reference의 `purposes`는 entry의 실제 `use`와 판정 필드를 함께 확인해서 고른다.
authoring citation의 `application` enum을 이 purpose enum으로 복사하지 마라.

| 검토 purpose | 허용되는 manifest entry.use |
|---|---|
| SCIENTIFIC_VALIDATION | GROUNDING, REFERENCE_PATTERN |
| CURRICULUM_SCOPE | GROUNDING, REFERENCE_PATTERN |
| ORIGINALITY_CHECK | REFERENCE_PATTERN, AVOID_COPY |
| VISUAL_VALIDATION | GROUNDING, REFERENCE_PATTERN |

manifest use가 `GROUNDING`인 entry를 ORIGINALITY_CHECK에 사용하지 마라. `AVOID_COPY` entry는
ORIGINALITY_CHECK에만 사용할 수 있으며 과학적 타당성·교육과정 적합성·시각 일치의 긍정적
근거로 쓰지 마라. entry의 `answer_bearing=true`이면 use가 무엇이든 ORIGINALITY_CHECK 외의
purpose를 붙이거나 다른 판정의 근거로 사용하지 마라. 모든 reference에 모든 purpose를
관성적으로 나열하지 마라.

answer_review.claims·choice_diagnostics·statement_diagnostics·explanation_assessment에서
사용한 각 ID에는 SCIENTIFIC_VALIDATION이 있어야 한다. curriculum_assessment에서 사용한
각 ID에는 CURRICULUM_SCOPE, originality_assessment에는 ORIGINALITY_CHECK,
visual_assessment에는 VISUAL_VALIDATION이 있어야 한다. 같은 entry를 두 판정에 실제로
재사용할 수 있을 때만 필요한 purpose들을 함께 기록한다.

마지막으로 모든 ID와 anchor를 핀된 manifest/context에서 exact lookup하고, manifest/5.0이면
solution_evidence가 연결된 근거를 SCIENTIFIC_VALIDATION에 실제로 사용했는지 확인한다.
answer-bearing 또는 AVOID_COPY 근거를 이 요구를 채우는 데 대신 쓰지 마라.
자료가 충분하지 않으면 부족함을 명시하고 기존 계약대로 역할 실행을 실패시킨다.
새 evidence ID·anchor·receipt를 만들거나
다른 Graph revision·latest 자료·일반 지식으로 빈 근거 연결을 위장하지 마라.
"""


def tree_bytes(root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(root): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def generate_pack(target: Path) -> None:
    prompt = (SOURCE / "prompt-templates/review.md").read_text(encoding="utf-8")
    if RULE_HEADING in prompt:
        raise ValueError("review evidence-binding rule already exists")
    if target.exists():
        raise FileExistsError(target)
    shutil.copytree(SOURCE, target)

    pack_path = target / "pack.yaml"
    pack = yaml.safe_load(pack_path.read_text(encoding="utf-8"))
    pack["pack"]["version"] = "1.20.16"
    pack["pack"]["description"] = (
        "Exact review evidence coverage and manifest-purpose binding with natural presentation"
    )
    pack_path.write_text(
        yaml.safe_dump(pack, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    profile_path = target / "profiles/generated-knowledge-review.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["profile"]["version"] = "12.2.2"
    profile_path.write_text(
        yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    (target / "prompt-templates/review.md").write_text(
        prompt.rstrip() + REVIEW_RULE, encoding="utf-8"
    )


def main() -> None:
    if not TARGET.exists():
        generate_pack(TARGET)
        return
    with tempfile.TemporaryDirectory(prefix="eom-review-evidence-binding-pack-") as temporary:
        generated = Path(temporary) / "1.20.16"
        generate_pack(generated)
        if tree_bytes(TARGET) != tree_bytes(generated):
            raise ValueError("generated Content Pack 1.20.16 has drifted")


if __name__ == "__main__":
    main()
