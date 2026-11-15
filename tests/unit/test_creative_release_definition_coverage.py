"""The installed-wheel gate stages and checks each admitted creative family."""

import ast
import os
import textwrap
from pathlib import Path

from eom_workflow import AgentStep
from eom_workflow.compiler import compile_definition
from eom_workflow.creative_learning_profile import creative_learning_profile
from eom_workflow.definition_execution_protocol import definition_execution_protocol
from eom_workflow.material_learning_request import material_learning_contract_for_definition

ROOT = Path(__file__).resolve().parents[2]


def test_release_simulation_stages_and_loads_each_exact_creative_successor() -> None:
    script = (ROOT / "scripts/api/deploy_release.sh").read_text()
    for version in ("1", "2", "3"):
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
    assert 'compile_definition(creative_office_definition, {"support"})' in source
    assert "WORKFLOW_ADMISSION_BY_IDENTITY.items()" in source


def test_uploaded_material_is_in_the_actual_installed_definition_gate() -> None:
    script = (ROOT / "scripts/api/deploy_release.sh").read_text()
    source = script.split("    check = r'''", 1)[1].split("'''", 1)[0]
    ast.parse(source)
    for name, version in (
        ("material_definition", "1.0.0"),
        ("material_coverage_definition", "2.0.0"),
        ("material_exact_score_definition", "3.0.0"),
    ):
        filename = f"material-learning.v{version[0]}.yaml"
        profile = material_learning_contract_for_definition(version)
        assert script.count(f'"{filename}"') >= 2
        assert f'compile_definition({name}, {{"support"}})' in source
        assert f'load_role_input_schema("support", "{profile.role_protocol}")' in source
        assert f'load_codex_result_schema("{profile.result_schema}")' in source
    assert 'raise SystemExit("material learning workflow profile mismatch")' in source


def test_actual_release_copy_block_stages_all_material_definitions_without_activation(
    monkeypatch, tmp_path
):
    script = (ROOT / "scripts/api/deploy_release.sh").read_text()
    start = script.index('    for name in (\n        "external-item-learning.v1.yaml"')
    end = script.index("    editorial_definition = ", start)
    copy_block = ast.parse(textwrap.dedent(script[start:end]))
    monkeypatch.setenv("REPOSITORY_ROOT", str(ROOT))
    # Execute only this existing local copy boundary, not deployment/service/control code.
    exec(
        compile(copy_block, "release-definition-copy", "exec"),
        {"root": tmp_path, "Path": Path, "os": os},
    )
    for version in ("1.0.0", "2.0.0", "3.0.0"):
        filename = f"material-learning.v{version[0]}.yaml"
        target = tmp_path / filename
        assert target.read_bytes() == (ROOT / "config/workflows" / filename).read_bytes()
        definition = compile_definition(target, {"support"}).definition
        profile = material_learning_contract_for_definition(version)
        agent = next(step for step in definition.steps if isinstance(step, AgentStep))
        assert (definition.definition_key, definition.definition_version) == (
            "material-learning",
            version,
        )
        assert agent.result_schema == profile.result_schema
        assert definition_execution_protocol(definition) == profile.role_protocol
