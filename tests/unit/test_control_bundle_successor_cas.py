from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_orchestrator.control_service import (
    BundleRevisionCAS,
    ControlPlaneError,
    publish_bundle_revision_successor,
)
from sqlalchemy.orm import Session


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object:
        return self.value


class _BundleSession:
    def __init__(
        self,
        *,
        current_revision_id: str,
        prior_manifest_sha256: str = "sha256:" + "3" * 64,
        prior_content_sha256: str = "sha256:" + "4" * 64,
        target_revision_number: int = 2,
        target_present: bool = True,
    ) -> None:
        self.logical = SimpleNamespace(
            bundle_id="instrbundle_" + "1" * 32,
            state="ACTIVE",
            current_revision_id=current_revision_id,
        )
        self.prior = SimpleNamespace(
            bundle_revision_id="instrrev_" + "1" * 32,
            bundle_id=self.logical.bundle_id,
            bundle_kind="INSTRUCTION",
            state="RELEASED",
            revision_number=1,
            manifest_sha256=prior_manifest_sha256,
            content_sha256=prior_content_sha256,
        )
        self.target = (
            SimpleNamespace(
                bundle_revision_id="instrrev_" + "2" * 32,
                bundle_id=self.logical.bundle_id,
                bundle_kind="INSTRUCTION",
                state="RELEASED",
                revision_number=target_revision_number,
            )
            if target_present
            else None
        )
        self.flush_count = 0

    def execute(self, _statement: object) -> _ScalarResult:
        return _ScalarResult(self.logical)

    def get(self, _model: object, identity: str) -> object | None:
        if identity == self.prior.bundle_revision_id:
            return self.prior
        if self.target is not None and identity == self.target.bundle_revision_id:
            return self.target
        return None

    def flush(self) -> None:
        self.flush_count += 1


def _cas() -> BundleRevisionCAS:
    return BundleRevisionCAS(
        bundle_revision_id="instrrev_" + "1" * 32,
        manifest_sha256="sha256:" + "3" * 64,
        content_sha256="sha256:" + "4" * 64,
    )


def _publish(session: _BundleSession) -> Any:
    return publish_bundle_revision_successor(
        cast(Session, session),
        bundle_id=session.logical.bundle_id,
        bundle_revision_id="instrrev_" + "2" * 32,
        predecessor=_cas(),
    )


def test_bundle_successor_cas_advances_once_and_exact_replay_is_idempotent() -> None:
    session = _BundleSession(current_revision_id="instrrev_" + "1" * 32)

    first = _publish(session)
    replay = _publish(session)

    assert first is session.target
    assert replay is session.target
    assert session.logical.current_revision_id == "instrrev_" + "2" * 32
    assert session.flush_count == 1


@pytest.mark.parametrize(
    ("session", "expected_code"),
    (
        (
            _BundleSession(
                current_revision_id="instrrev_" + "1" * 32,
                prior_content_sha256="sha256:" + "9" * 64,
            ),
            "CONTROL_POINTER_HASH_MISMATCH",
        ),
        (
            _BundleSession(current_revision_id="instrrev_" + "9" * 32),
            "CONTROL_CURRENT_REVISION_STALE",
        ),
        (
            _BundleSession(
                current_revision_id="instrrev_" + "1" * 32,
                target_revision_number=3,
            ),
            "CONTROL_CURRENT_REVISION_STALE",
        ),
        (
            _BundleSession(
                current_revision_id="instrrev_" + "1" * 32,
                target_present=False,
            ),
            "CONTROL_POINTER_MISSING",
        ),
    ),
)
def test_bundle_successor_cas_rejects_hash_state_revision_and_pointer_drift(
    session: _BundleSession,
    expected_code: str,
) -> None:
    with pytest.raises(ControlPlaneError) as captured:
        _publish(session)

    assert captured.value.code == expected_code
    assert session.logical.current_revision_id != "instrrev_" + "2" * 32
    assert session.flush_count == 0
