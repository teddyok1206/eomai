#!/usr/bin/env python3
"""Derive an immutable reference-aware successor without modifying released Pack bytes."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "content/packs/generated-knowledge-item/1.20.16"
TARGET = ROOT / "content/packs/generated-knowledge-item/1.20.17"
GUIDANCE = (
    ROOT / "config/control-plane/references/guidance/system-rag-similarity-reference-context-v1.md"
)
MODE_VARIABLE = "similarity.reference_mode"
RULE_MARKER = "BEGIN_SYSTEM_RAG_SIMILARITY_REFERENCE_V1"


def reference_rule() -> str:
    payload = GUIDANCE.read_bytes()
    return (
        "\n\n### System RAG 유사 문항 보조 자료의 고정 연동 지침\n\n"
        "서버가 고정한 이번 실행의 전달 mode: `{{ similarity.reference_mode }}`\n\n"
        "아래 지침은 빌드 시 프롬프트에 포함했다. 별도의 지침 파일이 worker에 있다고 "
        "추측하지 마라. 기존 원문 두 파일과 역할별 지침도 모두 읽고 유지한다.\n\n"
        f"source_sha256=sha256:{hashlib.sha256(payload).hexdigest()}\n\n"
        f"{RULE_MARKER}\n{payload.decode('utf-8').rstrip()}\n"
        "END_SYSTEM_RAG_SIMILARITY_REFERENCE_V1\n"
    )


def tree_bytes(root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(root): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def generate_pack(target: Path) -> None:
    rule = reference_rule()
    prompts = {
        role: (SOURCE / f"prompt-templates/{role}.md").read_text(encoding="utf-8")
        for role in ("authoring", "review")
    }
    if any(RULE_MARKER in prompt for prompt in prompts.values()):
        raise ValueError("similarity reference rule already exists")
    if target.exists():
        raise FileExistsError(target)
    shutil.copytree(SOURCE, target)
    pack_path = target / "pack.yaml"
    pack = yaml.safe_load(pack_path.read_text(encoding="utf-8"))
    pack["pack"]["version"] = "1.20.17"
    pack["pack"]["description"] = (
        "Pinned similarity references with exact Evidence and content-team presentation boundaries"
    )
    pack_path.write_text(
        yaml.safe_dump(pack, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    for role, prompt in prompts.items():
        profile_path = target / f"profiles/generated-knowledge-{role}.yaml"
        profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
        profile["profile"]["version"] = "12.3.0"
        if MODE_VARIABLE in profile["required_context"]:
            raise ValueError("similarity mode already exists")
        profile["required_context"].append(MODE_VARIABLE)
        profile_path.write_text(
            yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        (target / f"prompt-templates/{role}.md").write_text(
            prompt.rstrip() + rule, encoding="utf-8"
        )


def main() -> None:
    if not TARGET.exists():
        generate_pack(TARGET)
        return
    with tempfile.TemporaryDirectory(prefix="eom-similarity-reference-pack-") as temporary:
        generated = Path(temporary) / "1.20.17"
        generate_pack(generated)
        if tree_bytes(TARGET) != tree_bytes(generated):
            raise ValueError("generated Content Pack 1.20.17 has drifted")


if __name__ == "__main__":
    main()
