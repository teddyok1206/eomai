"""Bounded local C1 output reader; no browser, source authority, DB or NAS writes."""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

from eom_kakao_archive_contracts.capture import CsvMember
from eom_kakao_archive_contracts.render import LocalMember, sha256

from .kakao_runtime_os import KakaoRuntimeOsError, protected_directory, read_protected


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
            directory(self.root, os.geteuid(), 0o2750)
            parent = self.root / self.attempt_id
            directory(parent, self.worker_uid, 0o750)
            for component in member.relative_path.split("/")[:-1]:
                parent /= component
                directory(parent, self.worker_uid, 0o750)
            raw = read_protected(
                self.root / self.attempt_id / member.relative_path,
                uid=self.worker_uid,
                gid=self.control_gid,
                mode=0o640,
                maximum=member.size_bytes,
                owners=owners,
            )
        except FileNotFoundError:
            raise KakaoCaptureInputError("KAKAO_CAPTURE_INPUT_MISSING") from None
        except (KakaoRuntimeOsError, OSError):
            raise KakaoCaptureInputError("KAKAO_CAPTURE_STAGING_UNSAFE") from None
        if len(raw) != member.size_bytes or sha256(raw) != member.sha256:
            raise KakaoCaptureInputError("KAKAO_CAPTURE_MEMBER_HASH_MISMATCH")
        return raw
