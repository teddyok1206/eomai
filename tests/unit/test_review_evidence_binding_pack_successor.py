from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml
from eom_catalog_service.content_pack_files import compile_pack
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.evidence_usage_validation import (
    _ALLOWED_EVIDENCE_USES_BY_REVIEW_PURPOSE,
    EvidenceUsageValidationError,
    _validate_independent_review_report,
)
from eom_workflow.models import ContentTeamReviewRoleResultV12, WorkflowRequest
from pydantic import ValidationError

from scripts.workflow.generate_review_evidence_binding_pack_v12016 import (
    REVIEW_RULE,
    generate_pack,
    tree_bytes,
)
from tests.unit.test_content_team_v3_protocol import _content_v3
from tests.unit.test_execution_materializer import _knowledge_fixture
from tests.unit.test_graph_review_v11_protocol import _materials, _v12_review_document

ROOT = Path(__file__).resolve().parents[2]
PREDECESSOR = ROOT / "content/packs/generated-knowledge-item/1.20.15"
SUCCESSOR = ROOT / "content/packs/generated-knowledge-item/1.20.16"
UNUSED_EVIDENCE_ID = "evidenceitem_" + "4" * 32


def _refresh_fixture_materials(fixture: dict[str, Any]) -> None:
    """Keep the synthetic context, manifest and hashes consistent before semantic checks."""

    manifest = fixture["manifest"]
    use = manifest["entries"][0]["use"]
    fixture["context_payload"] = fixture["context_payload"].replace(
        b"use=REFERENCE_PATTERN", f"use={use}".encode()
    )
    manifest["materials"]["context_markdown"]["sha256"] = sha256_bytes(fixture["context_payload"])
    manifest["manifest_sha256"] = content_sha256(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    fixture["manifest_payload"] = canonical_json_bytes(manifest)


def test_review_evidence_pack_is_minimal_immutable_compatible_successor() -> None:
    predecessor = tree_bytes(PREDECESSOR)
    successor = tree_bytes(SUCCESSOR)
    assert predecessor.keys() == successor.keys()
    assert {path for path in predecessor if predecessor[path] != successor[path]} == {
        Path("pack.yaml"),
        Path("profiles/generated-knowledge-review.yaml"),
        Path("prompt-templates/review.md"),
    }
    pack = compile_pack(SUCCESSOR)
    assert pack.manifest.pack.version == "1.20.16"
    assert pack.manifest.compatibility == compile_pack(PREDECESSOR).manifest.compatibility
    request = WorkflowRequest.model_validate_json(
        (SUCCESSOR / "fixtures/smoke-request.json").read_text(encoding="utf-8")
    )
    WorkflowCatalogService._require_item_brief_release(
        "generated-knowledge-item", "1.20.16", request
    )
    profile = yaml.safe_load(
        (SUCCESSOR / "profiles/generated-knowledge-review.yaml").read_text(encoding="utf-8")
    )
    assert profile["profile"]["version"] == "12.2.2"
    assert profile["output_schema_ref"] == "review-result@12.0"


def test_review_evidence_generator_is_reproducible_and_never_replaces_source_or_target(
    tmp_path: Path,
) -> None:
    before = tree_bytes(PREDECESSOR)
    target = tmp_path / "candidate"
    generate_pack(target)
    assert tree_bytes(target) == tree_bytes(SUCCESSOR)
    assert tree_bytes(PREDECESSOR) == before
    with pytest.raises(FileExistsError):
        generate_pack(target)
    assert tree_bytes(target) == tree_bytes(SUCCESSOR)


def test_review_prompt_states_exact_union_without_fabricating_or_relaxing_evidence() -> None:
    prompt = (SUCCESSOR / "prompt-templates/review.md").read_text(encoding="utf-8")
    assert (
        prompt
        == (PREDECESSOR / "prompt-templates/review.md").read_text(encoding="utf-8").rstrip()
        + REVIEW_RULE
    )
    for required in (
        "answer_review.claims[*].evidence_ids",
        "choice_diagnostics[*].evidence_ids",
        "statement_diagnostics[*].evidence_ids",
        "explanation_assessment.evidence_ids",
        "curriculum_assessment.evidence_ids",
        "originality_assessment.evidence_ids",
        "visual_assessment.evidence_ids",
        "require R == U",
        "verification_targets[*].selected_evidence_ids is a subset of R",
        "candidate_findings[*].evidence_ids is a subset of R",
        "ID를 임의로 붙이거나",
        "새 evidence ID·anchor·receipt를 만들거나",
        "knowledge_source_mode=graph_grounded",
        "general_model_knowledge",
        "answer_bearing=true",
        "manifest/5.0",
    ):
        assert required in prompt


def test_review_prompt_manifest_use_table_matches_authoritative_validator() -> None:
    prompt = (SUCCESSOR / "prompt-templates/review.md").read_text(encoding="utf-8")
    rows = {
        purpose: frozenset(uses.strip().split(", "))
        for line in prompt.splitlines()
        if line.startswith("| ")
        for purpose, uses in [line.strip("| ").split(" | ")]
        if purpose in _ALLOWED_EVIDENCE_USES_BY_REVIEW_PURPOSE
    }
    assert rows == _ALLOWED_EVIDENCE_USES_BY_REVIEW_PURPOSE


@pytest.mark.parametrize("missing", [False, True], ids=["unused_reference", "missing_reference"])
def test_review_exact_union_rejects_both_directions_of_actual_incident(missing: bool) -> None:
    document = _v12_review_document({})
    report = document["output"]["independent_review_report"]
    if missing:
        report["evidence_references"] = []
    else:
        unused = deepcopy(report["evidence_references"][0])
        unused["evidence_id"] = UNUSED_EVIDENCE_ID
        report["evidence_references"].append(unused)
    with pytest.raises(ValidationError, match="references must exactly cover used evidence IDs"):
        ContentTeamReviewRoleResultV12.model_validate(document)


@pytest.mark.parametrize("candidate", [False, True], ids=["target", "candidate"])
def test_review_plan_cannot_introduce_an_id_outside_actual_judgment_references(
    candidate: bool,
) -> None:
    document = _v12_review_document({}, candidate_disposition="DEMOTED" if candidate else None)
    report = document["output"]["independent_review_report"]
    if candidate:
        report["candidate_findings"][0]["evidence_ids"] = [UNUSED_EVIDENCE_ID]
    else:
        report["verification_targets"][0]["selected_evidence_ids"] = [UNUSED_EVIDENCE_ID]
    with pytest.raises(ValidationError, match="outside the review references"):
        ContentTeamReviewRoleResultV12.model_validate(document)


@pytest.mark.parametrize("use", ["GROUNDING", "AVOID_COPY"])
def test_review_manifest_purpose_mismatch_is_rejected_without_relaxing_commit_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, use: str
) -> None:
    fixture = _knowledge_fixture(
        tmp_path,
        monkeypatch,
        manifest_schema_version="5.0",
        workflow_definition_version="1.16.0",
    )
    document = _v12_review_document(fixture)
    result = ContentTeamReviewRoleResultV12.model_validate(document)
    fixture["manifest"]["entries"][0]["use"] = use
    _refresh_fixture_materials(fixture)
    with pytest.raises(EvidenceUsageValidationError) as captured:
        _validate_independent_review_report(
            _materials(fixture), result, _content_v3().model_dump(mode="json")
        )
    assert captured.value.code == "EVIDENCE_REVIEW_PURPOSE_INVALID"


def test_review_answer_bearing_reference_cannot_support_positive_judgments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _knowledge_fixture(
        tmp_path,
        monkeypatch,
        manifest_schema_version="5.0",
        workflow_definition_version="1.16.0",
    )
    result = ContentTeamReviewRoleResultV12.model_validate(_v12_review_document(fixture))
    fixture["manifest"]["entries"][0]["answer_bearing"] = True
    fixture["manifest"]["entries"][0]["use"] = "AVOID_COPY"
    _refresh_fixture_materials(fixture)
    with pytest.raises(EvidenceUsageValidationError) as captured:
        _validate_independent_review_report(
            _materials(fixture), result, _content_v3().model_dump(mode="json")
        )
    assert captured.value.code == "EVIDENCE_REVIEW_PURPOSE_INVALID"


def test_valid_referenced_scientific_scope_and_originality_judgments_still_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _knowledge_fixture(
        tmp_path,
        monkeypatch,
        manifest_schema_version="5.0",
        workflow_definition_version="1.16.0",
    )
    result = ContentTeamReviewRoleResultV12.model_validate(_v12_review_document(fixture))
    _validate_independent_review_report(
        _materials(fixture), result, _content_v3().model_dump(mode="json")
    )
