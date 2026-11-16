"""Bounded lifetime of one private gateway, independent of browser/profile control.

An authenticated owner channel supplies grants. This helper cannot authorize or renew
itself. The injected stop adapter must stop the entire fixed gateway execution and its
connected children, not merely unlink its listening socket. Poll until STOPPED; a failed
stop leaves admission closed and remains retryable. No network/OS service is installed here.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime, timedelta
from enum import StrEnum
from threading import Lock

from eom_kakao_archive_contracts.kakao_remote import GatewayLeaseGrant, GatewayRevocation


class GatewayLifetimeState(StrEnum):
    ACTIVE = "ACTIVE"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"


def _clock(now: datetime, monotonic_now: float) -> None:
    if (
        now.tzinfo is None
        or now.utcoffset() != timedelta(0)
        or isinstance(monotonic_now, bool)
        or not math.isfinite(monotonic_now)
        or monotonic_now < 0
    ):
        raise ValueError("KAKAO_GATEWAY_CLOCK_INVALID")


def _identity(grant: GatewayLeaseGrant) -> tuple[str, str, str, int, int]:
    return (
        grant.lease_id,
        grant.source_binding_id,
        grant.profile_id,
        grant.fence_epoch,
        grant.gateway_epoch,
    )


class RemoteGatewayLifetime:
    """One lease/epoch, O(1) checks and lock-serialized renew/revoke/expiry decisions."""

    def __init__(
        self,
        grant: GatewayLeaseGrant,
        *,
        now: datetime,
        monotonic_now: float,
        stop_gateway: Callable[[GatewayLeaseGrant], bool],
    ) -> None:
        _clock(now, monotonic_now)
        if not grant.authorized_at <= now < grant.expires_at:
            raise ValueError("KAKAO_GATEWAY_GRANT_EXPIRED")
        self._grant = grant
        self._stop_gateway = stop_gateway
        self._state = GatewayLifetimeState.ACTIVE
        self._deadline = monotonic_now + (grant.expires_at - now).total_seconds()
        self._absolute_deadline = monotonic_now + (grant.absolute_expires_at - now).total_seconds()
        self._last_monotonic = monotonic_now
        self._lock = Lock()
        self._last_error_code: str | None = None

    @property
    def state(self) -> GatewayLifetimeState:
        with self._lock:
            return self._state

    @property
    def last_error_code(self) -> str | None:
        with self._lock:
            return self._last_error_code

    def _close(self) -> None:
        if self._state == GatewayLifetimeState.STOPPED:
            return
        # Close admission before invoking the adapter, even if its stop attempt fails.
        self._state = GatewayLifetimeState.STOPPING
        try:
            stopped = self._stop_gateway(self._grant) is True
        except Exception:
            stopped = False
        if stopped:
            self._state = GatewayLifetimeState.STOPPED
            self._last_error_code = None
        else:
            self._last_error_code = "KAKAO_GATEWAY_STOP_UNCONFIRMED"

    def _observe(self, now: datetime, monotonic_now: float) -> None:
        try:
            _clock(now, monotonic_now)
        except (TypeError, ValueError, OverflowError):
            self._close()
            raise ValueError("KAKAO_GATEWAY_CLOCK_INVALID") from None
        if monotonic_now < self._last_monotonic:
            self._close()
            raise ValueError("KAKAO_GATEWAY_MONOTONIC_REGRESSED")
        self._last_monotonic = monotonic_now
        if (
            self._state == GatewayLifetimeState.STOPPING
            or now >= self._grant.expires_at
            or monotonic_now >= min(self._deadline, self._absolute_deadline)
        ):
            self._close()

    def poll(self, *, now: datetime, monotonic_now: float) -> GatewayLifetimeState:
        with self._lock:
            self._observe(now, monotonic_now)
            return self._state

    def accept_renewal(
        self,
        grant: GatewayLeaseGrant,
        *,
        now: datetime,
        monotonic_now: float,
    ) -> bool:
        """Exact replay does not move deadlines. An ended epoch never resurrects."""
        with self._lock:
            self._observe(now, monotonic_now)
            if self._state != GatewayLifetimeState.ACTIVE:
                raise ValueError("KAKAO_GATEWAY_LEASE_ENDED")
            if (
                _identity(grant) != _identity(self._grant)
                or grant.issued_at != self._grant.issued_at
                or grant.absolute_expires_at != self._grant.absolute_expires_at
                or grant.grant_revision < self._grant.grant_revision
            ):
                raise ValueError("KAKAO_GATEWAY_GRANT_STALE")
            if grant.grant_revision == self._grant.grant_revision:
                if grant != self._grant:
                    raise ValueError("KAKAO_GATEWAY_GRANT_CONFLICT")
                return False
            if (
                not self._grant.authorized_at <= grant.authorized_at <= now < grant.expires_at
                or grant.expires_at < self._grant.expires_at
            ):
                raise ValueError("KAKAO_GATEWAY_GRANT_INVALID")
            # UTC rollback must not turn a higher revision of the same expiry into
            # extra real-time control. Anchor extensions to the existing deadline.
            extended_deadline = (
                self._deadline + (grant.expires_at - self._grant.expires_at).total_seconds()
            )
            self._grant = grant
            self._deadline = min(
                self._absolute_deadline,
                extended_deadline,
                monotonic_now + (grant.expires_at - now).total_seconds(),
            )
            return True

    def revoke(self, revocation: GatewayRevocation) -> GatewayLifetimeState:
        with self._lock:
            if (revocation.lease_id, revocation.fence_epoch, revocation.gateway_epoch) != (
                self._grant.lease_id,
                self._grant.fence_epoch,
                self._grant.gateway_epoch,
            ):
                raise ValueError("KAKAO_GATEWAY_REVOCATION_STALE")
            # Ending an epoch is irreversible. A concurrent heartbeat must not make
            # an already issued logout/revocation notice too old to close viewers.
            self._close()
            return self._state
