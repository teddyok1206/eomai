"""Transactional idempotency claims with bounded, hashed persisted state."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

from eom_identity_service.models import ApiIdempotencyRecord
from eom_operator_identity.identifiers import new_idempotency_record_id
from eom_orchestrator.database import build_session_factory, transaction
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError

from eom_api.errors import ApiError

ResultT = TypeVar("ResultT")


@dataclass(frozen=True)
class IdempotencyClaim:
    record_id: str
    replay_body: dict[str, Any] | None = None
    replay_status: int | None = None

    @property
    def replayed(self) -> bool:
        return self.replay_body is not None


class IdempotencyService:
    def __init__(
        self,
        engine: Engine,
        hash_key: bytes,
        *,
        lease_seconds: int = 60,
        retention_seconds: int = 86_400,
        response_limit_bytes: int = 65_536,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self._key = hash_key
        self._lease_seconds = lease_seconds
        self._retention_seconds = retention_seconds
        self._response_limit = response_limit_bytes

    def request_hash(
        self,
        *,
        method: str,
        operation_id: str,
        path_parameters: dict[str, str],
        body: dict[str, Any] | None,
        operator_id: str,
    ) -> str:
        payload = {
            "method": method,
            "operation_id": operation_id,
            "path_parameters": path_parameters,
            "body": body,
            "operator_id": operator_id,
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    def claim(
        self,
        *,
        operator_id: str,
        endpoint_key: str,
        raw_key: str,
        request_sha256: str,
        lease_owner: str,
        now: datetime | None = None,
    ) -> IdempotencyClaim:
        timestamp = now or datetime.now(UTC)
        key_hash = self._key_hash(raw_key)
        record_id = new_idempotency_record_id()
        try:
            with transaction(self.sessions) as session:
                session.add(
                    ApiIdempotencyRecord(
                        api_idempotency_record_id=record_id,
                        operator_id=operator_id,
                        endpoint_key=endpoint_key,
                        idempotency_key_hash=key_hash,
                        request_sha256=request_sha256,
                        state="PROCESSING",
                        lease_owner=lease_owner,
                        lease_expires_at=timestamp + timedelta(seconds=self._lease_seconds),
                        created_at=timestamp,
                        updated_at=timestamp,
                        expires_at=timestamp + timedelta(seconds=self._retention_seconds),
                    )
                )
                session.flush()
            return IdempotencyClaim(record_id)
        except IntegrityError:
            pass
        with transaction(self.sessions) as session:
            record = session.scalar(
                select(ApiIdempotencyRecord)
                .where(
                    ApiIdempotencyRecord.operator_id == operator_id,
                    ApiIdempotencyRecord.endpoint_key == endpoint_key,
                    ApiIdempotencyRecord.idempotency_key_hash == key_hash,
                )
                .with_for_update()
            )
            if record is None:
                raise ApiError(
                    409,
                    "API_IDEMPOTENCY_IN_PROGRESS",
                    "Idempotent request is being claimed",
                    "Retry the request after a short delay.",
                    {"Retry-After": "1"},
                )
            if not hmac.compare_digest(record.request_sha256, request_sha256):
                raise ApiError(
                    409,
                    "API_IDEMPOTENCY_CONFLICT",
                    "Idempotency conflict",
                    "The idempotency key was already used for a different request.",
                )
            if record.state == "COMPLETED" and record.response_body is not None:
                return IdempotencyClaim(
                    record.api_idempotency_record_id,
                    replay_body=record.response_body,
                    replay_status=record.response_status,
                )
            if record.state == "PROCESSING" and (
                record.lease_expires_at is None or record.lease_expires_at > timestamp
            ):
                retry = max(
                    1,
                    int((record.lease_expires_at - timestamp).total_seconds())
                    if record.lease_expires_at
                    else 1,
                )
                raise ApiError(
                    409,
                    "API_IDEMPOTENCY_IN_PROGRESS",
                    "Idempotent request is in progress",
                    "The original request has not finished.",
                    {"Retry-After": str(retry)},
                )
            record.state = "PROCESSING"
            record.lease_owner = lease_owner
            record.lease_expires_at = timestamp + timedelta(seconds=self._lease_seconds)
            record.updated_at = timestamp
            return IdempotencyClaim(record.api_idempotency_record_id)

    def complete(
        self,
        claim: IdempotencyClaim,
        *,
        status: int,
        body: dict[str, Any],
        resource_type: str,
        resource_id: str,
    ) -> None:
        encoded = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
        if len(encoded) > self._response_limit:
            raise ApiError(
                500,
                "API_INTERNAL_ERROR",
                "Command response is too large",
                "The command result cannot be stored safely.",
            )
        now = datetime.now(UTC)
        with transaction(self.sessions) as session:
            record = session.get(ApiIdempotencyRecord, claim.record_id, with_for_update=True)
            if record is None:
                raise RuntimeError("idempotency claim disappeared")
            record.state = "COMPLETED"
            record.response_status = status
            record.response_body = body
            record.resource_type = resource_type
            record.resource_id = resource_id
            record.lease_owner = None
            record.lease_expires_at = None
            record.updated_at = now
            record.completed_at = now

    def fail_final(self, claim: IdempotencyClaim, error_code: str) -> None:
        now = datetime.now(UTC)
        with transaction(self.sessions) as session:
            record = session.get(ApiIdempotencyRecord, claim.record_id, with_for_update=True)
            if record is None:
                return
            record.state = "FAILED_FINAL"
            record.error_code = error_code
            record.lease_owner = None
            record.lease_expires_at = None
            record.updated_at = now
            record.completed_at = now

    def _key_hash(self, raw_key: str) -> str:
        return "sha256:" + hmac.new(self._key, raw_key.encode("ascii"), hashlib.sha256).hexdigest()

    def sensitive_value_hash(self, value: str) -> str:
        return "sha256:" + hmac.new(self._key, value.encode("utf-8"), hashlib.sha256).hexdigest()
