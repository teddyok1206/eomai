#!/usr/bin/env python3
"""Create immutable Content Pack 1.20.5 for the V5 assessment line-art route."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "content/packs/generated-knowledge-item/1.20.4"
TARGET = ROOT / "content/packs/generated-knowledge-item/1.20.5"


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
    pack["pack"]["version"] = "1.20.5"
    pack["pack"]["description"] = (
        "Graph-grounded review, exact reference composition, and deterministic assessment line art"
    )
    pack_path.write_text(
        yaml.safe_dump(pack, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def main() -> None:
    if not TARGET.exists():
        _generate(TARGET)
        return
    with tempfile.TemporaryDirectory(prefix="eom-assessment-line-art-pack-") as temp_dir:
        generated = Path(temp_dir) / "1.20.5"
        _generate(generated)
        if _tree_bytes(TARGET) != _tree_bytes(generated):
            raise ValueError("generated Content Pack 1.20.5 has drifted")


if __name__ == "__main__":
    main()
