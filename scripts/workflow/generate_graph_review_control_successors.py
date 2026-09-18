#!/usr/bin/env python3
"""Generate immutable control successors for Graph-grounded independent review.

This is a deterministic repository generator.  It copies the reviewed V14/V11
predecessors, changes only the protocol/result identities and review contract,
then pins the exact V15 instruction member hashes in the V12 knowledge preset.
Existing targets are never overwritten.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
STANDARD_SOURCE = ROOT / "config/control-plane/standard-item-v14"
STANDARD_TARGET = ROOT / "config/control-plane/standard-item-v15"
KNOWLEDGE_SOURCE = ROOT / "config/control-plane/knowledge-grounded-item-v11"
KNOWLEDGE_TARGET = ROOT / "config/control-plane/knowledge-grounded-item-v12"

REVIEW_SUFFIX = """

Independently solve the authored item rather than assuming its answer and explanation are correct.
Return review-result@11.0 with a bounded `independent_review_report`; never expose free-form hidden
reasoning or chain-of-thought. Record only concise conclusions, rationales, exact canonical draft
JSON pointers, and selected Evidence IDs. Diagnose choices ① through ⑤ exactly once and mark only
the independently derived answer `CORRECT`. If ㄱ/ㄴ/ㄷ statements exist, diagnose all three; if
they do not exist, return an empty statement diagnostic array.

For Graph-grounded review, use Evidence Bundle manifest/5.0 and require at least one entry carrying
an immutable `solution_evidence` pointer for `SCIENTIFIC_VALIDATION`. Use only the context's bounded
`assessment_design_summary` and `reusable_generation_guidance`; do not copy a source item's final
answer or full explanation. Independently assess the answer, every choice, optional statements,
explanation consistency, curriculum scope, originality, and visual/content consistency. Every
declared review Evidence ID must appear in the staged manifest, use an allowed purpose, and resolve
only to non-null scalar draft leaves. The orchestrator, not the worker, resolves solution-report
pointers and produces the trusted validation receipt.

