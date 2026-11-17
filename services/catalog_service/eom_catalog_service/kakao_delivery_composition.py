"""Always compose packet history; only exact installed pins enable the offline renderer."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from sqlalchemy import Engine

from .artifacts import CatalogArtifactService
from .kakao_archive_authorization import KakaoArchiveError
from .kakao_delivery_application import KakaoDeliveryApplication
from .kakao_packet_service import KakaoPacketService
from .kakao_question_service import KakaoQuestionService
from .kakao_source_service import KakaoSourceService
from .kakao_study_service import KakaoStudyService

if TYPE_CHECKING:
    from .kakao_concept_task_service import KakaoConceptTaskService
    from .kakao_pdf_coordinator import KakaoPdfCoordinator

PDF_INPUT_ROOT = Path("/var/lib/eom-catalog-api/staging/kakao-pdf-inputs")
PDF_FONT = Path("/usr/local/share/fonts/eom/NotoSansCJKkr-Regular.otf")


@dataclass(frozen=True, slots=True)
class KakaoDeliveryComposition:
    application: KakaoDeliveryApplication
    coordinator: KakaoPdfCoordinator | None


def build_kakao_delivery_application(
    engine: Engine,
    questions: KakaoQuestionService,
    environment: Mapping[str, str],
    *,
    concepts: KakaoConceptTaskService | None = None,
) -> KakaoDeliveryComposition:
    artifacts = CatalogArtifactService(engine)

    def no_capture(*_args: object) -> None:
        raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_AUTHORITY_REQUIRED")

    sources = KakaoSourceService(engine, artifacts=artifacts, authorize_capture=no_capture)
    packets = KakaoPacketService(engine, artifacts=artifacts, questions=questions, sources=sources)
    studies = KakaoStudyService(
        engine, artifacts=artifacts, packets=packets, sources=sources, concepts=concepts
    )
    mode = environment.get("EOM_KAKAO_PDF_MODE", "DISABLED")
    if mode == "DISABLED":
        return KakaoDeliveryComposition(KakaoDeliveryApplication(packets, studies=studies), None)
    keys = (
        "EOM_KAKAO_PDF_RELEASE_SHA256",
        "EOM_KAKAO_PDF_TEMPLATE_SHA256",
        "EOM_KAKAO_PDF_FONT_SHA256",
    )
    hashes = tuple(environment.get(key, "") for key in keys)
    size = environment.get("EOM_KAKAO_PDF_FONT_SIZE", "")
    policy = environment.get("EOM_KAKAO_PDF_LAYOUT_POLICY", "student-question-a4/1.0")
    if (
        mode != "ENABLED"
        or any(re.fullmatch(r"sha256:[0-9a-f]{64}", pin) is None for pin in hashes)
        or re.fullmatch(r"[1-9][0-9]{0,7}", size) is None
        or policy not in {"student-question-a4/1.0", "student-study-a4/1.0"}
    ):
        raise ValueError("KAKAO_PDF_CONFIGURATION_INVALID")
    import grp
    import pwd

    from eom_catalog_contracts.kakao_export_store import ExportLayoutPolicy, KakaoExportProfile
    from eom_kakao_archive_contracts import LocalMember
    from eom_orchestrator.kakao_pdf_runtime import KAKAO_WORKSPACE_ROOT, FixedKakaoPdfLauncher

    from .kakao_export_service import KakaoExportService
    from .kakao_pdf_coordinator import KakaoPdfCoordinator
    from .kakao_pdf_delivery import KakaoPdfDelivery

    profile = KakaoExportProfile(
        renderer_release_sha256=hashes[0],
        font_sha256=hashes[2],
        font_size_bytes=int(size),
        layout_policy=cast(ExportLayoutPolicy, policy),
    )
    exports = KakaoExportService(
        engine,
        artifacts=artifacts,
        packets=packets,
        sources=sources,
        profile=profile,
        studies=studies,
    )
    runtime = FixedKakaoPdfLauncher(hashes[1], hashes[0])
    worker_uid = pwd.getpwnam("eom-kakao-render").pw_uid
    if worker_uid in {0, os.geteuid()}:
        raise ValueError("KAKAO_PDF_CONFIGURATION_INVALID")
    delivery = KakaoPdfDelivery(
        exports,
        artifacts,
        PDF_INPUT_ROOT,
        KAKAO_WORKSPACE_ROOT,
        PDF_FONT,
        LocalMember(
            relative_path="font.otf", sha256=hashes[2], size_bytes=int(size), media_type="font/otf"
        ),
        worker_uid,
        grp.getgrnam("eom-kakao-render").gr_gid,
        runtime,
        runtime.close_finished,
        studies,
    )
    coordinator = KakaoPdfCoordinator(delivery)
    return KakaoDeliveryComposition(
        KakaoDeliveryApplication(packets, exports, coordinator.submit, studies), coordinator
    )
