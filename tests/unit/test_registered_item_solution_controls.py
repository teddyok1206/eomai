"""Versioned worker instructions reuse the past-exam report, not its source identity."""

import ast
from pathlib import Path

import pytest
import yaml
from eom_orchestrator.control_bootstrap import (
    KnowledgeAnalysisBootstrapManifest,
    load_knowledge_analysis_bootstrap_manifest,
)
from eom_orchestrator.control_service import ControlPlaneError
from eom_workflow import AgentStep, compile_definition, workflow_admission
from eom_workflow.control_schemas import load_control_schema, validate_control_contract
from eom_workflow.definition_execution_protocol import definition_execution_protocol
from eom_workflow.schemas import load_codex_result_schema, load_role_input_schema
from jsonschema import Draft202012Validator
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config/control-plane/knowledge-analysis-v21"
OLD = ROOT / "config/control-plane/knowledge-analysis-v20"
SCHEMA = "knowledge-analysis-control-bootstrap-v21"


def test_registered_control_schema_and_model_preserve_the_released_model_and_prior_protocols():
    value = yaml.safe_load((CONFIG / "bootstrap.yaml").read_text())
    Draft202012Validator.check_schema(load_control_schema(SCHEMA))
    validate_control_contract(SCHEMA, value)
    current = load_knowledge_analysis_bootstrap_manifest(CONFIG)
    previous = load_knowledge_analysis_bootstrap_manifest(OLD)
    assert (current.model, current.reasoning_effort) == (previous.model, previous.reasoning_effort)
    assert current.compatible_workflow_protocols == (
        *previous.compatible_workflow_protocols,
        "workflow-role/1.35.0",
    )
    assert current.slot_key == previous.slot_key == "slot05"
    assert current.worker_pool_key == previous.worker_pool_key == "support"
    assert current.timeout_seconds == previous.timeout_seconds == 7200
    canonical = (
        ROOT / "schemas/workflow/control-plane/knowledge-analysis-control-bootstrap-v21.schema.json"
    )
    packaged = ROOT / "packages/workflow/eom_workflow/resources/control-plane" / canonical.name
    assert canonical.read_bytes() == packaged.read_bytes()


@pytest.mark.parametrize(
    "field,value",
    [
        ("timeout_seconds", "7200"),
        ("timeout_seconds", True),
        ("timeout_seconds", 7201),
        ("slot_key", "slot01"),
        ("worker_pool_key", "authoring"),
        ("model", 123),
        ("compatible_workflow_protocols", ["workflow-role/1.35.0"]),
        ("platform_instruction_path", "../platform.md"),
    ],
)
def test_registered_control_loader_validates_raw_schema_before_coercion_or_publication(
    tmp_path, field, value
):
    document = yaml.safe_load((CONFIG / "bootstrap.yaml").read_text())
    document[field] = value
    (tmp_path / "bootstrap.yaml").write_text(yaml.safe_dump(document))
    with pytest.raises(ControlPlaneError) as exc:
        load_knowledge_analysis_bootstrap_manifest(tmp_path)
    assert exc.value.code == "CONTROL_BOOTSTRAP_INVALID"


def test_registered_protocol_is_not_backported_into_released_v20_meaning():
    old = load_knowledge_analysis_bootstrap_manifest(OLD).model_dump(mode="json")
    old["compatible_workflow_protocols"].append("workflow-role/1.35.0")
    with pytest.raises(ValidationError):
        KnowledgeAnalysisBootstrapManifest.model_validate(old)


def test_registered_worker_instructions_keep_the_complete_past_exam_contract_and_hash_rules():
    old = (OLD / "instructions/knowledge-analysis.md").read_text()
    current = (CONFIG / "instructions/knowledge-analysis.md").read_text()
    historical = old[old.index("## Existing analysis task") :]
    assert current.endswith(historical)
    assert (CONFIG / "instructions/platform.md").read_bytes() == (
        OLD / "instructions/platform.md"
    ).read_bytes()
    for required in (
        "RFC6901",
        "canonical JSON value",
        "excerpt_sha256",
        "knode_concept_",
        "knode_item_element_",
        "knode_assessment_pattern_",
        "answer",
        "explanations",
        "knowledge-analysis-request/11.0",
        "seven original normalized members",
        "not a request for hidden chain-of-thought",
        "not proof that pixels were inspected",
        "Do not optimize the text for a source category",
        "unresolved issues",
    ):
        assert required in current


def test_registered_workflow_compiles_with_exact_input_and_result_protocol():
    compiled = compile_definition(
        ROOT / "config/workflows/knowledge-analysis.v11.yaml", {"support"}
    )
    assert compiled.definition.definition_version == "11.0.0"
    assert definition_execution_protocol(compiled.definition) == "workflow-role/1.35.0"
    admission = workflow_admission("knowledge-analysis", "11.0.0")
    assert admission is not None and admission.role_protocol_version == "workflow-role/1.35.0"
    agents = [step for step in compiled.definition.steps if isinstance(step, AgentStep)]
    assert len(agents) == 1 and agents[0].result_schema == "knowledge-analysis-proposal-result@11.0"
    load_role_input_schema("support", admission.role_protocol_version)
    load_codex_result_schema(agents[0].result_schema)


def test_isolated_release_simulation_stages_and_admits_registered_definition11():
    script = (ROOT / "scripts/api/deploy_release.sh").read_text()
    source = script.split("    check = r'''", 1)[1].split("'''", 1)[0]
    ast.parse(source)
    assert 'compile_definition(Path(analysis_v11), {"support"})' in source
    assert 'load_role_input_schema("support", "workflow-role/1.35.0")' in source
    assert 'load_codex_result_schema("knowledge-analysis-proposal-result@11.0")' in source
    # Argument unpack and both compiled-definition inventories must cover v11.
    assert "analysis_v10, analysis_v11, legacy_definition" in source
    assert 'for version in ("1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11"):' in script
