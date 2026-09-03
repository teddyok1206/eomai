"""Presentation-only operator commands for legacy assessment extraction."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Never

import typer
from eom_catalog_contracts import (
    LegacyItemEditorialCompatibilityPolicy,
    LegacyItemEditorialCompatibilityRequest,
    LegacyItemExtractionAcceptance,
    LegacyItemExtractionRequest,
    LegacyItemPromotionRequest,
    LegacyRightsReviewPointerV2,
    ReconcileKnowledgeAnalysisCommand,
    validate_contract,
)
from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.intake_files import load_strict_json
from eom_catalog_service.knowledge_analysis_service import (
    KnowledgeAnalysisApplicationService,
    KnowledgeAnalysisServiceError,
)
from eom_catalog_service.legacy_assessment_registry import LegacyAssessmentRegistryError
from eom_catalog_service.legacy_assessment_rights import (
    LegacyAssessmentRightsError,
    LegacyAssessmentRightsPolicyAdapter,
)
from eom_catalog_service.legacy_item_acceptance_service import LegacyItemAcceptanceService
from eom_catalog_service.legacy_item_editorial_compatibility_service import (
    LegacyItemEditorialCompatibilityError,
    LegacyItemEditorialCompatibilityService,
)
from eom_catalog_service.legacy_item_editorial_validation import (
    LegacyItemEditorialDeterministicEvaluator,
)
from eom_catalog_service.legacy_item_extraction_service import (
    CreateLegacyItemExtractionCommand,
    LegacyItemExtractionApplicationService,
    LegacyItemExtractionServiceError,
)
from eom_catalog_service.legacy_item_learning_service import (
    LegacyItemLearningCoordinator,
    LegacyItemLearningError,
)
from eom_catalog_service.legacy_item_promotion_service import (
    LegacyItemPromotionError,
    LegacyItemPromotionService,
)
from eom_catalog_service.legacy_source_selection_adapters import (
    CatalogLegacyRightsReviewResolver,
)
from eom_hwpx_manager.content_team_compatibility_evidence import (
    ExistingContentTeamBuildEvidenceResolver,
)
from eom_orchestrator.database import build_engine
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Engine

legacy_assessment_app = typer.Typer(no_args_is_help=True)
extraction_app = typer.Typer(no_args_is_help=True)
acceptance_app = typer.Typer(no_args_is_help=True)
learning_app = typer.Typer(no_args_is_help=True)
compatibility_app = typer.Typer(no_args_is_help=True)
legacy_assessment_app.add_typer(extraction_app, name="extraction")
legacy_assessment_app.add_typer(acceptance_app, name="acceptance")
legacy_assessment_app.add_typer(learning_app, name="learning")
legacy_assessment_app.add_typer(compatibility_app, name="compatibility")


def _emit(value: object) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _failure(exc: LegacyItemExtractionServiceError) -> Never:
    _emit({"status": "FAILED", "error_code": exc.code})
    raise typer.Exit(1)


def _operation_failure(exc: Exception) -> Never:
    code = getattr(exc, "code", "LEGACY_ITEM_OPERATION_FAILED")
    _emit({"status": "FAILED", "error_code": str(code)})
    raise typer.Exit(1)


def _rights_adapter(
    engine: Engine,
    rights_pointer_file: Path,
) -> tuple[CatalogArtifactService, LegacyAssessmentRightsPolicyAdapter]:
    try:
        pointer = LegacyRightsReviewPointerV2.model_validate(load_strict_json(rights_pointer_file))
    except (PydanticValidationError, UnicodeError, ValueError) as exc:
        raise typer.BadParameter("legacy rights-review pointer is invalid") from exc
    artifacts = CatalogArtifactService(engine)
    rights = LegacyAssessmentRightsPolicyAdapter(
        resolver=CatalogLegacyRightsReviewResolver(artifacts),
        review_pointers=(pointer,),
    )
    return artifacts, rights


def _compatibility_service(engine: Engine) -> LegacyItemEditorialCompatibilityService:
    artifacts = CatalogArtifactService(engine)
    evaluator = LegacyItemEditorialDeterministicEvaluator(
        engine,
        artifacts=artifacts,
        render_evidence=ExistingContentTeamBuildEvidenceResolver(engine),
    )
    return LegacyItemEditorialCompatibilityService(
        engine,
        artifacts=artifacts,
        deterministic_evaluator=evaluator,
    )


@extraction_app.command("create")
def extraction_create(
    request_file: Annotated[
        Path,
        typer.Option("--request-file", exists=True, dir_okay=False, resolve_path=True),
    ],
    idempotency_key: Annotated[str, typer.Option("--idempotency-key")],
    actor_id: Annotated[str, typer.Option("--actor-id")],
) -> None:
    """Create one extraction from an exact reviewed request document."""

    try:
        raw_request = load_strict_json(request_file)
        validate_contract("legacy-item-extraction-request", raw_request)
        request = LegacyItemExtractionRequest.model_validate(raw_request)
        command = CreateLegacyItemExtractionCommand(
            request=request,
            idempotency_key=idempotency_key,
            requested_by=actor_id,
        )
    except (
        JsonSchemaValidationError,
        PydanticValidationError,
        UnicodeError,
        ValueError,
    ) as exc:
        raise typer.BadParameter("legacy item extraction request is invalid") from exc
    engine = build_engine()
    try:
        service = LegacyItemExtractionApplicationService(engine)
        try:
            result = service.create(command)
        except LegacyItemExtractionServiceError as exc:
            _failure(exc)
        _emit({"status": "SUCCEEDED", **result.as_dict()})
    finally:
        engine.dispose()


@extraction_app.command("inspect")
def extraction_inspect(
    workflow_id: Annotated[str, typer.Argument()],
) -> None:
    """Inspect only the workflow, plan, Job, and immutable receipt pointers."""

    engine = build_engine()
    try:
        service = LegacyItemExtractionApplicationService(engine)
        try:
            result = service.inspect(workflow_id)
        except LegacyItemExtractionServiceError as exc:
            _failure(exc)
        _emit({"status": "SUCCEEDED", **result.as_dict()})
    finally:
        engine.dispose()


@acceptance_app.command("register")
def acceptance_register(
    acceptance_file: Annotated[
        Path,
        typer.Option("--acceptance-file", exists=True, dir_okay=False, resolve_path=True),
    ],
    rights_pointer_file: Annotated[
        Path,
        typer.Option("--rights-pointer-file", exists=True, dir_okay=False, resolve_path=True),
    ],
) -> None:
    """Commit and register one exact human-reviewed extraction acceptance."""

    try:
        raw = load_strict_json(acceptance_file)
        validate_contract("legacy-item-extraction-acceptance", raw)
        acceptance = LegacyItemExtractionAcceptance.model_validate(raw)
    except (
        JsonSchemaValidationError,
        PydanticValidationError,
        UnicodeError,
        ValueError,
    ) as exc:
        raise typer.BadParameter("legacy extraction acceptance is invalid") from exc
    engine = build_engine()
    try:
        try:
            artifacts, rights = _rights_adapter(engine, rights_pointer_file)
            registered = LegacyItemAcceptanceService(
                engine,
                rights=rights,
                artifacts=artifacts,
            ).register(acceptance)
        except (
            LegacyAssessmentRegistryError,
            LegacyAssessmentRightsError,
            ValueError,
        ) as exc:
            _operation_failure(exc)
        _emit({"status": "SUCCEEDED", **asdict(registered)})
    finally:
        engine.dispose()


@learning_app.command("start")
def learning_start(
    promotion_file: Annotated[
        Path,
        typer.Option("--promotion-file", exists=True, dir_okay=False, resolve_path=True),
    ],
    rights_pointer_file: Annotated[
        Path,
        typer.Option("--rights-pointer-file", exists=True, dir_okay=False, resolve_path=True),
    ],
    risk_policy_revision_id: Annotated[str, typer.Option("--risk-policy-revision-id")],
) -> None:
    """Promote one accepted proposal and queue the ordinary approved-item analysis."""

    try:
        raw = load_strict_json(promotion_file)
        validate_contract("legacy-item-promotion-request", raw)
        command = LegacyItemPromotionRequest.model_validate(raw)
    except (
        JsonSchemaValidationError,
        PydanticValidationError,
        UnicodeError,
        ValueError,
    ) as exc:
        raise typer.BadParameter("legacy item promotion request is invalid") from exc
    engine = build_engine()
    try:
        try:
            artifacts, rights = _rights_adapter(engine, rights_pointer_file)
            promotion = LegacyItemPromotionService(
                engine,
                rights=rights,
                artifacts=artifacts,
            )
            result = LegacyItemLearningCoordinator(
                engine,
                promotion=promotion,
            ).promote_and_schedule(
                command,
                risk_policy_revision_id=risk_policy_revision_id,
            )
        except (
            LegacyAssessmentRightsError,
            LegacyItemLearningError,
            LegacyItemPromotionError,
            KnowledgeAnalysisServiceError,
            ValueError,
        ) as exc:
            _operation_failure(exc)
        _emit(
            {
                "status": "SUCCEEDED",
                "source": result.source.model_dump(mode="json"),
                "analysis": result.analysis.model_dump(mode="json"),
                "item_created": result.item_created,
                "origin_created": result.origin_created,
            }
        )
    finally:
        engine.dispose()


@learning_app.command("reconcile")
def learning_reconcile(
    analysis_run_id: Annotated[str, typer.Argument()],
    actor_id: Annotated[str, typer.Option("--actor-id")],
) -> None:
    """Advance one knowledge-analysis run from exact persisted workflow evidence."""

    engine = build_engine()
    try:
        try:
            result = KnowledgeAnalysisApplicationService(engine).reconcile(
                ReconcileKnowledgeAnalysisCommand(
                    analysis_run_id=analysis_run_id,
                    requested_by=actor_id,
                )
            )
        except (KnowledgeAnalysisServiceError, ValueError) as exc:
            _operation_failure(exc)
        _emit({"status": "SUCCEEDED", **result.model_dump(mode="json")})
    finally:
        engine.dispose()


@learning_app.command("retry")
def learning_retry(
    predecessor_analysis_run_id: Annotated[str, typer.Argument()],
    actor_id: Annotated[str, typer.Option("--actor-id")],
) -> None:
    """Create one explicit successor for a terminal failed legacy-item analysis."""

    engine = build_engine()
    try:
        try:
            result = LegacyItemLearningCoordinator(engine).retry_failed_analysis(
                predecessor_analysis_run_id=predecessor_analysis_run_id,
                requested_by=actor_id,
            )
        except (
            LegacyItemLearningError,
            KnowledgeAnalysisServiceError,
            ValueError,
        ) as exc:
            _operation_failure(exc)
        _emit({"status": "SUCCEEDED", **result.model_dump(mode="json")})
    finally:
        engine.dispose()


@compatibility_app.command("release-policy")
def compatibility_release_policy(
    policy_file: Annotated[
        Path,
        typer.Option("--policy-file", exists=True, dir_okay=False, resolve_path=True),
    ],
) -> None:
    """Release one lifecycle-only compatibility policy revision."""

    try:
        raw = load_strict_json(policy_file)
        validate_contract("legacy-item-editorial-compatibility-policy", raw)
        policy = LegacyItemEditorialCompatibilityPolicy.model_validate(raw)
    except (
        JsonSchemaValidationError,
        PydanticValidationError,
        UnicodeError,
        ValueError,
    ) as exc:
        raise typer.BadParameter("editorial compatibility policy is invalid") from exc
    engine = build_engine()
    try:
        try:
            released = _compatibility_service(engine).release_policy(policy)
        except (LegacyItemEditorialCompatibilityError, ValueError) as exc:
            _operation_failure(exc)
        _emit({"status": "SUCCEEDED", **released.model_dump(mode="json")})
    finally:
        engine.dispose()


@compatibility_app.command("submit")
def compatibility_submit(
    request_file: Annotated[
        Path,
        typer.Option("--request-file", exists=True, dir_okay=False, resolve_path=True),
    ],
    idempotency_key: Annotated[str, typer.Option("--idempotency-key")],
    actor_id: Annotated[str, typer.Option("--actor-id")],
) -> None:
    """Submit one exact Item/prompt/handoff revision tuple for compatibility analysis."""

    try:
        raw = load_strict_json(request_file)
        validate_contract("legacy-item-editorial-compatibility-request", raw)
        request = LegacyItemEditorialCompatibilityRequest.model_validate(raw)
    except (
        JsonSchemaValidationError,
        PydanticValidationError,
        UnicodeError,
        ValueError,
    ) as exc:
        raise typer.BadParameter("editorial compatibility request is invalid") from exc
    engine = build_engine()
    try:
        try:
            result = _compatibility_service(engine).submit(
                request,
                idempotency_key=idempotency_key,
                requested_by=actor_id,
            )
        except (LegacyItemEditorialCompatibilityError, ValueError) as exc:
            _operation_failure(exc)
        _emit({"status": "SUCCEEDED", **asdict(result)})
    finally:
        engine.dispose()


@compatibility_app.command("inspect")
def compatibility_inspect(compatibility_run_id: Annotated[str, typer.Argument()]) -> None:
    """Inspect one bounded compatibility lifecycle projection."""

    engine = build_engine()
    try:
        try:
            result = _compatibility_service(engine).inspect(compatibility_run_id)
        except LegacyItemEditorialCompatibilityError as exc:
            _operation_failure(exc)
        _emit({"status": "SUCCEEDED", **asdict(result)})
    finally:
        engine.dispose()


@compatibility_app.command("reconcile")
def compatibility_reconcile(
    compatibility_run_id: Annotated[str, typer.Argument()],
    actor_id: Annotated[str, typer.Option("--actor-id")],
) -> None:
    """Advance one compatibility run from exact persisted workflow evidence."""

    engine = build_engine()
    try:
        try:
            result = _compatibility_service(engine).reconcile(
                compatibility_run_id,
                actor_id=actor_id,
            )
        except (LegacyItemEditorialCompatibilityError, ValueError) as exc:
            _operation_failure(exc)
        _emit({"status": "SUCCEEDED", **asdict(result)})
    finally:
        engine.dispose()
