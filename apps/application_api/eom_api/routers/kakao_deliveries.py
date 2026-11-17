"""Packet/PDF transport. The existing Catalog owners retain work and authorization."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, cast

from eom_api_contracts import SingleResponse
from eom_api_contracts.kakao_deliveries import (
    KakaoExport,
    KakaoExportCreate,
    KakaoExportMutation,
    KakaoExportPage,
    KakaoPacketCreate,
    KakaoPacketMutation,
    KakaoPacketPage,
    KakaoPacketRevise,
    KakaoPacketView,
    KakaoStudyCreate,
    KakaoStudyExport,
    KakaoStudyExportCreate,
    KakaoStudyExportMutation,
    KakaoStudyMutation,
    KakaoStudyPage,
    KakaoStudyRevise,
    KakaoStudyView,
)
from eom_catalog_contracts.kakao_delivery_rpc import (
    KAKAO_DELIVERY_ERRORS,
    CreateKakaoExportRequest,
    CreateKakaoStudyExportRequest,
    KakaoDeliveryRequest,
    KakaoDeliveryResult,
    ListKakaoExportsRequest,
    ListKakaoPacketsRequest,
    ListKakaoStudiesRequest,
    ReadKakaoExportPdfRequest,
    ReadKakaoExportRequest,
    ReadKakaoPacketRequest,
    ReadKakaoStudyExportRequest,
    ReadKakaoStudyRequest,
    ReadKakaoStudySelectionRequest,
    SaveKakaoPacketRequest,
    SaveKakaoStudyRequest,
)
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.responses import StreamingResponse

from eom_api.dependencies import Auth, ExpectedVersion, IdempotencyKey, etag, require_permission
from eom_api.errors import ApiError
from eom_api.routers.common import one
from eom_api.services.catalog_application_client import CatalogApplicationClientError

router = APIRouter(prefix="/kakao-archive", tags=["kakao-archive"])
BindingId = Annotated[str, Query(pattern=r"^kakaobinding_[0-9a-f]{32}$")]
PacketId = Annotated[str, Path(pattern=r"^kakaopacket_[0-9a-f]{32}$")]
PacketRevisionId = Annotated[str, Path(pattern=r"^kakaopacketrev_[0-9a-f]{32}$")]
ExportId = Annotated[str, Path(pattern=r"^kakaoexport_[0-9a-f]{32}$")]
StudyId = Annotated[str, Path(pattern=r"^kakaostudy_[0-9a-f]{32}$")]
StudyRevisionId = Annotated[str, Path(pattern=r"^kakaostudyrev_[0-9a-f]{32}$")]
StudentId = Annotated[str, Path(pattern=r"^kakaostudent_[0-9a-f]{32}$")]
READ = require_permission(PermissionKey.KAKAO_ARCHIVE_READ)
EXPORT = require_permission(PermissionKey.KAKAO_ARCHIVE_EXPORT)
EDIT = require_permission(PermissionKey.KAKAO_ARCHIVE_EDIT)


def _identity(request: Request) -> dict[str, object]:
    actor = request.state.request_context.actor()
    return dict(
        actor_id=actor.operator_id,
        session_id=actor.session_id,
        request_id=actor.request_id,
        authentication_time=actor.authentication_time,
    )


@contextmanager
def _boundary() -> Iterator[None]:
    try:
        yield
    except CatalogApplicationClientError as error:
        code = error.code if error.code in KAKAO_DELIVERY_ERRORS else "KAKAO_ARCHIVE_UNAVAILABLE"
        status = {
            "KAKAO_ARCHIVE_PERMISSION_DENIED": 403,
            "KAKAO_ARCHIVE_RESOURCE_NOT_FOUND": 404,
            "KAKAO_ARCHIVE_PRECONDITION_FAILED": 412,
            "KAKAO_ARCHIVE_REQUEST_INVALID": 422,
            "KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT": 409,
            "KAKAO_ARCHIVE_FINAL_BLOCKED": 409,
            "KAKAO_ARCHIVE_QUESTION_OUTSIDE_PERIOD": 409,
            "KAKAO_ARCHIVE_STUDENT_DISPLAY_CONFLICT": 409,
            "KAKAO_ARCHIVE_PERIOD_INVALID": 422,
            "KAKAO_ARCHIVE_STUDENT_UNMAPPED": 409,
            "KAKAO_ARCHIVE_STUDENT_NOT_IN_PACKET": 409,
            "KAKAO_ARCHIVE_QUESTION_EXCLUDED": 409,
            "KAKAO_ARCHIVE_EMPTY_SELECTION": 409,
            "KAKAO_ARCHIVE_BINDING_RETIRED": 409,
            "KAKAO_ARCHIVE_ROOM_RETIRED": 409,
            "KAKAO_ARCHIVE_EXPORT_NOT_COMPLETED": 409,
            "KAKAO_STUDY_PACKET_CHANGED": 409,
            "KAKAO_STUDY_SOURCE_CHANGED": 409,
            "KAKAO_STUDY_QUESTION_SET_MISMATCH": 422,
            "KAKAO_STUDY_BLOCK_SELECTION_INVALID": 422,
            "KAKAO_STUDY_CONCEPT_QUESTION_MISMATCH": 422,
            "KAKAO_STUDY_EXPORT_INVALID": 409,
            "KAKAO_STUDY_CONTRACT_INVALID": 422,
            "KAKAO_CONCEPT_RESULT_NOT_READY": 409,
        }.get(code, 503)
        raise ApiError(
            status,
            code,
            "KakaoTalk request failed",
            "The private packet or PDF operation could not be completed.",
        ) from error


def _call(request: Request, command: KakaoDeliveryRequest) -> KakaoDeliveryResult:
    with _boundary():
        return cast(
            KakaoDeliveryResult,
            request.app.state.services.catalog_application.request_kakao_delivery(command),
        )


@router.post(
    "/question-packets",
    operation_id="kakao_packet_create",
    status_code=201,
    response_model=SingleResponse[KakaoPacketMutation],
    dependencies=[Depends(EXPORT)],
)
def create_packet(
    request: Request,
    response: Response,
    body: KakaoPacketCreate,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[KakaoPacketMutation]:
    value = cast(
        KakaoPacketMutation,
        _call(
            request,
            SaveKakaoPacketRequest.model_validate(
                {**_identity(request), "command": body, "idempotency_key": idempotency_key}
            ),
        ),
    )
    response.headers.update(
        {"Cache-Control": "no-store", "ETag": etag(value.packet.resource_version)}
    )
    return one(request, value)


@router.patch(
    "/question-packets/{packet_id}",
    operation_id="kakao_packet_revise",
    response_model=SingleResponse[KakaoPacketMutation],
    dependencies=[Depends(EXPORT)],
)
def revise_packet(
    request: Request,
    response: Response,
    packet_id: PacketId,
    body: KakaoPacketRevise,
    authentication: Auth,
    expected: ExpectedVersion,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[KakaoPacketMutation]:
    if body.packet_id != packet_id or body.expected_resource_version != expected:
        raise ApiError(
            412,
            "KAKAO_ARCHIVE_PRECONDITION_FAILED",
            "Packet version differs",
            "Select the current packet revision.",
        )
    value = cast(
        KakaoPacketMutation,
        _call(
            request,
            SaveKakaoPacketRequest.model_validate(
                {**_identity(request), "command": body, "idempotency_key": idempotency_key}
            ),
        ),
    )
    response.headers.update(
        {"Cache-Control": "no-store", "ETag": etag(value.packet.resource_version)}
    )
    return one(request, value)


@router.get(
    "/question-packets",
    operation_id="kakao_packet_list",
    response_model=SingleResponse[KakaoPacketPage],
    dependencies=[Depends(READ)],
)
def list_packets(
    request: Request,
    response: Response,
    source_binding_id: BindingId,
    authentication: Auth,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, pattern=r"^kakaopacket_[0-9a-f]{32}$"),
) -> SingleResponse[KakaoPacketPage]:
    value = cast(
        KakaoPacketPage,
        _call(
            request,
            ListKakaoPacketsRequest.model_validate(
                {
                    **_identity(request),
                    "source_binding_id": source_binding_id,
                    "limit": limit,
                    "cursor": cursor,
                }
            ),
        ),
    )
    response.headers["Cache-Control"] = "no-store"
    return one(request, value)


@router.get(
    "/question-packets/{packet_id}/revisions/{revision_id}",
    operation_id="kakao_packet_read",
    response_model=SingleResponse[KakaoPacketView],
    dependencies=[Depends(READ)],
)
def read_packet(
    request: Request,
    response: Response,
    packet_id: PacketId,
    revision_id: PacketRevisionId,
    source_binding_id: BindingId,
    authentication: Auth,
) -> SingleResponse[KakaoPacketView]:
    value = cast(
        KakaoPacketView,
        _call(
            request,
            ReadKakaoPacketRequest.model_validate(
                {
                    **_identity(request),
                    "source_binding_id": source_binding_id,
                    "packet_id": packet_id,
                    "packet_revision_id": revision_id,
                }
            ),
        ),
    )
    response.headers.update(
        {"Cache-Control": "no-store", "ETag": etag(value.packet.resource_version)}
    )
    return one(request, value)


@router.post(
    "/exports",
    operation_id="kakao_export_create",
    status_code=202,
    response_model=SingleResponse[KakaoExportMutation],
    dependencies=[Depends(EXPORT)],
)
def create_export(
    request: Request,
    response: Response,
    body: KakaoExportCreate,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[KakaoExportMutation]:
    value = cast(
        KakaoExportMutation,
        _call(
            request,
            CreateKakaoExportRequest.model_validate(
                {**_identity(request), "command": body, "idempotency_key": idempotency_key}
            ),
        ),
    )
    response.headers["Cache-Control"] = "no-store"
    return one(request, value)


@router.get(
    "/exports",
    operation_id="kakao_export_list",
    response_model=SingleResponse[KakaoExportPage],
    dependencies=[Depends(READ)],
)
def list_exports(
    request: Request,
    response: Response,
    source_binding_id: BindingId,
    authentication: Auth,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, pattern=r"^kakaoexport_[0-9a-f]{32}$"),
) -> SingleResponse[KakaoExportPage]:
    value = cast(
        KakaoExportPage,
        _call(
            request,
            ListKakaoExportsRequest.model_validate(
                {
                    **_identity(request),
                    "source_binding_id": source_binding_id,
                    "limit": limit,
                    "cursor": cursor,
                }
            ),
        ),
    )
    response.headers["Cache-Control"] = "no-store"
    return one(request, value)


@router.get(
    "/exports/{export_id}",
    operation_id="kakao_export_read",
    response_model=SingleResponse[KakaoExport],
    dependencies=[Depends(READ)],
)
def read_export(
    request: Request,
    response: Response,
    export_id: ExportId,
    source_binding_id: BindingId,
    authentication: Auth,
) -> SingleResponse[KakaoExport]:
    value = cast(
        KakaoExport,
        _call(
            request,
            ReadKakaoExportRequest.model_validate(
                {
                    **_identity(request),
                    "source_binding_id": source_binding_id,
                    "export_id": export_id,
                }
            ),
        ),
    )
    response.headers["Cache-Control"] = "no-store"
    return one(request, value)


@router.get(
    "/exports/{export_id}/file",
    operation_id="kakao_export_download",
    dependencies=[Depends(EXPORT)],
)
def download_export(
    request: Request,
    export_id: ExportId,
    source_binding_id: BindingId,
    authentication: Auth,
    revision_id: Annotated[str, Query(pattern=r"^kakaoexportrev_[0-9a-f]{32}$")],
) -> StreamingResponse:
    command = ReadKakaoExportPdfRequest.model_validate(
        {
            **_identity(request),
            "source_binding_id": source_binding_id,
            "export_id": export_id,
            "export_revision_id": revision_id,
        }
    )
    with _boundary():
        value = request.app.state.services.catalog_application.download_kakao_export_pdf(command)
    return StreamingResponse(
        value.iter_chunks(),
        media_type="application/pdf",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Length": str(value.content_length),
            "Content-Disposition": f'attachment; filename="{export_id}.pdf"',
            "ETag": '"' + value.sha256 + '"',
        },
    )


@router.post(
    "/studies",
    operation_id="kakao_study_create",
    status_code=201,
    response_model=SingleResponse[KakaoStudyMutation],
    dependencies=[Depends(EDIT)],
)
def create_study(
    request: Request,
    response: Response,
    body: KakaoStudyCreate,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[KakaoStudyMutation]:
    value = cast(
        KakaoStudyMutation,
        _call(
            request,
            SaveKakaoStudyRequest.model_validate(
                {**_identity(request), "command": body, "idempotency_key": idempotency_key}
            ),
        ),
    )
    response.headers.update(
        {"Cache-Control": "no-store", "ETag": etag(value.study.resource_version)}
    )
    return one(request, value)


@router.patch(
    "/studies/{study_id}",
    operation_id="kakao_study_revise",
    response_model=SingleResponse[KakaoStudyMutation],
    dependencies=[Depends(EDIT)],
)
def revise_study(
    request: Request,
    response: Response,
    study_id: StudyId,
    body: KakaoStudyRevise,
    authentication: Auth,
    expected: ExpectedVersion,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[KakaoStudyMutation]:
    if body.study_id != study_id or body.expected_resource_version != expected:
        raise ApiError(
            412,
            "KAKAO_ARCHIVE_PRECONDITION_FAILED",
            "Study version differs",
            "Select the current study revision.",
        )
    value = cast(
        KakaoStudyMutation,
        _call(
            request,
            SaveKakaoStudyRequest.model_validate(
                {**_identity(request), "command": body, "idempotency_key": idempotency_key}
            ),
        ),
    )
    response.headers.update(
        {"Cache-Control": "no-store", "ETag": etag(value.study.resource_version)}
    )
    return one(request, value)


@router.get(
    "/studies",
    operation_id="kakao_study_list",
    response_model=SingleResponse[KakaoStudyPage],
    dependencies=[Depends(READ)],
)
def list_studies(
    request: Request,
    response: Response,
    source_binding_id: BindingId,
    authentication: Auth,
    limit: int = Query(default=30, ge=1, le=100),
    cursor: str | None = Query(default=None, pattern=r"^kakaostudy_[0-9a-f]{32}$"),
) -> SingleResponse[KakaoStudyPage]:
    value = cast(
        KakaoStudyPage,
        _call(
            request,
            ListKakaoStudiesRequest.model_validate(
                {
                    **_identity(request),
                    "source_binding_id": source_binding_id,
                    "limit": limit,
                    "cursor": cursor,
                }
            ),
        ),
    )
    response.headers["Cache-Control"] = "no-store"
    return one(request, value)


@router.get(
    "/studies/{study_id}/revisions/{revision_id}",
    operation_id="kakao_study_read",
    response_model=SingleResponse[KakaoStudyView],
    dependencies=[Depends(READ)],
)
def read_study(
    request: Request,
    response: Response,
    study_id: StudyId,
    revision_id: StudyRevisionId,
    source_binding_id: BindingId,
    authentication: Auth,
) -> SingleResponse[KakaoStudyView]:
    value = cast(
        KakaoStudyView,
        _call(
            request,
            ReadKakaoStudyRequest.model_validate(
                {
                    **_identity(request),
                    "source_binding_id": source_binding_id,
                    "study_id": study_id,
                    "study_revision_id": revision_id,
                }
            ),
        ),
    )
    response.headers.update(
        {"Cache-Control": "no-store", "ETag": etag(value.study.resource_version)}
    )
    return one(request, value)


@router.post(
    "/study-exports",
    operation_id="kakao_study_export_create",
    status_code=202,
    response_model=SingleResponse[KakaoStudyExportMutation],
    dependencies=[Depends(EXPORT)],
)
def create_study_export(
    request: Request,
    response: Response,
    body: KakaoStudyExportCreate,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[KakaoStudyExportMutation]:
    value = cast(
        KakaoStudyExportMutation,
        _call(
            request,
            CreateKakaoStudyExportRequest.model_validate(
                {
                    **_identity(request),
                    "command": body,
                    "idempotency_key": idempotency_key,
                }
            ),
        ),
    )
    response.headers["Cache-Control"] = "no-store"
    return one(request, value)


@router.get(
    "/study-exports/{export_id}",
    operation_id="kakao_study_export_read",
    response_model=SingleResponse[KakaoStudyExport],
    dependencies=[Depends(READ)],
)
def read_study_export(
    request: Request,
    response: Response,
    export_id: ExportId,
    source_binding_id: BindingId,
    authentication: Auth,
) -> SingleResponse[KakaoStudyExport]:
    value = cast(
        KakaoStudyExport,
        _call(
            request,
            ReadKakaoStudyExportRequest.model_validate(
                {
                    **_identity(request),
                    "source_binding_id": source_binding_id,
                    "export_id": export_id,
                }
            ),
        ),
    )
    response.headers["Cache-Control"] = "no-store"
    return one(request, value)


@router.get(
    "/question-packets/{packet_id}/revisions/{revision_id}/students/{student_id}/study-selection",
    operation_id="kakao_study_selection",
    response_model=SingleResponse[KakaoStudyCreate],
    dependencies=[Depends(READ)],
)
def read_study_selection(
    request: Request,
    response: Response,
    packet_id: PacketId,
    revision_id: PacketRevisionId,
    student_id: StudentId,
    source_binding_id: BindingId,
    authentication: Auth,
) -> SingleResponse[KakaoStudyCreate]:
    value = cast(
        KakaoStudyCreate,
        _call(
            request,
            ReadKakaoStudySelectionRequest.model_validate(
                {
                    **_identity(request),
                    "source_binding_id": source_binding_id,
                    "packet_id": packet_id,
                    "packet_revision_id": revision_id,
                    "student_id": student_id,
                }
            ),
        ),
    )
    response.headers["Cache-Control"] = "no-store"
    return one(request, value)
