"""Synthetic remote intent values; no real account or browser identity."""

from datetime import UTC, datetime, timedelta

from eom_catalog_contracts.kakao_manual import KakaoManualSession, KakaoManualStart

NOW = datetime(2026, 11, 16, 7, 0, tzinfo=UTC)
BINDING = "kakaobinding_" + "1" * 32
LEASE = "kakaoremotelease_" + "2" * 32
KEY = "kakao-manual-command-0001"
IDENTITY = {
    "actor_id": "operator_" + "3" * 32,
    "session_id": "apisession_" + "4" * 32,
    "request_id": "webreq_manual_fixture",
    "authentication_time": NOW,
}


def start():
    return KakaoManualStart(source_binding_id=BINDING)


def session(phase="PREPARING", version=1, grant=0):
    return KakaoManualSession(
        lease_id=LEASE,
        source_binding_id=BINDING,
        phase=phase,
        resource_version=version,
        grant_revision=grant,
        created_at=NOW,
        expires_at=NOW + timedelta(seconds=30) if grant else None,
        absolute_expires_at=NOW + timedelta(minutes=20),
        ready=phase == "ACTIVE",
        last_error=None,
        ended_reason="USER_ENDED" if phase == "STOPPING" else None,
        closed_at=None,
    )
