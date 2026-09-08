"""Read-only exact resolution of the production plan's one-Item generation block."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Never

from eom_api_contracts.mock_exam_execution import MockExamGenerationBlockResolutionV1
from eom_catalog_contracts.mock_exam_production_plan import MockExamOneItemGenerationBlockV1
from eom_catalog_service.models import (
    ContentPackActivationRecord,
    ContentPackRecord,
    ContentPackReleaseRecord,
)
from eom_orchestrator.control_models import (
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
)
from eom_orchestrator.database import build_session_factory
from eom_workflow import AgentStep, ExecutionPresetRevisionV2, compile_definition_data
from eom_workflow.admission import workflow_definition_is_admitted
from eom_workflow.schemas import result_schema_protocol
from eom_workflow_runner.models import WorkflowDefinitionRecord
from sqlalchemy import Engine, select, true


class MockExamGenerationBlockResolutionError(RuntimeError):
    """Stable failure raised before any production Workflow is started."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DatabaseGenerationBlockResolver:
    """Resolve all mutable current selectors in one database snapshot statement."""

    def __init__(
        self,
        engine: Engine,
        *,
        environment: Literal["development", "test"] = "development",
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.environment = environment

    def resolve_generation_block(
        self, block: MockExamOneItemGenerationBlockV1
    ) -> MockExamGenerationBlockResolutionV1:
        statement = (
            select(
                WorkflowDefinitionRecord,
                ContentPackActivationRecord,
                ContentPackReleaseRecord,
                ContentPackRecord,
                ExecutionPresetRecord,
                ExecutionPresetRevisionRecord,
            )
            .select_from(WorkflowDefinitionRecord)
            .join(ContentPackActivationRecord, true())
            .join(
                ContentPackReleaseRecord,
                ContentPackReleaseRecord.content_pack_release_id
                == ContentPackActivationRecord.content_pack_release_id,
            )
            .join(
                ContentPackRecord,
                ContentPackRecord.content_pack_id == ContentPackReleaseRecord.content_pack_id,
            )
            .join(ExecutionPresetRecord, true())
            .join(
                ExecutionPresetRevisionRecord,
                ExecutionPresetRevisionRecord.preset_revision_id
                == ExecutionPresetRecord.current_revision_id,
            )
            .where(
                WorkflowDefinitionRecord.definition_key == block.workflow_definition_key,
                WorkflowDefinitionRecord.definition_version
                == block.workflow_definition_version,
                WorkflowDefinitionRecord.active.is_(True),
                ContentPackActivationRecord.pack_key == block.content_pack_key,
                ContentPackActivationRecord.environment == self.environment,
                ContentPackActivationRecord.active.is_(True),
                ContentPackReleaseRecord.state == "RELEASED",
                ContentPackRecord.pack_key == block.content_pack_key,
                ExecutionPresetRecord.preset_key == block.execution_preset_key,
                ExecutionPresetRecord.state == "ACTIVE",
                ExecutionPresetRevisionRecord.state == "RELEASED",
            )
        )
        with self.sessions() as session, session.begin():
            row = session.execute(statement).one_or_none()
        if row is None:
            self._fail(
                "PRODUCTION_GENERATION_BLOCK_DEPENDENCY_MISSING",
                "one or more current generation-block dependencies do not resolve",
            )
        definition, _activation, release, pack, preset_logical, preset_revision = row
        if not workflow_definition_is_admitted(
            definition.definition_key, definition.definition_version
        ):
            self._fail(
                "PRODUCTION_WORKFLOW_DEFINITION_NOT_ADMITTED",
                "generation-block Workflow definition is not admitted",
            )
        if (
            release.version != block.content_pack_version
            or release.source_tree_sha256 != block.content_pack_source_tree_sha256
            or pack.pack_key != block.content_pack_key
            or not any(
                item.get("key") == definition.definition_key
                and definition.definition_version in item.get("versions", [])
                for item in release.compatibility_json.get("workflow_definitions", [])
                if isinstance(item, dict)
            )
        ):
            self._fail(
                "PRODUCTION_CONTENT_PACK_DRIFT",
                "current Content Pack differs from the generation block",
            )
        compiled = compile_definition_data(
            definition.canonical_definition,
            definition.source_path,
            {"authoring", "image", "review", "item_management"},
        )
        protocols = {
            result_schema_protocol(step.result_schema)
            for step in compiled.definition.steps
            if isinstance(step, AgentStep)
        }
        if len(protocols) != 1:
            self._fail(
                "PRODUCTION_WORKFLOW_DEFINITION_INVALID",
                "generation-block Workflow definition has inconsistent role protocols",
            )
        try:
            preset = ExecutionPresetRevisionV2.model_validate(
                preset_revision.canonical_document
            )
        except ValueError as exc:
            raise MockExamGenerationBlockResolutionError(
                "PRODUCTION_EXECUTION_PRESET_INVALID",
                "current generation-block preset is not a valid V2 revision",
            ) from exc
        if (
            preset_logical.preset_id != preset_revision.preset_id
            or preset.preset_id != preset_logical.preset_id
            or preset.preset_revision_id != preset_revision.preset_revision_id
            or preset.content_sha256 != preset_revision.content_sha256
            or str(next(iter(protocols))) not in preset.compatible_workflow_protocols
        ):
            self._fail(
                "PRODUCTION_EXECUTION_PRESET_DRIFT",
                "current execution preset pointers or protocol compatibility differ",
            )
        return MockExamGenerationBlockResolutionV1(
            generation_block_key=block.block_key,
            generation_block_revision=block.block_revision,
            generation_block_sha256=block.block_sha256,
            workflow_definition_key=definition.definition_key,
            workflow_definition_version=definition.definition_version,
            workflow_definition_sha256=definition.definition_hash,
            content_pack_release_id=release.content_pack_release_id,
            content_pack_key=pack.pack_key,
            content_pack_version=release.version,
            content_pack_release_sha256=release.bundle_sha256,
            content_pack_source_tree_sha256=release.source_tree_sha256,
            execution_preset_id=preset.preset_id,
            execution_preset_revision_id=preset.preset_revision_id,
            execution_preset_key=preset_logical.preset_key,
            execution_preset_sha256=preset.content_sha256,
            resolved_at=datetime.now(UTC),
        )

    @staticmethod
    def _fail(code: str, message: str) -> Never:
        raise MockExamGenerationBlockResolutionError(code, message)
