"""Compiler/protocol continuity without importing, admitting or launching a runtime."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, cast
from warnings import catch_warnings, simplefilter

import pytest
import yaml
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.admission import workflow_definition_is_admitted
from eom_workflow.compiler import (
    WorkflowDefinitionError,
    compile_definition,
    compile_definition_data,
)
from eom_workflow.definition_execution_protocol import (
    DefinitionExecutionProtocolError,
    definition_execution_protocol,
)
from eom_workflow.local_embedding_workflow import (
    LOCAL_EMBEDDING_EXECUTION_PROTOCOL,
    LocalEmbeddingStep,
    LocalEmbeddingWorkflowDefinition,
)
from eom_workflow.models import AgentStep, TerminalStep, WorkflowDefinition, WorkflowLimits

ROLES = {"authoring", "image", "review", "item_management", "support"}
CONFIG = Path("config/workflows")
_PRECHANGE_HASHES = {
    "generic-item-development.v1.yaml": (
        "sha256:036b978250e09f8288f26d83780db8997db6a4337818ec92bf96a1d36b43ede0"
    ),
    "generic-item-development.v1.16.yaml": (
        "sha256:0bc5ad197679302f21035b551ea2ce93a357a46f43dd3b0815cc64a94fcb20ed"
    ),
    "customer-support.v1.yaml": (
        "sha256:fdfefa8019cc3075b7592f0b83704c3cb02f11e763ec54562d79a6678cf1258d"
    ),
    "knowledge-analysis.v10.yaml": (
        "sha256:97afd30531d04ecdcc9297523561df963301e80dcb47cc247f416f43d0714556"
    ),
    "item-inference-transfer-comparison.v1.yaml": (
        "sha256:74a266386a5f80832ec2ec183acc0289a33b994aa9ea33b6605c61dd930a987f"
    ),
    "item-inference-transfer-comparison.v1_1.yaml": (
        "sha256:a9c7e38151b7f0a0004069d23e60f8601c9717173bb672022ae075566844260e"
    ),
    "pdf-document-review.v1.3.yaml": (
        "sha256:c3cce17eba54f57517724ea1e3f7ffce6fa80c0f6a39da234a8c63a5e6554634"
    ),
    "legacy-item-extraction.v1.yaml": (
        "sha256:03b240e6f880f7699a6a2f9184a422caac781c3d24c7b175795dc73e91cc059b"
    ),
}


def _native() -> dict[str, Any]:
    value = LocalEmbeddingWorkflowDefinition(
        limits=WorkflowLimits(max_rework_cycles=0, max_step_attempts=1),
        steps=(
            LocalEmbeddingStep(),
            TerminalStep(key="complete", type="terminal", terminal_status="COMPLETED"),
        ),
    )
    return value.model_dump(mode="json", exclude_none=True)


def test_native_compiler_preserves_fixed_snapshot_and_requires_no_codex_role() -> None:
    raw = _native()
    compiled = compile_definition_data(raw, "synthetic-native-definition", set())
    assert isinstance(compiled.definition, LocalEmbeddingWorkflowDefinition)
    assert isinstance(compiled.steps_by_key["encode_batch"], LocalEmbeddingStep)
    assert isinstance(compiled.steps_by_key["complete"], TerminalStep)
    assert tuple(compiled.steps_by_key) == ("encode_batch", "complete")
    assert compiled.automatic_review_rework is None
    assert compiled.as_dict() == raw
    assert compiled.canonical_bytes == canonical_json_bytes(raw)
    assert compiled.sha256 == sha256_bytes(compiled.canonical_bytes)
    assert definition_execution_protocol(compiled.definition) == LOCAL_EMBEDDING_EXECUTION_PROTOCOL
    replay = compile_definition_data(compiled.as_dict(), compiled.source_path, set())
    assert replay.canonical_bytes == compiled.canonical_bytes
    assert replay.sha256 == compiled.sha256
    # Compiler support cannot activate repository admission or an installed executor.
    assert not workflow_definition_is_admitted("local-embedding-index", "1.0.0")


@pytest.mark.parametrize(("name", "expected"), tuple(_PRECHANGE_HASHES.items()))
def test_legacy_definition_hashes_are_exactly_the_prechange_values(
    name: str, expected: str
) -> None:
    compiled = compile_definition(CONFIG / name, ROLES)
    assert isinstance(compiled.definition, WorkflowDefinition)
    assert compiled.sha256 == expected
    raw = yaml.safe_load((CONFIG / name).read_text())
    old_model = WorkflowDefinition.model_validate(raw)
    assert compiled.automatic_review_rework is compiled.definition.automatic_review_rework
    assert compiled.canonical_bytes == canonical_json_bytes(
        old_model.model_dump(mode="python", exclude_none=True)
    )
    replay = compile_definition_data(compiled.as_dict(), compiled.source_path, ROLES)
    assert replay.canonical_bytes == compiled.canonical_bytes
    assert replay.sha256 == expected


@pytest.mark.parametrize(
    "name", ("generic-item-development.v1.12.yaml", "generic-item-development.v1.16.yaml")
)
def test_compiled_review_projection_preserves_the_original_policy_and_replay(name: str) -> None:
    compiled = compile_definition(CONFIG / name, ROLES)
    assert isinstance(compiled.definition, WorkflowDefinition)
    policy = compiled.definition.automatic_review_rework
    assert policy is not None
    assert compiled.automatic_review_rework is policy
    assert policy.source_review_step == "review"
    assert policy.target_authoring_step == "authoring"
    replay = compile_definition_data(compiled.as_dict(), compiled.source_path, ROLES)
    assert replay.automatic_review_rework == policy
    assert replay.canonical_bytes == compiled.canonical_bytes
    assert replay.sha256 == compiled.sha256


def test_every_existing_agent_family_uses_the_existing_protocol_mapping() -> None:
    from eom_workflow.schemas import result_schema_protocol

    seen = 0
    for path in sorted(CONFIG.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text())
        if raw.get("schema_version") != "1.0":
            continue
        compiled = compile_definition_data(raw, str(path), ROLES)
        assert isinstance(compiled.definition, WorkflowDefinition)
        original = {
            result_schema_protocol(step.result_schema)
            for step in compiled.definition.steps
            if isinstance(step, AgentStep)
        }
        assert len(original) == 1
        assert definition_execution_protocol(compiled.definition) == next(iter(original))
        seen += 1
    assert seen >= 36


@pytest.mark.parametrize("version", ("1.2", "2.0", 1.1, True, None))
def test_unknown_version_is_not_inferred_or_silently_upgraded(version: object) -> None:
    raw = _native()
    raw["schema_version"] = version
    with pytest.raises(WorkflowDefinitionError, match="schema validation"):
        compile_definition_data(raw, "synthetic-version", ROLES)


def test_agent_definition_cannot_use_the_native_version_or_protocol() -> None:
    raw = yaml.safe_load((CONFIG / "customer-support.v1.yaml").read_text())
    raw["schema_version"] = "1.1"
    with pytest.raises(WorkflowDefinitionError, match="schema validation"):
        compile_definition_data(raw, "synthetic-cross-purpose", ROLES)
    native = _native()
    native["schema_version"] = "1.0"
    with pytest.raises(WorkflowDefinitionError, match="schema validation"):
        compile_definition_data(native, "synthetic-cross-purpose", ROLES)


@pytest.mark.parametrize("field", ("shell", "command", "module", "CALLABLE", "sql", "template"))
def test_native_compiler_retains_the_recursive_unsafe_key_guard(field: str) -> None:
    raw = _native()
    raw["steps"][0][field] = "synthetic-unsafe-value"
    with pytest.raises(WorkflowDefinitionError, match="unsafe workflow field"):
        compile_definition_data(raw, "synthetic-unsafe", set())


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("operation", "RUN_COMMAND"),
        ("worker_role", "support"),
        ("worker_role", "image"),
        ("result_schema", "customer-support-result@1.0"),
        ("on_success", "encode_batch"),
    ),
)
def test_native_compiler_has_no_arbitrary_application_or_agent_fallback(
    field: str, value: str
) -> None:
    raw = _native()
    raw["steps"][0][field] = value
    with pytest.raises(WorkflowDefinitionError, match="schema validation"):
        compile_definition_data(raw, "synthetic-fallback", ROLES)


def test_native_compiler_rejects_reversed_and_extra_steps() -> None:
    raw = _native()
    raw["steps"].reverse()
    with pytest.raises(WorkflowDefinitionError):
        compile_definition_data(raw, "synthetic-order", set())
    raw = _native()
    raw["steps"].append(deepcopy(raw["steps"][1]))
    with pytest.raises(WorkflowDefinitionError):
        compile_definition_data(raw, "synthetic-extra", set())


def test_protocol_helper_revalidates_forged_native_and_old_frozen_values() -> None:
    native = LocalEmbeddingWorkflowDefinition.model_validate(_native())
    bad_step = native.steps[0].model_copy(update={"operation": "RUN_COMMAND"})
    with catch_warnings(record=True) as observed:
        simplefilter("always")
        with pytest.raises(DefinitionExecutionProtocolError):
            definition_execution_protocol(
                native.model_copy(update={"steps": (bad_step, native.steps[1])})
            )
    assert observed == []
    old = compile_definition(CONFIG / "customer-support.v1.yaml", ROLES).definition
    assert isinstance(old, WorkflowDefinition)
    with pytest.raises(DefinitionExecutionProtocolError):
        definition_execution_protocol(old.model_copy(update={"schema_version": "1.1"}))
    with pytest.raises(DefinitionExecutionProtocolError):
        definition_execution_protocol(cast(WorkflowDefinition, object()))


def test_protocol_helper_rejects_missing_and_mixed_old_agent_protocols() -> None:
    old = compile_definition(CONFIG / "customer-support.v1.yaml", ROLES).definition
    assert isinstance(old, WorkflowDefinition)
    no_agents = old.model_copy(
        update={
            "steps": (
                TerminalStep(key="start", type="terminal", terminal_status="COMPLETED"),
                TerminalStep(key="complete", type="terminal", terminal_status="COMPLETED"),
            )
        }
    )
    with pytest.raises(DefinitionExecutionProtocolError, match="one role protocol"):
        definition_execution_protocol(no_agents)
    raw = yaml.safe_load((CONFIG / "generic-item-development.v1.2.yaml").read_text())
    raw["steps"][1]["result_schema"] = "image-result@1.0"
    mixed = WorkflowDefinition.model_validate(raw)
    with pytest.raises(DefinitionExecutionProtocolError, match="one role protocol"):
        definition_execution_protocol(mixed)
