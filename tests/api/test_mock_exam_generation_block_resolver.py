from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_api.services.mock_exam_generation_block_resolver import (
    DatabaseGenerationBlockResolver,
    MockExamGenerationBlockResolutionError,
)
from eom_catalog_contracts import (
    load_integrated_science_editorial_outline,
    load_integrated_science_mock_exam_layout_policy,
    load_integrated_science_mock_exam_policy,
)
from eom_catalog_contracts.mock_exam_production_plan import (
    MockExamOneItemGenerationBlockV1,
    build_integrated_science_mock_exam_production_plan,
)
from eom_workflow import AgentStep, compile_definition
from eom_workflow.schemas import result_schema_protocol

ROOT = Path(__file__).resolve().parents[2]


class _Result:
    def __init__(self, value: object | None) -> None:
        self.value = value

    def one_or_none(self) -> object | None:
        return self.value


class _Session:
    def __init__(self, value: object | None) -> None:
        self.value = value
        self.statement = ""

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def begin(self) -> nullcontext[None]:
        return nullcontext()

    def execute(self, statement: object) -> _Result:
        self.statement = str(statement)
        return _Result(self.value)


def _block() -> MockExamOneItemGenerationBlockV1:
    plan = build_integrated_science_mock_exam_production_plan(
        policy=load_integrated_science_mock_exam_policy(),
        layout_policy=load_integrated_science_mock_exam_layout_policy(),
        outline=load_integrated_science_editorial_outline(),
    )
    return plan.one_item_generation_block


def _row(*, source_tree_sha256: str | None = None) -> tuple[object, ...]:
    block = _block()
    compiled = compile_definition(
        ROOT / "config/workflows/generic-item-development.v1.8.yaml",
        {"authoring", "image", "review", "item_management"},
    )
    definition = SimpleNamespace(
        definition_key=block.workflow_definition_key,
        definition_version=block.workflow_definition_version,
        definition_hash=compiled.sha256,
        canonical_definition=compiled.as_dict(),
        source_path=compiled.source_path,
    )
    activation = SimpleNamespace(active=True)
    release = SimpleNamespace(
        content_pack_release_id="packrel_" + "2" * 32,
        content_pack_id="pack_" + "3" * 32,
        version=block.content_pack_version,
        source_tree_sha256=source_tree_sha256 or block.content_pack_source_tree_sha256,
        bundle_sha256="sha256:" + "4" * 64,
        compatibility_json={
            "workflow_definitions": [
                {
                    "key": block.workflow_definition_key,
                    "versions": [block.workflow_definition_version],
                }
            ]
        },
    )
    pack = SimpleNamespace(pack_key=block.content_pack_key)
    logical = SimpleNamespace(
        preset_id="execpreset_" + "5" * 32,
        preset_key=block.execution_preset_key,
    )
    revision = SimpleNamespace(
        preset_id=logical.preset_id,
        preset_revision_id="execpresetrev_" + "6" * 32,
        content_sha256="sha256:" + "7" * 64,
        canonical_document={},
    )
    return definition, activation, release, pack, logical, revision


def _resolver(session: _Session) -> DatabaseGenerationBlockResolver:
    resolver = object.__new__(DatabaseGenerationBlockResolver)
    resolver.sessions = lambda: session  # type: ignore[method-assign]
    resolver.environment = "development"
    return resolver


def test_generation_block_resolver_pins_all_current_dependencies_in_one_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row()
    revision = row[-1]
    definition = row[0]
    compiled = compile_definition(
        ROOT / "config/workflows/generic-item-development.v1.8.yaml",
        {"authoring", "image", "review", "item_management"},
    )
    protocol = next(
        result_schema_protocol(step.result_schema)
        for step in compiled.definition.steps
        if isinstance(step, AgentStep)
    )
    preset = SimpleNamespace(
        preset_id=revision.preset_id,
        preset_revision_id=revision.preset_revision_id,
        content_sha256=revision.content_sha256,
        compatible_workflow_protocols=(protocol,),
    )
    monkeypatch.setattr(
        "eom_api.services.mock_exam_generation_block_resolver.ExecutionPresetRevisionV2.model_validate",
        staticmethod(lambda _value: preset),
    )
    session = _Session(row)

    result = _resolver(session).resolve_generation_block(_block())

    assert result.workflow_definition_sha256 == definition.definition_hash
    assert result.content_pack_release_id == row[2].content_pack_release_id
    assert result.content_pack_release_sha256 == row[2].bundle_sha256
    assert result.execution_preset_revision_id == revision.preset_revision_id
    assert result.resolved_at.utcoffset() is not None
    assert "content_pack_activations.active IS true" in session.statement
    assert "workflow_definitions.active IS true" in session.statement


def test_generation_block_resolver_rejects_missing_or_source_tree_drift() -> None:
    with pytest.raises(MockExamGenerationBlockResolutionError) as missing:
        _resolver(_Session(None)).resolve_generation_block(_block())
    assert missing.value.code == "PRODUCTION_GENERATION_BLOCK_DEPENDENCY_MISSING"

    with pytest.raises(MockExamGenerationBlockResolutionError) as drift:
        _resolver(_Session(_row(source_tree_sha256="sha256:" + "f" * 64))).resolve_generation_block(
            _block()
        )
    assert drift.value.code == "PRODUCTION_CONTENT_PACK_DRIFT"
