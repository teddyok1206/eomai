from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _artifact(seed: str) -> dict[str, str]:
    return {
        "artifact_id": "artifact_" + seed * 32,
        "artifact_revision_id": "rev_" + seed * 32,
        "sha256": "sha256:" + seed * 64,
        "schema_ref": "eom.test/1.0",
        "media_type": "application/json",
        "logical_name": "manifest.json",
    }


def _bundle(kind: str, seed: str) -> dict[str, object]:
    return {
        "bundle_id": f"{kind}bundle_" + seed * 32,
        "bundle_revision_id": f"{kind}rev_" + seed * 32,
        "manifest_artifact": _artifact(seed),
        "manifest_sha256": "sha256:" + seed * 64,
    }


def _preset() -> dict[str, object]:
    return {
        "preset_id": "execpreset_" + "1" * 32,
        "preset_key": "standard-item",
        "current_revision_id": "execpresetrev_" + "2" * 32,
        "state": "ACTIVE",
        "revisions": [
            {
                "schema_version": "execution-preset-revision/1.0",
                "preset_revision_id": "execpresetrev_" + "2" * 32,
                "revision_number": 4,
                "display_name": "표준 문항 제작",
                "description": "검증된 표준 실행 정책",
                "capacity_policy_revision_id": "capacityrev_" + "3" * 32,
                "general_knowledge_policy": "ALLOW_WITH_PROVENANCE",
                "compatible_workflow_protocols": ["workflow-role/1.3.0"],
                "content_sha256": "sha256:" + "4" * 64,
                "retrieval_policy": None,
                "role_policies": [
                    {
                        "role": "authoring",
                        "model_candidates": [
                            {"model": "gpt-5.6-terra", "reasoning_effort": "xhigh"},
                            {"model": "gpt-5.6-sol", "reasoning_effort": "high"},
                        ],
                        "instruction_bundle": _bundle("instr", "5"),
                        "reference_bundle": _bundle("ref", "6"),
                        "worker_pool_key": "item-workers",
                        "timeout_seconds": 1800,
                        "sandbox": "read-only",
                        "network": "disabled",
                        "evidence_access": None,
                    }
                ],
                "evaluations": [],
                "server_only_value": "must-not-be-copied",
            }
        ],
    }


def test_guided_editor_preserves_pointers_and_requires_a_new_review(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not available for the browser helper regression")
    module = tmp_path / "execution-preset-editor.mjs"
    module.write_bytes(
        (ROOT / "apps/web_gui/eom_web_gui/static/execution-preset-editor.js").read_bytes()
    )
    script = f"""
import {{
  candidateFromOptionValue,
  candidateOptionValue,
  guidedPresetBases,
  reviewedPresetDraft,
}} from {json.dumps(module.as_uri())};
let input = "";
for await (const chunk of process.stdin) input += chunk;
const preset = JSON.parse(input);
const bases = guidedPresetBases([preset]);
if (bases.length !== 1) throw new Error("EDITABLE_BASE_MISSING");
const base = bases[0];
if (base.preset_revision_id !== preset.current_revision_id) throw new Error("CURRENT_NOT_PINNED");
if ("server_only_value" in base.draft) throw new Error("UNREVIEWED_FIELD_COPIED");
if (base.draft.role_policies[0].instruction_bundle.bundle_revision_id !==
    "instrrev_" + "5".repeat(32)) {{
  throw new Error("INSTRUCTION_POINTER_NOT_PRESERVED");
}}
const encoded = candidateOptionValue("gpt-5.6-sol", "xhigh");
const decoded = candidateFromOptionValue(encoded);
if (decoded.model !== "gpt-5.6-sol" || decoded.reasoning_effort !== "xhigh") {{
  throw new Error("CANDIDATE_OPTION_ROUNDTRIP_FAILED");
}}
const draft = reviewedPresetDraft(base.draft, {{
  display_name: "표준 문항 제작 · 고정",
  description: base.draft.description,
  general_knowledge_policy: base.draft.general_knowledge_policy,
  role_policies: [{{
    role: "authoring",
    model_candidates: [decoded, {{model: "gpt-5.6-sol", reasoning_effort: "high"}}],
    timeout_seconds: 2400,
  }}],
}});
if (draft.role_policies[0].timeout_seconds !== 2400) throw new Error("TIMEOUT_NOT_APPLIED");
if (draft.role_policies[0].reference_bundle.bundle_revision_id !== "refrev_" + "6".repeat(32)) {{
  throw new Error("REFERENCE_POINTER_NOT_PRESERVED");
}}
let unchangedFailed = false;
try {{ reviewedPresetDraft(base.draft, {{
  display_name: base.draft.display_name,
  description: base.draft.description,
  general_knowledge_policy: base.draft.general_knowledge_policy,
  role_policies: base.draft.role_policies,
}}); }} catch (error) {{ unchangedFailed = error.message === "PRESET_DRAFT_HAS_NO_CHANGES"; }}
if (!unchangedFailed) throw new Error("UNCHANGED_DRAFT_NOT_REJECTED");
let duplicateFailed = false;
try {{ reviewedPresetDraft(base.draft, {{
  display_name: "변경",
  description: base.draft.description,
  general_knowledge_policy: base.draft.general_knowledge_policy,
  role_policies: [{{
    role: "authoring",
    model_candidates: [decoded, decoded],
    timeout_seconds: 2400,
  }}],
}}); }} catch (error) {{
  duplicateFailed = error.message === "PRESET_MODEL_CANDIDATES_DUPLICATED";
}}
if (!duplicateFailed) throw new Error("DUPLICATE_CANDIDATE_NOT_REJECTED");
const v2 = structuredClone(preset);
v2.revisions[0].schema_version = "execution-preset-revision/2.0";
v2.revisions[0].retrieval_policy = {{access_policy_revision_id: "accessrev_ignored"}};
if (guidedPresetBases([v2]).length !== 0) throw new Error("V2_PRESET_OFFERED_FOR_V1_EDITOR");
"""
    completed = subprocess.run(
        [node, "--input-type=module", "--eval", script],
        check=False,
        input=json.dumps(_preset()),
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
