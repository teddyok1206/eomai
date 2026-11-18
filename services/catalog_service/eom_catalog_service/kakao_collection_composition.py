"""Feature-off by default; only the existing installed Catalog owner may enable AUTO."""

import grp
import pwd
import re
from collections.abc import Mapping
from pathlib import Path

from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.kakao_collection_browser_runtime import FixedKakaoCollectionBrowserRuntime
from eom_orchestrator.settings import Settings
from sqlalchemy import Engine

from .kakao_capability_service import KakaoCapabilityService
from .kakao_collection_attempt_service import KakaoCollectionAttemptService
from .kakao_collection_browser_service import KakaoCollectionBrowserService
from .kakao_collection_continuation import KakaoCollectionContinuation
from .kakao_collection_service import KakaoCollectionService
from .kakao_manual_composition import ManualRuntimeComposition
from .kakao_one_room_collection import KakaoOneRoomCollection


def build_kakao_collection_continuation(
    engine: Engine,
    environment: Mapping[str, str],
    *,
    manual: ManualRuntimeComposition | None,
    attempts: KakaoCollectionAttemptService | None,
) -> KakaoCollectionContinuation | None:
    mode = environment.get("EOM_KAKAO_COLLECTION_MODE", "DISABLED")
    if mode == "DISABLED":
        return None
    commit = environment.get("EOM_RUNTIME_SOURCE_COMMIT", "")
    if (
        mode != "ONE_ROOM"
        or attempts is None
        or manual is None
        or manual.fixed_runtime is None
        or attempts.profile_id != manual.fixed_runtime.profile.profile_id
        or re.fullmatch(r"[0-9a-f]{40}", commit) is None
    ):
        raise ValueError("KAKAO_ARCHIVE_COLLECTION_RUNTIME_CONFIGURATION_INVALID")
    runtime = manual.fixed_runtime
    uid = pwd.getpwnam("eom-kakao").pw_uid
    gid = grp.getgrnam("eom-kakao-control").gr_gid
    if uid <= 0 or gid <= 0:
        raise ValueError("KAKAO_ARCHIVE_COLLECTION_RUNTIME_CONFIGURATION_INVALID")
    collections = KakaoCollectionService(
        engine,
        capabilities=KakaoCapabilityService(
            engine,
            artifacts=attempts.artifacts,
            adapter_release_sha256=attempts.adapter_sha256,
        ),
    )
    return KakaoCollectionContinuation(
        KakaoOneRoomCollection(
            engine=engine,
            collections=collections,
            browsers=KakaoCollectionBrowserService(
                engine,
                profile_id=attempts.profile_id,
                adapter_release_sha256=attempts.adapter_sha256,
            ),
            attempts=attempts,
            runtime=FixedKakaoCollectionBrowserRuntime(runtime.browser, runtime.gateway),
            observe_profile=manual.application.observe_profile,
            result_publisher=ControlFileSetPublisher(
                engine,
                Settings(
                    staging_root=attempts.artifacts.settings.staging_root,
                    nas_artifact_root=attempts.artifacts.settings.nas_artifact_root,
                ),
            ),
            source_commit=commit,
            output_root=Path("/var/lib/eom-kakao/downloads"),
            worker_uid=uid,
            control_gid=gid,
        )
    )
