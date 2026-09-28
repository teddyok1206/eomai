#!/usr/bin/env python3
"""Create immutable Content Pack 1.20.4 for transparent HYBRID SVG overlays."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "content/packs/generated-knowledge-item/1.20.3"
TARGET = ROOT / "content/packs/generated-knowledge-item/1.20.4"

IMAGE_POLICY = r"""

## Transparent local-raster overlay policy

`LOCAL_GENERATIVE_BACKGROUND` 또는 `HYBRID_LOCAL_GENERATIVE` drawing의 `svg_overlay`는 반드시
투명 캔버스여야 한다. `<rect x="0" y="0" width="800" height="500" ...>`처럼 800x500 전체를
덮는 흰색·회색·검은색 또는 그 밖의 불투명 배경 도형을 절대 만들지 마라. SVG root에도 배경색을
추가하지 마라. 전체 캔버스 배경은 참조-conditioned raster를 가려 버리므로 허용되지 않는다.

이 두 route의 SVG에는 정답 판단에 필요한 문자·수치·화살표·축·벽·안내선과 제한된 권위 도형만
놓는다. 각 요소에 필요한 `fill="none"` 또는 개별 평면색은 사용할 수 있지만, 배경을 흰색으로
만들기 위한 도형은 넣지 않는다. 흰 시험지 배경은 최종 renderer가 담당하고 사물의 외형·질감은
로컬 GPU/reference raster가 담당한다. 최종 rasterizer가 800x500 RGBA 투명 overlay를 만들 수 없는
SVG를 제출하지 마라.
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
    pack["pack"]["version"] = "1.20.4"
    pack["pack"]["description"] = (
        "Graph-grounded review, exact reference composition, and transparent SVG overlay"
    )
    pack_path.write_text(
        yaml.safe_dump(pack, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    profile_path = target / "profiles/generated-stimulus-drawing.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["profile"]["version"] = "12.2.3"
    profile_path.write_text(
        yaml.safe_dump(profile, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    image_path = target / "prompt-templates/image.md"
    image_path.write_text(
        image_path.read_text(encoding="utf-8").rstrip() + "\n" + IMAGE_POLICY,
        encoding="utf-8",
    )


def main() -> None:
    if not TARGET.exists():
        _generate(TARGET)
        return
    with tempfile.TemporaryDirectory(prefix="eom-hybrid-overlay-transparency-pack-") as temp_dir:
        generated = Path(temp_dir) / "1.20.4"
        _generate(generated)
        if _tree_bytes(TARGET) != _tree_bytes(generated):
            raise ValueError("generated Content Pack 1.20.4 has drifted")


if __name__ == "__main__":
    main()
