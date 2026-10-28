"""Local trusted completion adapter for an already admitted creative Workflow."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer
from eom_catalog_contracts.external_item_learning_authorization import (
    ExternalItemLearningAuthorizationRequest,
)
from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.creative_item_graph_learning import (
    CreativeItemGraphLearningService,
    prepare_creative_analysis_controls,
)
from eom_catalog_service.creative_item_registration import (
    CreativeItemRegistrationService,
    prepare_creative_registration_pack,
)
from eom_catalog_service.creative_learning_proposal import (
    resolve_completed_creative_learning_proposal,
)
from eom_catalog_service.settings import CatalogSettings
from eom_orchestrator.database import build_engine, build_session_factory
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.settings import Settings


def complete_learning(
    selection_file: Annotated[Path, typer.Option("--selection-file")],
    pack_directory: Annotated[Path, typer.Option("--pack-directory")],
    source_commit: Annotated[str, typer.Option("--source-commit")],
    access_policy_revision_id: Annotated[str, typer.Option("--access-policy-revision-id")],
    preset_revision_id: Annotated[str, typer.Option("--preset-revision-id")],
    risk_policy_revision_id: Annotated[str, typer.Option("--risk-policy-revision-id")],
) -> None:
    """Advance source registration and the existing analysis/Graph stages once.

    Authority is the stored, originally authenticated task owner reauthorized at
    each mutation. A root shell or a caller-supplied operator ID is not a grant.
    This never starts a new extraction or rewrites a previous failure.
    """
    from eomctl.creative_learning import _read_reviewed

    if os.geteuid() != 0:
        raise typer.BadParameter("trusted local owner is required")
    selection = ExternalItemLearningAuthorizationRequest.model_validate(
        {
            "schema_version": "external-item-learning-authorization-request/1.0",
            "operation": "AUTHORIZE_EXTERNAL_ITEM_LEARNING_INPUT",
            "selection": json.loads(_read_reviewed(selection_file, 16 * 1024)),
        }
    ).selection
    engine = build_engine()
    try:
        settings = CatalogSettings.from_environment()
        sessions = build_session_factory(engine)
        with sessions() as session:
            resolved = resolve_completed_creative_learning_proposal(
                session, CatalogArtifactService(engine, settings), selection
            )
        pack_release_id = prepare_creative_registration_pack(
            engine, settings=settings, pack_directory=pack_directory, selection=selection
        )
        registered = CreativeItemRegistrationService(
            engine,
            content_pack_release_id=pack_release_id,
            publisher=ControlFileSetPublisher(engine, Settings.from_environment()),
            source_commit=source_commit,
            settings=settings,
        ).register_completed(selection, requested_by_operator_id=resolved.operator_id)
        analysis_preset = prepare_creative_analysis_controls(
            engine,
            selection=selection,
            baseline_revision_id=preset_revision_id,
            source_commit=source_commit,
            settings=settings,
        )
        progress = CreativeItemGraphLearningService(
            engine,
            settings=settings,
            access_policy_revision_id=access_policy_revision_id,
            preset_key="creative-knowledge-analysis",
            preset_id=analysis_preset.preset_id,
            preset_revision_id=analysis_preset.preset_revision_id,
            risk_policy_revision_id=risk_policy_revision_id,
        ).advance(
            item_revision_id=registered.item_revision_id,
            requested_by_operator_id=resolved.operator_id,
        )
        typer.echo(
            json.dumps(
                {
                    **asdict(progress),
                    "item_id": registered.item_id,
                    "external_number": registered.lineage.external_number,
                    "registered_created": registered.created,
                    "warnings": registered.lineage.warning_codes,
                },
                ensure_ascii=False,
            )
        )
    finally:
        engine.dispose()