Return the exact blocking code for each failed axis: `INDEPENDENT_ANSWER_MISMATCH`,
`EXPLANATION_INCONSISTENT`, `CURRICULUM_SCOPE_INVALID`, `ORIGINALITY_RISK`,
`ORIGINALITY_EVIDENCE_INSUFFICIENT`, or `VISUAL_CONTENT_INCONSISTENT`. Only a fully consistent item
may be `ready_for_human`; human approval remains mandatory.
"""


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _stable_id(prefix: str, key: str) -> str:
    digest = hashlib.sha256(f"eom-standard-control-v1:{key}".encode()).hexdigest()
    return prefix + digest[:32]


def _write_json_pair(source_name: str, target_name: str, replacements: dict[str, str]) -> None:
    canonical_source = ROOT / "schemas/workflow/control-plane" / source_name
    canonical_target = ROOT / "schemas/workflow/control-plane" / target_name
    packaged_target = ROOT / "packages/workflow/eom_workflow/resources/control-plane" / target_name
    if canonical_target.exists() or packaged_target.exists():
        raise FileExistsError(target_name)
    text = canonical_source.read_text(encoding="utf-8")
    for old, new in replacements.items():
        text = text.replace(old, new)
    value = json.loads(text)
    payload = json.dumps(value, ensure_ascii=False, indent=2).encode() + b"\n"
    canonical_target.write_bytes(payload)
    packaged_target.write_bytes(payload)


def _generate_standard() -> None:
    if STANDARD_TARGET.exists():
        raise FileExistsError(STANDARD_TARGET)
    shutil.copytree(STANDARD_SOURCE, STANDARD_TARGET)
    bootstrap_path = STANDARD_TARGET / "bootstrap.yaml"
    bootstrap = yaml.safe_load(bootstrap_path.read_text(encoding="utf-8"))
    bootstrap.update(
        {
            "schema_version": "standard-control-bootstrap/15.0",
            "display_name": "표준 문항 제작 · Graph 독립 검토 계약",
            "description": (
                "풀이보고서가 결속된 Graph 근거로 정답·선택지·교육과정·독창성·시각자료를 "
                "독립 검토하는 표준 문항 제작 정책입니다."
            ),
            "created_at": "2026-09-18T00:00:00Z",
            "compatible_workflow_protocols": ["workflow-role/1.23.0"],
        }
    )
    bootstrap_path.write_text(
        yaml.safe_dump(bootstrap, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    for name in ("authoring.md", "image.md", "item-management.md", "review.md"):
        path = STANDARD_TARGET / "instructions" / name
        text = path.read_text(encoding="utf-8").replace("@10.0", "@11.0")
        if name == "review.md":
            text = text.rstrip() + REVIEW_SUFFIX
        path.write_text(text, encoding="utf-8")


def _generate_knowledge() -> None:
    if KNOWLEDGE_TARGET.exists():
        raise FileExistsError(KNOWLEDGE_TARGET)
    shutil.copytree(KNOWLEDGE_SOURCE, KNOWLEDGE_TARGET)
    path = KNOWLEDGE_TARGET / "bootstrap.yaml"
    bootstrap = yaml.safe_load(path.read_text(encoding="utf-8"))
    bootstrap.update(
        {
            "schema_version": "knowledge-item-control-bootstrap/12.0",
            "display_name": "Graph 풀이보고서 기반 통합과학 독립 검토",
            "description": (
                "검증된 교과서·기출 Graph 근거와 additive 풀이보고서를 표준 독립 검토 정책에 "
                "결속하는 통합과학 정책입니다."
            ),
            "created_at": "2026-09-18T00:05:00Z",
            "compatible_workflow_protocols": ["workflow-role/1.23.0"],
            "base_instruction_bundle_revision_ids": {
                role: _stable_id("instrrev_", f"standard-item:{role}:v15")
                for role in ("authoring", "image", "review", "item_management")
            },
            "base_instruction_member_sha256s": {
                "platform": _sha256(STANDARD_TARGET / "instructions/platform.md"),
                "authoring": _sha256(STANDARD_TARGET / "instructions/authoring.md"),
                "image": _sha256(STANDARD_TARGET / "instructions/image.md"),
                "review": _sha256(STANDARD_TARGET / "instructions/review.md"),
                "item_management": _sha256(STANDARD_TARGET / "instructions/item-management.md"),
            },
        }
    )
    path.write_text(
        yaml.safe_dump(bootstrap, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def main() -> None:
    _write_json_pair(
        "standard-control-bootstrap-v14.schema.json",
        "standard-control-bootstrap-v15.schema.json",
        {
            "standard-control-bootstrap/14.0": "standard-control-bootstrap/15.0",
            "V14": "V15",
            "workflow-role/1.20.0": "workflow-role/1.23.0",
        },
    )
    _generate_standard()
    _generate_knowledge()
    _write_json_pair(
        "knowledge-item-control-bootstrap-v11.schema.json",
        "knowledge-item-control-bootstrap-v12.schema.json",
        {
            "knowledge-item-control-bootstrap/11.0": ("knowledge-item-control-bootstrap/12.0"),
            "V11": "V12",
            "workflow-role/1.20.0": "workflow-role/1.23.0",
            **{
                old: new
                for old, new in zip(
                    (
                        "instrrev_4f9222ae43e2888182d5638485ce5571",
                        "instrrev_0a2cf0ffb0f68d573534f1777b4504a8",
                        "instrrev_ad5bda678de0e23872c75a72cfdd5a32",
                        "instrrev_7ccd6d6c1b36ba5c12370bc3d460a559",
                    ),
                    (
                        "instrrev_f6b5237c9e635e3aba9d33f41369b8e3",
                        "instrrev_c9e473bc085a1b878afc2dc9a72ee788",
                        "instrrev_11820f6f455fc43286c2c65b3832cb0b",
                        "instrrev_5d5eec49d02f10eb629e2440a9e495fd",
                    ),
                    strict=True,
                )
            },
            **{
                old.removeprefix("sha256:"): new.removeprefix("sha256:")
                for old, new in zip(
                    (
                        "sha256:5a3cfab6dc1c195ebc93cb13c7549cd31ea30f6229a4b134bed818d9dd69271b",
                        "sha256:a638fc707723770b85222c8eae8321f0a65373613b0a2c1f9b0250235a7ed913",
                        "sha256:4641d2fdeb7d78431d2b00190c117c6b27433e02f14c3750a89fbefbde0cdfb2",
                        "sha256:9b7f5d27d5f08b82e39572bd3f42e30b38b0513294e619859ba4026042941682",
                        "sha256:8ba95a2d3dbad009d04dd7aee122a1b592429cebee08fa738fe26798ce1194ed",
                    ),
                    tuple(
                        _sha256(STANDARD_TARGET / "instructions" / name)
                        for name in (
                            "platform.md",
                            "authoring.md",
                            "image.md",
                            "review.md",
                            "item-management.md",
                        )
                    ),
                    strict=True,
                )
            },
        },
    )


if __name__ == "__main__":
    main()
