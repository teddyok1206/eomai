from __future__ import annotations

import hashlib
from pathlib import Path

from eom_catalog_service.content_pack_files import compile_pack
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_orchestrator.control_bootstrap import (
    STANDARD_BOOTSTRAP_INSTRUCTION_REVISIONS,
    load_standard_bootstrap_manifest,
)
from eom_orchestrator.knowledge_item_bootstrap import (
    PINNED_STANDARD_INSTRUCTION_REVISION_BY_KNOWLEDGE_SCHEMA,
    load_knowledge_item_bootstrap_manifest,
)
from eom_workflow import WORKFLOW_ADMISSION_BY_IDENTITY, compile_definition
from eom_workflow.models import WorkflowRequest

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "content/packs/generated-knowledge-item/1.19.0"
WORKFLOW = ROOT / "config/workflows/generic-item-development.v1.13.yaml"
STANDARD = ROOT / "config/control-plane/standard-item-v17"
KNOWLEDGE = ROOT / "config/control-plane/knowledge-grounded-item-v14"


def test_verification_review_pack_workflow_and_admission_form_one_family() -> None:
    pack = compile_pack(PACK)
    workflow = compile_definition(
        WORKFLOW,
        {"authoring", "image", "review", "item_management"},
    ).definition

    assert pack.manifest.pack.version == "1.19.0"
    assert pack.source_tree_sha256 == (
        "sha256:5ef75c25b9fc6254ce836b007df3ef49cce8c43c609a83f089b6390679228880"
    )
    assert pack.manifest.compatibility.protocol.minimum == "1.24.0"
    assert pack.manifest.compatibility.protocol.maximum_exclusive == "1.25.0"
    assert workflow.definition_version == "1.13.0"
    assert workflow.limits.max_step_attempts == 10
    assert workflow.limits.max_rework_cycles == 3
    assert workflow.automatic_review_rework is not None
    assert (
        WORKFLOW_ADMISSION_BY_IDENTITY[("generic-item-development", "1.13.0")].role_protocol_version
        == "workflow-role/1.24.0"
    )


def test_review_prompt_requires_graph_plan_visual_first_and_bounded_escalation() -> None:
    review_path = PACK / "prompt-templates/review.md"
    review = review_path.read_text(encoding="utf-8")

    for required in (
        "REVIEW_ESCALATION_DIRECTIVE_JSON",
        "SOURCE_PRIMARY_REVIEW_RESULT_JSON",
        "verification_targets",
        "VISUAL_FIRST",
        "CONFIRMED/DEMOTED/UNCERTAIN",
        "고정",
        "Evidence ID",
        "일반지식이나 최신 Graph로 보완하지 말고",
        "한 번뿐인 강화 검토",
    ):
        assert required in review
    assert hashlib.sha256(review_path.read_bytes()).hexdigest() == (
        "1dbcccb9d809441dfa742ce2d77b6dcf52918d7e67f8d4ea0a703164d7a97549"
    )


def test_catalog_admits_v119_material_request_without_parallel_item_contract() -> None:
    request = WorkflowRequest.model_validate_json(
        (PACK / "fixtures/smoke-request.json").read_text(encoding="utf-8")
    )

    WorkflowCatalogService._require_item_brief_release(
        "generated-knowledge-item",
        "1.19.0",
        request,
    )


def test_control_successors_pin_primary_and_stronger_review_candidates() -> None:
    standard = load_standard_bootstrap_manifest(STANDARD)
    knowledge = load_knowledge_item_bootstrap_manifest(KNOWLEDGE)

    assert standard.schema_version == "standard-control-bootstrap/17.0"
    assert standard.compatible_workflow_protocols == ("workflow-role/1.24.0",)
    assert (standard.model, standard.reasoning_effort) == ("gpt-5.6-terra", "high")
    assert (
        standard.review_escalation_model,
        standard.review_escalation_reasoning_effort,
    ) == ("gpt-5.6-terra", "xhigh")
    assert STANDARD_BOOTSTRAP_INSTRUCTION_REVISIONS[standard.schema_version] == 17

    assert knowledge.schema_version == "knowledge-item-control-bootstrap/14.0"
    assert knowledge.compatible_workflow_protocols == ("workflow-role/1.24.0",)
    assert PINNED_STANDARD_INSTRUCTION_REVISION_BY_KNOWLEDGE_SCHEMA[knowledge.schema_version] == 17
    assert knowledge.base_instruction_member_sha256s == {
        "platform": "sha256:5a3cfab6dc1c195ebc93cb13c7549cd31ea30f6229a4b134bed818d9dd69271b",
        "authoring": "sha256:f6019d8e13c8887bce76adbf183eaa5aa13bf014a749fcddfb97fa349dc3be0b",
        "image": "sha256:18ad7994b5d84bb395be1dddc40f3fde6d6637419926f1a7a59c8e8e6ec527e1",
        "review": "sha256:616b46ceb031c3044242597422c93e5538ab3caebaa16ea5d4650a01725f2898",
        "item_management": (
            "sha256:9482b7380920b1f0ffcdbca342e66a1c3797962beaa4d37d8d54eadcc30bdcd8"
        ),
    }
