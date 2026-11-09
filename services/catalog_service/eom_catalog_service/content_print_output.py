"""Connect a selected print scope to one exact successful curated publication."""

from eom_catalog_contracts.content_planning import ContentPrintScopeV1
from eom_catalog_contracts.content_print_commands import RecordContentPrintWithOutput
from eom_catalog_contracts.content_print_record import ContentPrintOutput
from eom_hwpx_contracts.curated_occurrences import CURATED_OCCURRENCE_PROFILE
from eom_operator_identity import ActorContext, PermissionKey
from sqlalchemy.orm import Session

from eom_catalog_service.content_delivery_service import read_content_delivery
from eom_catalog_service.content_planning_access import ContentPlanningError
from eom_catalog_service.curated_output_publication import read_curated_committed_output


def resolve_content_print_output(
    session: Session,
    command: RecordContentPrintWithOutput,
    scope: ContentPrintScopeV1,
    actor: ActorContext,
) -> ContentPrintOutput:
    if PermissionKey.HWPX_READ not in actor.permissions:
        raise ContentPlanningError("CONTENT_PLANNING_PERMISSION_DENIED")
    try:
        output = read_curated_committed_output(session, command.output_build_id)
    except ValueError as exc:
        raise ContentPlanningError("CONTENT_PRINT_OUTPUT_INVALID") from exc
    prepared, _manifest = read_content_delivery(
        session,
        output.assembly_id,
        output.assembly_revision_id,
        output.assembly_manifest_sha256,
        actor=actor,
        permission=PermissionKey.HWPX_READ,
    )
    if (
        prepared.edition_id != command.edition_id
        or prepared.revision_id != command.revision_id
        or prepared.composition_sha256 != command.composition_sha256
        or prepared.scope_sha256 != scope.scope_sha256
        or output.profile != CURATED_OCCURRENCE_PROFILE
        or output.output_sha256 != command.output_sha256
    ):
        raise ContentPlanningError("CONTENT_PRINT_OUTPUT_SCOPE_MISMATCH")
    return ContentPrintOutput(
        hwpx_build_id=output.build_id,
        scope_sha256=scope.scope_sha256,
        artifact_id=output.artifact_id,
        artifact_revision_id=output.artifact_revision_id,
        artifact_sha256=output.artifact_sha256,
        output_sha256=output.output_sha256,
    )
