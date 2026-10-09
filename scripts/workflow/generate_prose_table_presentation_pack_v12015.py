#!/usr/bin/env python3
"""Materialize one editorial clarification into an immutable compatible pack."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import yaml
from eom_identifiers import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "content/packs/generated-knowledge-item/1.20.14"
TARGET = ROOT / "content/packs/generated-knowledge-item/1.20.15"
GUIDANCE = (
    ROOT / "config/control-plane/references/guidance/content-team-hwp-question-editor-handoff-v2.md"
)
PRESENTATION_HEADING = "## Student-visible presentation intent\n"
NEXT_HEADING = "## Inquiry and equations\n"
RULE_HEADING = "### 발문·native TABLE의 제시 의도 V2"


def presentation_rule() -> str:
    source_bytes = GUIDANCE.read_bytes()
    guidance = source_bytes.decode("utf-8")
    if guidance.count(PRESENTATION_HEADING) != 1 or guidance.count(NEXT_HEADING) != 1:
        raise ValueError("presentation guidance section boundaries differ")
    rule = guidance.split(PRESENTATION_HEADING, 1)[1].split(NEXT_HEADING, 1)[0].strip()
    if not rule:
        raise ValueError("presentation guidance is empty")
    return (
        f"\n\n{RULE_HEADING}\n\n"
        f"연동 지침: content-team-hwp-question-editor-handoff/2.0, "
        f"source_sha256={sha256_bytes(source_bytes)}.\n"
        "다음은 이 Pack에 결속된 연동 지침의 원문 발췌다. V1 handoff의 지원 문법은 유지하고,\n"
        "'boxed source가 필요할 때'의 제시 의도는 아래 기준으로 구분한다. workspace에 별도의\n"
        "V2 파일이 있다고 추측하지 마라. 새 output schema나 고정 material requirement를 만들거나\n"
        "바꾸는 지시가 아니다.\n\n"
        "BEGIN_CONTENT_TEAM_PRESENTATION_V2\n"
        f"{rule}\n"
        "END_CONTENT_TEAM_PRESENTATION_V2\n"
    )


def tree_bytes(root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(root): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def generate_pack(target: Path) -> None:
    # Validate the single source before creating any candidate files. Never replace a release.
    rule = presentation_rule()
    if target.exists():
        raise FileExistsError(target)
    shutil.copytree(SOURCE, target)
    pack_path = target / "pack.yaml"
    pack = yaml.safe_load(pack_path.read_text(encoding="utf-8"))
    pack["pack"]["version"] = "1.20.15"
    pack["pack"]["description"] = (
        "Natural stem and balanced native-table presentation from content-team handoff V2"
    )
    pack_path.write_text(
        yaml.safe_dump(pack, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    for role in ("authoring", "review"):
        profile_path = target / f"profiles/generated-knowledge-{role}.yaml"
        profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
        profile["profile"]["version"] = "12.2.1"
        profile_path.write_text(
            yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        prompt_path = target / f"prompt-templates/{role}.md"
        prompt = prompt_path.read_text(encoding="utf-8")
        if RULE_HEADING in prompt:
            raise ValueError(f"presentation rule already exists in {role}")
        prompt_path.write_text(prompt.rstrip() + rule, encoding="utf-8")


def main() -> None:
    if not TARGET.exists():
        generate_pack(TARGET)
        return
    with tempfile.TemporaryDirectory(prefix="eom-prose-table-pack-") as temp_dir:
        generated = Path(temp_dir) / "1.20.15"
        generate_pack(generated)
        if tree_bytes(TARGET) != tree_bytes(generated):
            raise ValueError("generated Content Pack 1.20.15 has drifted")


if __name__ == "__main__":
    main()
