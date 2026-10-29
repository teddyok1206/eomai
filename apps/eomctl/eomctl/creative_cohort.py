"""Admit a source cohort once; its stored owner is reauthorized on later claims."""

import json
import os
from pathlib import Path
from typing import Annotated

import typer
from eom_catalog_contracts.external_item_learning_authorization import (
    ExternalItemLearningAuthorizationRequest,
)
from eom_catalog_service.creative_learning_cohort import admit_creative_cohort
from eom_catalog_service.settings import CatalogSettings
from eom_orchestrator.database import build_engine
from eom_orchestrator.settings import Settings


def admit_cohort(
    seed_selection_file: Annotated[Path, typer.Option("--seed-selection-file")],
    import_id: Annotated[str, typer.Option("--import-id")],
    risk_policy_revision_id: Annotated[str, typer.Option("--risk-policy-revision-id")],
    access_policy_revision_id: Annotated[str, typer.Option("--access-policy-revision-id")],
    source_commit: Annotated[str, typer.Option("--source-commit")],
    username: Annotated[str, typer.Option("--username")],
) -> None:
    """Authenticate once and publish the exact target/policy plan; no worker starts."""
    from eomctl.creative_learning import _read_reviewed, _studio_operator_session

    selection = ExternalItemLearningAuthorizationRequest.model_validate(
        {
            "schema_version": "external-item-learning-authorization-request/1.0",
            "operation": "AUTHORIZE_EXTERNAL_ITEM_LEARNING_INPUT",
            "selection": json.loads(_read_reviewed(seed_selection_file, 16 * 1024)),
        }
    ).selection
    result: dict[str, object] = {"test_session_logout": "NOT_CREATED"}
    with _studio_operator_session(
        username=username, label="창작 문항 전체 순차 작업 제출 1회", result=result
    ) as (engine, actor_provider):
        cohort, published = admit_creative_cohort(
            engine,
            actor_provider=actor_provider,
            seed_selection=selection,
            import_id=import_id,
            risk_policy_revision_id=risk_policy_revision_id,
            access_policy_revision_id=access_policy_revision_id,
            source_commit=source_commit,
            settings=Settings.from_environment(),
            catalog_settings=CatalogSettings.from_environment(),
        )
        result.update(
            cohort_id=cohort.cohort_id,
            cohort_sha256=cohort.cohort_sha256,
            target_count=len(cohort.targets),
            artifact_id=published.artifact_id,
            artifact_revision_id=published.artifact_revision_id,
            artifact_sha256=published.primary_sha256,
        )
    typer.echo(json.dumps(result, ensure_ascii=False))


def continue_source_visuals(
    parent_revision_id: Annotated[str, typer.Option("--parent-cohort-revision-id")],
    instruction_directory: Annotated[Path, typer.Option("--instruction-directory")],
    pack_directory: Annotated[Path, typer.Option("--pack-directory")],
    definition_path: Annotated[Path, typer.Option("--definition-path")],
    source_commit: Annotated[str, typer.Option("--source-commit")],
) -> None:
    """Prepare the explicit successor of an admitted cohort; never start workers."""
    from eom_catalog_service.creative_continuation_preparation import (
        prepare_creative_source_continuation,
    )

    from eomctl.creative_learning import _read_reviewed

    if os.geteuid() != 0:
        raise ValueError("trusted installed maintenance owner is required")
    for path in (
        instruction_directory / "platform.md",
        instruction_directory / "external-item-learning.md",
        definition_path,
        pack_directory / "pack.yaml",
    ):
        _read_reviewed(path, 64 * 1024)
    engine = build_engine()
    try:
        scope, published = prepare_creative_source_continuation(
            engine,
            parent_revision_id=parent_revision_id,
            instruction_directory=instruction_directory,
            pack_directory=pack_directory,
            definition_path=definition_path,
            source_commit=source_commit,
            settings=Settings.from_environment(),
            catalog_settings=CatalogSettings.from_environment(),
        )
        typer.echo(
            json.dumps(
                {
                    "cohort_id": scope.cohort_id,
                    "artifact_revision_id": published.artifact_revision_id,
                    "artifact_sha256": published.primary_sha256,
                    "parent_revision_id": parent_revision_id,
                    "target_count": len(scope.cohort.targets),
                    "target_set_sha256": scope.cohort.target_set_sha256,
                    "definition_version": scope.workflow_definition_version,
                    "workers_started": 0,
                },
                ensure_ascii=False,
            )
        )
    finally:
        engine.dispose()
