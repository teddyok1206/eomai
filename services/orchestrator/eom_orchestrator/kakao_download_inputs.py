"""Resolve one retained MANUAL download, not source authority or browser control.

The trusted owner supplies the installed root/UID/GID and exact run fence. Bytes
are materialized once at this input boundary; nothing is published or changed.
"""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

from eom_kakao_archive_contracts.kakao_remote import ProfileFence
from eom_kakao_archive_contracts.manual_download import ManualDownloadResult, ManualDownloadStart
from eom_kakao_archive_contracts.manual_observation import (
    MAX_OBSERVATION_BYTES,
    ManualPageObservation,
)
from eom_kakao_archive_contracts.render import canonical_bytes, sha256

from .kakao_runtime_os import KakaoRuntimeOsError, protected_directory, read_protected

_CAPTURE_ID = re.compile(r"kakaodownload_[0-9a-f]{32}\Z")


class KakaoDownloadInputError(ValueError):
    """Stable technical code only, never the private filename or receipt payload."""


@dataclass(frozen=True, slots=True)
class ReceivedKakaoDownload:
    receipt: ManualDownloadResult = field(repr=False)
    payload: bytes = field(repr=False)
    observation: ManualPageObservation | None = field(default=None, repr=False)
    receipt_bytes: bytes = field(default=b"", repr=False)
    observation_bytes: bytes | None = field(default=None, repr=False)


def read_received_kakao_download(
    *,
    root: Path,
    fence: ProfileFence,
    capture_id: str,
    worker_uid: int,
    control_gid: int,
) -> ReceivedKakaoDownload:
    """O(bytes), bounded32MiB; exact ID lookup, no directory scan or network call.

    This accepts only a local completed transfer. Current operator/source access,
    room/message association and canonical Artifact admission remain owner duties.
    A stopped MANUAL browser does not invalidate already completed transfer bytes.
    """
    if (
        not isinstance(capture_id, str)
        or _CAPTURE_ID.fullmatch(capture_id) is None
        or type(worker_uid) is not int
        or type(control_gid) is not int
        or worker_uid < 0
        or control_gid < 0
    ):
        raise KakaoDownloadInputError("KAKAO_DOWNLOAD_INPUT_INVALID")
    try:
        fence = ProfileFence.model_validate(fence.model_dump(mode="json"))
    except ValueError:
        raise KakaoDownloadInputError("KAKAO_DOWNLOAD_INPUT_INVALID") from None
    if fence.mode != "MANUAL":
        raise KakaoDownloadInputError("KAKAO_DOWNLOAD_INPUT_INVALID")
    owners = frozenset({0, worker_uid})

    def directory(path: Path, mode: int) -> None:
        with protected_directory(path, owners=owners) as descriptor:
            info = os.fstat(descriptor)
            if (
                info.st_uid != worker_uid
                or info.st_gid != control_gid
                or stat.S_IMODE(info.st_mode) != mode
            ):
                raise KakaoDownloadInputError("KAKAO_DOWNLOAD_STAGING_UNSAFE")

    def read(path: Path, maximum: int) -> bytes:
        return read_protected(
            path,
            uid=worker_uid,
            gid=control_gid,
            mode=0o640,
            maximum=maximum,
            owners=owners,
        )

    try:
        directory(root, 0o2750)
        run = root / fence.browser_run_id
        directory(run, 0o750)
        if read(run / "run.json", 4096) != canonical_bytes(fence.model_dump(mode="json")):
            raise KakaoDownloadInputError("KAKAO_DOWNLOAD_FENCE_STALE")
        capture = run / capture_id
        directory(capture, 0o750)
        try:
            started = ManualDownloadStart.model_validate_json(read(capture / "started.json", 16384))
            result_raw = read(capture / "result.json", 16384)
            result = ManualDownloadResult.model_validate_json(result_raw)
        except ValueError as error:
            if isinstance(error, KakaoRuntimeOsError):
                raise
            raise KakaoDownloadInputError("KAKAO_DOWNLOAD_RECEIPT_INVALID") from None
        if started.capture_id != capture_id or (
            started.profile_id,
            started.browser_run_id,
            started.fence_epoch,
        ) != (fence.profile_id, fence.browser_run_id, fence.fence_epoch):
            raise KakaoDownloadInputError("KAKAO_DOWNLOAD_FENCE_STALE")
        initial = result.model_dump(include=set(ManualDownloadStart.model_fields))
        initial["phase"] = "STARTED"
        if initial != started.model_dump():
            raise KakaoDownloadInputError("KAKAO_DOWNLOAD_RECEIPT_INVALID")
        if result.phase != "RECEIVED" or result.member is None:
            raise KakaoDownloadInputError("KAKAO_DOWNLOAD_NOT_RECEIVED")
        raw = read(capture / result.member.relative_path, result.member.size_bytes)
        if len(raw) != result.member.size_bytes or sha256(raw) != result.member.sha256:
            raise KakaoDownloadInputError("KAKAO_DOWNLOAD_MEMBER_HASH_MISMATCH")
        try:
            read_observation = read(capture / "page-observation.json", MAX_OBSERVATION_BYTES)
        except FileNotFoundError:
            # Historical captures have no document evidence. This is UNKNOWN,
            # not proof of a room identity or a missing/absent photo attachment.
            observation = None
            observed_raw = None
        else:
            observed_raw = read_observation
            try:
                observation = ManualPageObservation.model_validate_json(read_observation)
            except ValueError as error:
                if isinstance(error, KakaoRuntimeOsError):
                    raise
                raise KakaoDownloadInputError("KAKAO_DOWNLOAD_OBSERVATION_INVALID") from None
            shared = (
                "capture_id",
                "profile_id",
                "browser_run_id",
                "fence_epoch",
                "page_instance_id",
            )
            if (
                any(getattr(observation, name) != getattr(started, name) for name in shared)
                or not started.started_at <= observation.observed_at <= result.completed_at
            ):
                raise KakaoDownloadInputError("KAKAO_DOWNLOAD_OBSERVATION_STALE")
        return ReceivedKakaoDownload(result, raw, observation, result_raw, observed_raw)
    except FileNotFoundError:
        raise KakaoDownloadInputError("KAKAO_DOWNLOAD_INPUT_MISSING") from None
    except (KakaoRuntimeOsError, OSError):
        raise KakaoDownloadInputError("KAKAO_DOWNLOAD_STAGING_UNSAFE") from None
