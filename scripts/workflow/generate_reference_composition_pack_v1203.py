#!/usr/bin/env python3
"""Create immutable Content Pack 1.20.3 for exact reference composition."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "content/packs/generated-knowledge-item/1.20.2"
TARGET = ROOT / "content/packs/generated-knowledge-item/1.20.3"

IMAGE_POLICY = r"""

## Exact visual-reference composition policy

HYBRID_LOCAL_GENERATIVE를 선택하면 Catalog는 이 Pack에서 승인된 visual reference의 정확한 bytes를
V1 reference-conditioned provider에 전달한다. 참조의 대상 개수, 좌우 방향, 앞·뒤, 실루엣, 자세,
시점, 상대 위치, 겹침과 framing은 스타일 요소가 아니라 보존해야 할 구성이다. 참조가 오른쪽을 향하면
결과도 오른쪽을 향해야 하고, 왼쪽을 향하면 결과도 왼쪽을 향해야 한다. 좌우 반전, 시점 변경,
대상 추가·삭제·복제 또는 crop은 금지한다.

`alt_text`에는 실제 필요한 방향이 있으면 `facing right` 또는 `facing left`를 정확히 포함한다. 방향이
문항 의미에 없으면 임의로 추가하지 않는다. 로컬 GPU는 참조 구성 위에 시험지용 흑백 선화 스타일만
적용한다. 과학적으로 권위 있는 화살표, 충돌 벽, 문자, 수치와 위치 관계는 기존대로 deterministic SVG
overlay가 담당한다. 참조가 필요한 구도를 제공하지 못하면 text-to-image로 조용히 대체하지 말고 역할
실행을 실패시킨다.
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
    pack["pack"]["version"] = "1.20.3"
    pack["pack"]["description"] = "Graph-grounded review and exact reference composition"
    pack_path.write_text(
        yaml.safe_dump(pack, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    profile_path = target / "profiles/generated-stimulus-drawing.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["profile"]["version"] = "12.2.2"
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
    with tempfile.TemporaryDirectory(prefix="eom-reference-composition-pack-") as temp_dir:
        generated = Path(temp_dir) / "1.20.3"
        _generate(generated)
        if _tree_bytes(TARGET) != _tree_bytes(generated):
            raise ValueError("generated Content Pack 1.20.3 has drifted")


if __name__ == "__main__":
    main()
