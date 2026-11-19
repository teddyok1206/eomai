"""Bounded local C1 output reader; no browser, source authority, DB or NAS writes."""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

from eom_kakao_archive_contracts.capture import ROOM_AUTH_REFUSAL_NAME, CsvMember
from eom_kakao_archive_contracts.open_room_download import (
    MAX_OPEN_ROOM_RECEIPT_BYTES,
    OPEN_ROOM_RECEIPT_NAME,
    InvalidOpenRoomDownloadReceipt,
    OpenRoomDownloadReceipt,
    RoomPhotoReceipt,
)
from eom_kakao_archive_contracts.render import LocalMember, sha256

from .kakao_runtime_os import KakaoRuntimeOsError, protected_directory, read_protected

_INSTALLED_BROWSER_DOWNLOADS = Path("/var/lib/eom-kakao/downloads")


class KakaoCaptureInputError(ValueError):
    """Stable technical code only, never an untrusted path or file content."""


@dataclass(frozen=True, slots=True)
class KakaoCaptureOutputReader:
    # Trusted installed composition chooses this location; it is not identity or
    # public input. Accepted report pointers and current authorization stay upstream.
    root: Path = field(repr=False)
    attempt_id: str
    worker_uid: int
    control_gid: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.root, Path)
            or not self.root.is_absolute()
            or ".." in self.root.parts
            or not isinstance(self.attempt_id, str)
            or re.fullmatch(r"kakaoattempt_[0-9a-f]{32}", self.attempt_id) is None
            or type(self.worker_uid) is not int
            or type(self.control_gid) is not int
            or self.worker_uid <= 0
            or self.control_gid < 0
        ):
            raise KakaoCaptureInputError("KAKAO_CAPTURE_INPUT_INVALID")

    def __call__(self, member: LocalMember | CsvMember) -> bytes:
        try:
            # Frozen models can still be made with model_copy/model_construct;
            # validate before deriving a filesystem path or read budget.
            if isinstance(member, CsvMember):
                member = CsvMember.model_validate(member.model_dump(mode="json"))
            elif isinstance(member, LocalMember):
                member = LocalMember.model_validate(member.model_dump(mode="json"))
            else:
                raise ValueError
            if not member.relative_path.startswith("outputs/") or member.media_type not in {
                "application/json",
                "text/csv",
                "image/png",
                "image/jpeg",
                "image/webp",
            }:
                raise ValueError
        except ValueError:
            raise KakaoCaptureInputError("KAKAO_CAPTURE_MEMBER_INVALID") from None

        raw = self._read(member.relative_path, maximum=member.size_bytes)
        if len(raw) != member.size_bytes or sha256(raw) != member.sha256:
            raise KakaoCaptureInputError("KAKAO_CAPTURE_MEMBER_HASH_MISMATCH")
        return raw

    def read_result(self) -> bytes:
        """Fixed bounded proposal only; the accepted command's owner validates C1."""
        return self._read("outputs/result.json", maximum=32768)

    def read_room_auth_refusal(self) -> bytes:
        """Fixed C1 failure proposal, distinct from an ordinary staged result."""
        return self._read(f"outputs/{ROOM_AUTH_REFUSAL_NAME}", maximum=32768)

    def open_room_download(self) -> OpenRoomDownloadReceipt:
        raw = self._read(f"outputs/{OPEN_ROOM_RECEIPT_NAME}", maximum=MAX_OPEN_ROOM_RECEIPT_BYTES)
        try:
            return OpenRoomDownloadReceipt.decode(raw)
        except InvalidOpenRoomDownloadReceipt:
            raise KakaoCaptureInputError("KAKAO_CAPTURE_RECEIPT_INVALID") from None

    def read_open_room_photo(self, photo: RoomPhotoReceipt) -> bytes:
        if (
            re.fullmatch(r"outputs/photo-[1-6]\.bin", photo.relative_path) is None
            or type(photo.size_bytes) is not int
            or not 0 < photo.size_bytes <= 32 * 1024 * 1024
        ):
            raise KakaoCaptureInputError("KAKAO_CAPTURE_MEMBER_INVALID")
        return self._read(photo.relative_path, maximum=photo.size_bytes)

    def _read(self, relative_path: str, *, maximum: int) -> bytes:
        owners = frozenset({0, os.geteuid(), self.worker_uid})

        def directory(path: Path, uid: int, mode: int) -> None:
            with protected_directory(path, owners=owners) as descriptor:
                info = os.fstat(descriptor)
                if (
                    info.st_uid != uid
                    or info.st_gid != self.control_gid
                    or stat.S_IMODE(info.st_mode) != mode
                ):
                    raise KakaoCaptureInputError("KAKAO_CAPTURE_STAGING_UNSAFE")

        try:
            root_owner = (
                self.worker_uid if self.root == _INSTALLED_BROWSER_DOWNLOADS else os.geteuid()
            )
            directory(self.root, root_owner, 0o2750)
            parent = self.root / self.attempt_id
            directory(parent, self.worker_uid, 0o750)
            for component in relative_path.split("/")[:-1]:
                parent /= component
                directory(parent, self.worker_uid, 0o750)
            raw = read_protected(
                self.root / self.attempt_id / relative_path,
                uid=self.worker_uid,
                gid=self.control_gid,
                mode=0o640,
                maximum=maximum,
                owners=owners,
            )
        except FileNotFoundError:
            raise KakaoCaptureInputError("KAKAO_CAPTURE_INPUT_MISSING") from None
        except (KakaoRuntimeOsError, OSError):
            raise KakaoCaptureInputError("KAKAO_CAPTURE_STAGING_UNSAFE") from None
        return raw
