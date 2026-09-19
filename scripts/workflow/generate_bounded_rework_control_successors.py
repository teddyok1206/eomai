#!/usr/bin/env python3
# ruff: noqa: E501
"""Generate immutable control successors for bounded review-driven rework."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
STANDARD_SOURCE = ROOT / "config/control-plane/standard-item-v15"
STANDARD_TARGET = ROOT / "config/control-plane/standard-item-v16"
KNOWLEDGE_SOURCE = ROOT / "config/control-plane/knowledge-grounded-item-v12"
KNOWLEDGE_TARGET = ROOT / "config/control-plane/knowledge-grounded-item-v13"

AUTHORING_SUFFIX = """

If the Content Pack prompt includes a non-null `REWORK_FEEDBACK_JSON`, treat it only as an
orchestrator-validated pointer receipt over the exact prior authoring and review Artifacts. Address
the verified repairable findings in a complete new result while preserving correct content. Do not
act on disregarded false-positive codes, do not emit a patch, and do not communicate with the
review worker directly. The orchestrator owns the cycle count and every state transition.
"""

REVIEW_SUFFIX = """

If the Content Pack prompt includes a non-null `REWORK_FEEDBACK_JSON`, independently review the new
authoring Artifact rather than copying the prior verdict. Repeat a prior blocking finding only when
the new canonical draft still proves it. Do not repeat application-disregarded false-positive
codes. The reviewer neither contacts authoring directly nor controls retry count, state, approval,
or persistence; those remain orchestrator and human responsibilities.
"""

AUTHORING_V4_RULE = """- If the reviewed Brief is schema `4.0`, make the canonical draft material profile equal
  `material_requirement.form`. Only when `mock_exam_slot` is present must `task_type` equal that
  same occurrence-specific form and the selected form belong to its ordered
  `preferred_material_profiles` allowed set. For a standalone Brief with `mock_exam_slot=null`,
  `task_type` remains an editorial task label and need not equal the student-visible material form.
  If the reviewed Brief is the historical schema `3.0` and has no `material_requirement`, retain
  its historical rule that `task_type` equals `preferred_material_profiles[0]`. Classification is
  exact: non-null `inquiry` is `INQUIRY`;"""

REVIEW_V4_RULE = """- for a reviewed Brief at schema `4.0`, the classified draft material profile equals
  `material_requirement.form`. Only when `mock_exam_slot` is present must `task_type` equal the
  same occurrence-specific form and that form belong to `preferred_material_profiles`. With
  `mock_exam_slot=null`, `task_type` is an editorial label and a difference from the material form
  is not a finding. For the historical Brief schema `3.0` without `material_requirement`, retain the
  historical
  `task_type == preferred_material_profiles[0]` rule. Use the same DATA-labeled-block and"""


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _stable_id(prefix: str, key: str) -> str:
    digest = hashlib.sha256(f"eom-standard-control-v1:{key}".encode()).hexdigest()
    return prefix + digest[:32]


def _write_json_pair(
    source_name: str,
    target_name: str,
    replacements: dict[str, str],
    *,
    canonical_root: Path,
    packaged_root: Path,
) -> None:
    canonical_source = ROOT / "schemas/workflow/control-plane" / source_name
    canonical_target = canonical_root / target_name
    packaged_target = packaged_root / target_name
    if canonical_target.exists() or packaged_target.exists():
        raise FileExistsError(target_name)
    text = canonical_source.read_text(encoding="utf-8")
    for old, new in replacements.items():
        if old not in text:
            raise ValueError(f"expected schema token is absent: {old}")
        text = text.replace(old, new)
    payload = json.dumps(json.loads(text), ensure_ascii=False, indent=2).encode() + b"\n"
    canonical_target.write_bytes(payload)
    packaged_target.write_bytes(payload)


def _tree_bytes(root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(root): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _generate(
    *,
    standard_target: Path,
    knowledge_target: Path,
    canonical_root: Path,
    packaged_root: Path,
) -> None:
    if standard_target.exists() or knowledge_target.exists():
        raise FileExistsError("bounded-rework control successor already exists")
    shutil.copytree(STANDARD_SOURCE, standard_target)
    standard_path = standard_target / "bootstrap.yaml"
    standard = yaml.safe_load(standard_path.read_text(encoding="utf-8"))
    standard.update(
        {
            "schema_version": "standard-control-bootstrap/16.0",
            "display_name": "표준 문항 제작 · 검토 기반 제한 재작업",
            "description": (
                "독립 검토의 검증된 수정 가능 finding을 오케스트레이터가 최대 3회 출제에 "
                "되돌리는 표준 문항 제작 정책입니다."
            ),
            "created_at": "2026-09-19T00:00:00Z",
        }
    )
    standard_path.write_text(
        yaml.safe_dump(standard, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    instruction_replacements = {
        "authoring.md": (
            """- If the reviewed Brief is schema `4.0`, make the canonical draft material profile equal both
  `material_requirement.form` and `task_type`. The ordered `preferred_material_profiles` tuple is
  only the allowed planning set: the selected form must be a member, but its first element has no
  special authority and may differ from the selected form. If the reviewed Brief is the historical
  schema `3.0` and has no `material_requirement`, retain its historical rule that `task_type` equals
  `preferred_material_profiles[0]`. Classification is exact: non-null `inquiry` is `INQUIRY`;""",
            AUTHORING_V4_RULE,
        ),
        "review.md": (
            """- for a reviewed Brief at schema `4.0`, the classified draft material profile equals both
  `material_requirement.form` and `task_type`; `preferred_material_profiles` is only the ordered
  allowed set, so the selected form must be a member but need not equal its first element. For the
  historical Brief schema `3.0` without `material_requirement`, retain the historical
  `task_type == preferred_material_profiles[0]` rule. Use the same DATA-labeled-block and""",
            REVIEW_V4_RULE,
        ),
    }
    for name, suffix in (("authoring.md", AUTHORING_SUFFIX), ("review.md", REVIEW_SUFFIX)):
        path = standard_target / "instructions" / name
        original, replacement = instruction_replacements[name]
        source = path.read_text(encoding="utf-8")
        if original not in source:
            raise ValueError(f"expected standalone material rule is absent: {name}")
        path.write_text(source.replace(original, replacement).rstrip() + suffix, encoding="utf-8")

    old_revision_ids = yaml.safe_load(
        (KNOWLEDGE_SOURCE / "bootstrap.yaml").read_text(encoding="utf-8")
    )["base_instruction_bundle_revision_ids"]
    old_member_hashes = yaml.safe_load(
        (KNOWLEDGE_SOURCE / "bootstrap.yaml").read_text(encoding="utf-8")
    )["base_instruction_member_sha256s"]
    shutil.copytree(KNOWLEDGE_SOURCE, knowledge_target)
    knowledge_path = knowledge_target / "bootstrap.yaml"
    knowledge = yaml.safe_load(knowledge_path.read_text(encoding="utf-8"))
    new_revision_ids = {
        role: _stable_id("instrrev_", f"standard-item:{role}:v16")
        for role in ("authoring", "image", "review", "item_management")
    }
    new_member_hashes = {
        "platform": _sha256(standard_target / "instructions/platform.md"),
        "authoring": _sha256(standard_target / "instructions/authoring.md"),
        "image": _sha256(standard_target / "instructions/image.md"),
        "review": _sha256(standard_target / "instructions/review.md"),
        "item_management": _sha256(standard_target / "instructions/item-management.md"),
    }
    knowledge.update(
        {
            "schema_version": "knowledge-item-control-bootstrap/13.0",
            "display_name": "Graph 풀이보고서 기반 통합과학 제한 재작업",
            "description": (
                "Graph 독립 검토와 오케스트레이터 중재 최대 3회 출제 재작업을 결속하는 "
                "통합과학 정책입니다."
            ),
            "created_at": "2026-09-19T00:05:00Z",
            "base_instruction_bundle_revision_ids": new_revision_ids,
            "base_instruction_member_sha256s": new_member_hashes,
        }
    )
    knowledge_path.write_text(
        yaml.safe_dump(knowledge, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    _write_json_pair(
        "standard-control-bootstrap-v15.schema.json",
        "standard-control-bootstrap-v16.schema.json",
        {
            "standard-control-bootstrap/15.0": "standard-control-bootstrap/16.0",
            "V15": "V16",
        },
        canonical_root=canonical_root,
        packaged_root=packaged_root,
    )
    schema_replacements = {
        "knowledge-item-control-bootstrap/12.0": "knowledge-item-control-bootstrap/13.0",
        "V12": "V13",
    }
    schema_replacements.update(
        {
            old: new
            for old, new in zip(old_revision_ids.values(), new_revision_ids.values(), strict=True)
        }
    )
    schema_replacements.update(
        {
            old.removeprefix("sha256:"): new.removeprefix("sha256:")
            for old, new in zip(old_member_hashes.values(), new_member_hashes.values(), strict=True)
        }
    )
    _write_json_pair(
        "knowledge-item-control-bootstrap-v12.schema.json",
        "knowledge-item-control-bootstrap-v13.schema.json",
        schema_replacements,
        canonical_root=canonical_root,
        packaged_root=packaged_root,
    )


def main() -> None:
    canonical_root = ROOT / "schemas/workflow/control-plane"
    packaged_root = ROOT / "packages/workflow/eom_workflow/resources/control-plane"
    targets = (
        STANDARD_TARGET,
        KNOWLEDGE_TARGET,
        canonical_root / "standard-control-bootstrap-v16.schema.json",
        canonical_root / "knowledge-item-control-bootstrap-v13.schema.json",
        packaged_root / "standard-control-bootstrap-v16.schema.json",
        packaged_root / "knowledge-item-control-bootstrap-v13.schema.json",
    )
    if not any(path.exists() for path in targets):
        _generate(
            standard_target=STANDARD_TARGET,
            knowledge_target=KNOWLEDGE_TARGET,
            canonical_root=canonical_root,
            packaged_root=packaged_root,
        )
        return
    if not all(path.exists() for path in targets):
        raise FileExistsError("bounded-rework control successor is only partially materialized")

    with tempfile.TemporaryDirectory(prefix="eom-bounded-rework-control-") as temp_dir:
        temporary = Path(temp_dir)
        generated_canonical = temporary / "canonical"
        generated_packaged = temporary / "packaged"
        generated_canonical.mkdir()
        generated_packaged.mkdir()
        generated_standard = temporary / "standard"
        generated_knowledge = temporary / "knowledge"
        _generate(
            standard_target=generated_standard,
            knowledge_target=generated_knowledge,
            canonical_root=generated_canonical,
            packaged_root=generated_packaged,
        )
        comparisons = (
            (_tree_bytes(generated_standard), _tree_bytes(STANDARD_TARGET), "standard v16"),
            (_tree_bytes(generated_knowledge), _tree_bytes(KNOWLEDGE_TARGET), "knowledge v13"),
        )
        for expected_tree, actual_tree, label in comparisons:
            if actual_tree != expected_tree:
                raise ValueError(f"generated {label} successor has drifted")
        for name in (
            "standard-control-bootstrap-v16.schema.json",
            "knowledge-item-control-bootstrap-v13.schema.json",
        ):
            expected_bytes = (generated_canonical / name).read_bytes()
            if (canonical_root / name).read_bytes() != expected_bytes:
                raise ValueError(f"generated canonical schema has drifted: {name}")
            if (packaged_root / name).read_bytes() != expected_bytes:
                raise ValueError(f"generated packaged schema has drifted: {name}")


if __name__ == "__main__":
    main()
