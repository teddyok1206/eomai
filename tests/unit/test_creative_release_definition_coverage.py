"""The installed-wheel gate stages and checks both admitted creative families."""

import ast
from pathlib import Path

from eom_workflow import AgentStep
from eom_workflow.compiler import compile_definition
from eom_workflow.creative_learning_profile import creative_learning_profile

ROOT = Path(__file__).resolve().parents[2]


def test_release_simulation_stages_and_loads_each_exact_creative_successor() -> None:
    script = (ROOT / "scripts/api/deploy_release.sh").read_text()
    for version in ("1", "2"):
        name = f"external-item-learning.v{version}.yaml"
        assert script.count(f'"{name}"') >= 2
        profile = creative_learning_profile(f"{version}.0.0")
        compiled = compile_definition(ROOT / "config/workflows" / name, {"support"})
        agent = next(step for step in compiled.definition.steps if isinstance(step, AgentStep))
        assert agent.result_schema == profile.result_schema
        assert f'load_role_input_schema("support", "{profile.role_protocol}")' in script
        assert f'load_codex_result_schema("{profile.result_schema}")' in script
    # Check the actual isolated child program, not only file-name substrings.
    source = script.split("    check = r'''", 1)[1].split("'''", 1)[0]
    ast.parse(source)
    assert 'compile_definition(creative_definition, {"support"})' in source
    assert 'compile_definition(creative_source_definition, {"support"})' in source
    assert "WORKFLOW_ADMISSION_BY_IDENTITY.items()" in source
