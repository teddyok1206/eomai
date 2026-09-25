#!/usr/bin/env python3
"""Create immutable Content Pack 1.20 with benchmarked local-image instructions."""

# ruff: noqa: E501 -- Exact Korean prompt prose is immutable release input.

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "content/packs/generated-knowledge-item/1.19.0"
TARGET = ROOT / "content/packs/generated-knowledge-item/1.20.0"

IMAGE_POLICY = r"""

## Local GPU subject and routing contract

520개 occurrence-backed 기출 분석의 시각 패턴과 고정 SSD-1B 비교 실험에서, 짧은 한국어 subject는
관련 없는 인물 사진으로 붕괴했고 같은 대상을 영어로 기술하면 의미 정확도가 회복되었다. 또한
`black and white Korean science exam illustration` 스타일을 명시한 영어 subject가 사진 질감을 줄이고
시험지용 흑백 선화에 가장 가깝게 수렴했다. 이 관찰은 팀장 원문 두 개나 KICE 삽화 가이드를 바꾸지
않으며, 로컬 모델에 전달하는 비권위 raster subject만 제한한다.

`HYBRID_LOCAL_GENERATIVE`는 비인간 동물·유기물·복잡한 자연 질감·현실 자연 장면처럼 raster 표현이
실제로 필요한 경우에만 사용한다. 그래프, 지도, 실험 장치, 입자 모형, 셀 구조, 축·수치·화살표·경계,
정답을 좌우하는 정확한 기하와 사람은 `DETERMINISTIC_SVG`로 만든다. 자연 장면이라도 정확한 위치나
관계가 정답에 쓰이면 그 권위 요소는 SVG overlay가 담당한다. GPU에는 사람을 요청하지 않는다.

HYBRID drawing의 `alt_text`는 로컬 모델이 받을 **영어 subject**로 작성한다. 3~180 ASCII 문자이며
대상·개수·관계만 한 문장으로 기록한다. 허용 문자는 영문자, 숫자, 공백과 `, . ' ( ) / _ -`뿐이다.
스타일, 색, 글자, 숫자 label, 정답, 패널 label은 적지 않는다. 예시는
`one trilobite fossil isolated on white`처럼 쓰되 실제 문항 대상을 그대로 기술한다. 한국어 전체 설명과
접근성 의미는 `scene_description`과 `scientific_constraints`에 보존한다. `generation_prompt`는 계속
팀장의 exact `illustration_prompt`와 같아야 하고, `negative_prompt`는 `null`이다. Catalog가 영어
subject에 검증된 시험지 선화 prefix와 고정 음성 제약을 붙이고 그 policy revision과 prompt hash를
provider request identity에 포함한다. 조건을 만족하는 subject를 만들 수 없으면 임의 번역이나 일반
이미지로 대체하지 말고 작업을 실패시킨다.

`electronic component`, `cell`, `car`처럼 대상 종류만 적는 추상 subject는 금지한다. 생성 결과만 보아도
문항의 대상을 구별할 수 있도록 정확한 개수, 시점(side view/cross-section 등), 외형, 핵심 물리 상태를
포함한다. 다만 정답을 암시하는 문자·수치와 SVG가 담당할 권위 관계는 넣지 않는다. 예를 들어 충돌
차량이면 `one compact car in side view with the front bumper visibly crumpled after impact, isolated on
white`처럼 상태까지 명시한다.
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
    pack["pack"]["version"] = "1.20.0"
    pack["pack"]["description"] = (
        "Graph verification-planned review with benchmarked local assessment illustration prompts"
    )
    pack_path.write_text(
        yaml.safe_dump(pack, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    profile_path = target / "profiles/generated-stimulus-drawing.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["profile"]["version"] = "12.1.0"
    profile_path.write_text(
        yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    image_path = target / "prompt-templates/image.md"
    image_path.write_text(
        image_path.read_text(encoding="utf-8").rstrip() + "\n\n" + IMAGE_POLICY.strip() + "\n",
        encoding="utf-8",
    )


def main() -> None:
    if not TARGET.exists():
        _generate(TARGET)
        return
    with tempfile.TemporaryDirectory(prefix="eom-assessment-image-pack-") as temp_dir:
        generated = Path(temp_dir) / "1.20.0"
        _generate(generated)
        if _tree_bytes(TARGET) != _tree_bytes(generated):
            raise ValueError("generated Content Pack 1.20.0 has drifted")


if __name__ == "__main__":
    main()
