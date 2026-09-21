#!/usr/bin/env python3
"""Create Standard Item control V17 for bounded stronger item review."""

# ruff: noqa: E501 -- Exact instruction prose is hashed immutable control input.

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "config/control-plane/standard-item-v16"
TARGET = ROOT / "config/control-plane/standard-item-v17"

REVIEW_RULES = """

## Verification-planned review

Return `independent-item-review/2.0` inside review-result@12.0. Build the bounded verification target
set before the verdict, inspect authored visuals first when present, and preserve every suspected
issue as a typed candidate with an explicit CONFIRMED, DEMOTED, or UNCERTAIN disposition. Use only
the immutable Graph/Evidence/solution-report materials staged by the orchestrator. Never query or
substitute a mutable latest Graph revision. A missing required pin is INSUFFICIENT, not permission to
invent support.

The first pass is PRIMARY. Perform an ESCALATED pass only when the orchestrator supplies the exact
self-hashed escalation directive and source review Artifact. Preserve its target and candidate
identity set, close every UNCERTAIN candidate, and do not request another escalation. Only confirmed
candidates may become blocking findings. Do not expose hidden reasoning transcripts; return concise
auditable conclusions, exact scalar draft leaves, and Evidence IDs.
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
    bootstrap_path = target / "bootstrap.yaml"
    document = yaml.safe_load(bootstrap_path.read_text(encoding="utf-8"))
    document["schema_version"] = "standard-control-bootstrap/17.0"
    document["display_name"] = "표준 문항 제작 · Graph 검증 계획과 제한 강화 검토"
    document["description"] = (
        "Graph 검증 대상·후보 재확인과 한 번의 강화 검토를 오케스트레이터가 결속하는 정책입니다."
    )
    document["created_at"] = "2026-09-21T00:00:00Z"
    document["compatible_workflow_protocols"] = ["workflow-role/1.24.0"]
    document["review_escalation_model"] = "gpt-5.6-terra"
    document["review_escalation_reasoning_effort"] = "xhigh"
    bootstrap_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    for path in sorted((target / "instructions").glob("*.md")):
        text = path.read_text(encoding="utf-8").replace("result@11.0", "result@12.0")
        if path.name == "review.md":
            text = text.rstrip() + REVIEW_RULES
        path.write_text(text, encoding="utf-8")


def main() -> None:
    if not TARGET.exists():
        _generate(TARGET)
        return
    with tempfile.TemporaryDirectory(prefix="eom-standard-review-v17-") as temp_dir:
        generated = Path(temp_dir) / "standard-item-v17"
        _generate(generated)
        if _tree_bytes(TARGET) != _tree_bytes(generated):
            raise ValueError("generated Standard Item V17 has drifted")


if __name__ == "__main__":
    main()
