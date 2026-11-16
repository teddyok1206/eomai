"""Short private-archive command transactions; never hold these locks during I/O."""

from __future__ import annotations

import hashlib
import json
import re

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError


def validate_kakao_idempotency_key(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[!-~]{16,128}", value) is None:
        raise KakaoArchiveError("KAKAO_ARCHIVE_REQUEST_INVALID")
    return value


def kakao_command_sha256(command: BaseModel) -> str:
    encoded = json.dumps(
        command.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def lock_kakao_intent(session: Session, owner: str, scope: str, key: str) -> None:
    # Preserve the initial binding lock namespace; distinct domain scopes partition it.
    digest = hashlib.sha256(f"kakao-binding\0{owner}\0{scope}\0{key}".encode()).digest()
    lock_key = int.from_bytes(digest[:8], "big", signed=True)
    session.execute(select(func.pg_advisory_xact_lock(lock_key)))
