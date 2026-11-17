"""Optional retained input adapters; fixed paths and UIDs never come from requests."""

from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import Engine

if TYPE_CHECKING:
    from .kakao_capture_intake_service import KakaoCaptureIntakeService
    from .kakao_manual_composition import ManualRuntimeComposition


def build_kakao_capture_intake(
    engine: Engine, manual: "ManualRuntimeComposition | None"
) -> "KakaoCaptureIntakeService | None":
    if manual is None:
        return None
    import grp
    import pwd

    from eom_orchestrator.kakao_download_inputs import (
        list_kakao_download_ids,
        read_kakao_download_metadata,
        read_received_kakao_download,
    )

    from .artifacts import CatalogArtifactService
    from .kakao_capture_intake_service import KakaoCaptureIntakeService
    from .kakao_room_intake import KakaoRoomIntakeService
    from .kakao_room_service import KakaoRoomService

    root = Path("/var/lib/eom-kakao/downloads")
    worker_uid = pwd.getpwnam("eom-kakao").pw_uid
    control_gid = grp.getgrnam("eom-kakao-control").gr_gid
    if worker_uid == 0:
        raise ValueError("KAKAO_MANUAL_CONFIGURATION_INVALID")
    artifacts = CatalogArtifactService(engine)
    return KakaoCaptureIntakeService(
        engine,
        intake=KakaoRoomIntakeService(
            engine,
            artifacts=artifacts,
            rooms=KakaoRoomService(engine),
            read_download=lambda fence, capture: read_received_kakao_download(
                root=root,
                fence=fence,
                capture_id=capture,
                worker_uid=worker_uid,
                control_gid=control_gid,
            ),
        ),
        read_metadata=lambda fence, capture: read_kakao_download_metadata(
            root=root,
            fence=fence,
            capture_id=capture,
            worker_uid=worker_uid,
            control_gid=control_gid,
        ),
        list_capture_ids=lambda fence: list_kakao_download_ids(
            root=root, fence=fence, worker_uid=worker_uid, control_gid=control_gid
        ),
    )
