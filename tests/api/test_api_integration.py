from __future__ import annotations

import os

import pytest
from eom_api.app import create_app
from eom_api.lifespan import build_services
from eom_api.settings import ApiSecrets, ApiSettings
from eom_identity_service.models import (
    ApiIdempotencyRecord,
    ApiSessionRecord,
    ApiTokenRecord,
    OperatorCredentialRecord,
    OperatorEventRecord,
    OperatorRecord,
    OperatorRoleAssignmentRecord,
)
from eom_identity_service.service import OperatorService
from eom_orchestrator.database import build_engine, build_session_factory, transaction
from eom_orchestrator.settings import database_url
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from tests.api.helpers import TEST_FINGERPRINT_KEY, TEST_TOKEN_KEY

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
ADMIN_PASSWORD = "TEST_ONLY API admin password 84"
VIEWER_PASSWORD = "TEST_ONLY API viewer password 42"


class NoopAudit:
    def append(self, *args: object, **kwargs: object) -> None:
        pass


def _enabled() -> None:
    if os.environ.get("EOM_RUN_API_INTEGRATION") != "1":
        pytest.skip("set EOM_RUN_API_INTEGRATION=1 with an isolated PostgreSQL database")


def _cleanup(engine: object) -> None:
    from sqlalchemy import Engine

    assert isinstance(engine, Engine)
    sessions = build_session_factory(engine)
    with transaction(sessions) as session:
        operator_ids = list(
            session.scalars(
                select(OperatorRecord.operator_id).where(
                    OperatorRecord.username.in_(("admin", "viewer01"))
                )
            )
        )
        if not operator_ids:
            return
        session_ids = select(ApiSessionRecord.api_session_id).where(
            ApiSessionRecord.operator_id.in_(operator_ids)
        )
        session.execute(
            delete(ApiTokenRecord).where(ApiTokenRecord.api_session_id.in_(session_ids))
        )
        session.execute(
            delete(ApiIdempotencyRecord).where(ApiIdempotencyRecord.operator_id.in_(operator_ids))
        )
        session.execute(
            delete(ApiSessionRecord).where(ApiSessionRecord.operator_id.in_(operator_ids))
        )
        session.execute(
            delete(OperatorEventRecord).where(OperatorEventRecord.operator_id.in_(operator_ids))
        )
        session.execute(
            delete(OperatorRoleAssignmentRecord).where(
                OperatorRoleAssignmentRecord.operator_id.in_(operator_ids)
            )
        )
        session.execute(
            delete(OperatorCredentialRecord).where(
                OperatorCredentialRecord.operator_id.in_(operator_ids)
            )
        )
        session.execute(delete(OperatorRecord).where(OperatorRecord.operator_id.in_(operator_ids)))


def _authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_http_auth_rbac_rotation_reuse_and_revocation() -> None:
    _enabled()
    engine = build_engine()
    sessions = build_session_factory(engine)
    with sessions() as session:
        if int(session.scalar(select(func.count(OperatorRecord.operator_id))) or 0):
            pytest.skip("API integration requires a database without existing Operators")
    bootstrap = OperatorService(engine).bootstrap_admin(username="admin", display_name="관리자")
    services = build_services(
        ApiSettings(),
        ApiSecrets(
            database_url=database_url(),
            token_hash_key=TEST_TOKEN_KEY,
            fingerprint_key=TEST_FINGERPRINT_KEY,
        ),
    )
    services.audit = NoopAudit()  # type: ignore[assignment]
    try:
        with TestClient(create_app(services), base_url="http://localhost") as client:
            unknown = client.post(
                "/api/v1/auth/login",
                json={
                    "username": "unknown",
                    "password": "TEST_ONLY unknown password 42",
                    "client_name": "api-integration",
                },
            )
            assert unknown.status_code == 401
            assert unknown.json()["error_code"] == "AUTH_INVALID_CREDENTIALS"

            restricted = client.post(
                "/api/v1/auth/login",
                json={
                    "username": "admin",
                    "password": bootstrap.temporary_password,
                    "client_name": "api-integration",
                },
            ).json()["data"]
            assert restricted["password_change_required"]
            assert (
                client.get(
                    "/api/v1/operators",
                    headers=_authorization(restricted["access_token"]),
                ).status_code
                == 403
            )
            changed = client.post(
                "/api/v1/auth/change-password",
                headers=_authorization(restricted["access_token"]),
                json={
                    "current_password": bootstrap.temporary_password,
                    "new_password": ADMIN_PASSWORD,
                },
            )
            assert changed.status_code == 200
            admin_pair = changed.json()["data"]
            admin_headers = _authorization(admin_pair["access_token"])
            assert client.get("/api/v1/operators", headers=admin_headers).status_code == 200

            created = client.post(
                "/api/v1/operators",
                headers={**admin_headers, "Idempotency-Key": "create-viewer-0001"},
                json={
                    "username": "viewer01",
                    "display_name": "조회자",
                    "temporary_password": VIEWER_PASSWORD,
                    "initial_roles": ["VIEWER"],
                },
            )
            assert created.status_code == 201
            assert VIEWER_PASSWORD not in created.text
            viewer_id = created.json()["data"]["resource_id"]
            replay = client.post(
                "/api/v1/operators",
                headers={**admin_headers, "Idempotency-Key": "create-viewer-0001"},
                json={
                    "username": "viewer01",
                    "display_name": "조회자",
                    "temporary_password": VIEWER_PASSWORD,
                    "initial_roles": ["VIEWER"],
                },
            )
            assert replay.status_code == 201
            assert replay.json()["data"]["resource_id"] == viewer_id
            conflict = client.post(
                "/api/v1/operators",
                headers={**admin_headers, "Idempotency-Key": "create-viewer-0001"},
                json={
                    "username": "viewer01",
                    "display_name": "조회자",
                    "temporary_password": "TEST_ONLY different password 55",
                    "initial_roles": ["VIEWER"],
                },
            )
            assert conflict.status_code == 409
            assert conflict.json()["error_code"] == "API_IDEMPOTENCY_CONFLICT"

            viewer_restricted = client.post(
                "/api/v1/auth/login",
                json={
                    "username": "viewer01",
                    "password": VIEWER_PASSWORD,
                    "client_name": "api-integration",
                },
            ).json()["data"]
            viewer_pair = client.post(
                "/api/v1/auth/change-password",
                headers=_authorization(viewer_restricted["access_token"]),
                json={
                    "current_password": VIEWER_PASSWORD,
                    "new_password": "TEST_ONLY API viewer replacement 73",
                },
            ).json()["data"]
            viewer_headers = _authorization(viewer_pair["access_token"])
            workflow_body = {
                "definition_key": "missing-definition",
                "definition_version": "1.0.0",
                "request_name": "PLACEHOLDER_REQUEST",
                "image_mode": "skip",
            }
            denied = client.post(
                "/api/v1/workflows",
                headers={**viewer_headers, "Idempotency-Key": "viewer-start-0001"},
                json=workflow_body,
            )
            assert denied.status_code == 403

            detail = client.get(f"/api/v1/operators/{viewer_id}", headers=admin_headers)
            assigned = client.post(
                f"/api/v1/operators/{viewer_id}/roles/AUTHOR",
                headers={
                    **admin_headers,
                    "Idempotency-Key": "assign-author-0001",
                    "If-Match": detail.headers["ETag"],
                },
                json={},
            )
            assert assigned.status_code == 200
            immediate = client.post(
                "/api/v1/workflows",
                headers={**viewer_headers, "Idempotency-Key": "viewer-start-0002"},
                json=workflow_body,
            )
            assert immediate.status_code == 404

            detail = client.get(f"/api/v1/operators/{viewer_id}", headers=admin_headers)
            disabled = client.post(
                f"/api/v1/operators/{viewer_id}/disable",
                headers={
                    **admin_headers,
                    "Idempotency-Key": "disable-viewer-001",
                    "If-Match": detail.headers["ETag"],
                },
                json={"reason": "TEST_ONLY integration disable"},
            )
            assert disabled.status_code == 200
            assert client.get("/api/v1/items", headers=viewer_headers).status_code == 401

            rotated = client.post(
                "/api/v1/auth/refresh", json={"refresh_token": admin_pair["refresh_token"]}
            )
            assert rotated.status_code == 200
            rotated_pair = rotated.json()["data"]
            reused = client.post(
                "/api/v1/auth/refresh", json={"refresh_token": admin_pair["refresh_token"]}
            )
            assert reused.status_code == 401
            assert reused.json()["error_code"] == "AUTH_REFRESH_TOKEN_REUSED"
            assert (
                client.get(
                    "/api/v1/operators",
                    headers=_authorization(rotated_pair["access_token"]),
                ).status_code
                == 401
            )

            relogin = client.post(
                "/api/v1/auth/login",
                json={
                    "username": "admin",
                    "password": ADMIN_PASSWORD,
                    "client_name": "api-integration",
                },
            ).json()["data"]
            logged_out = client.post(
                "/api/v1/auth/logout", headers=_authorization(relogin["access_token"]), json={}
            )
            assert logged_out.status_code == 200
            assert (
                client.get(
                    "/api/v1/operators", headers=_authorization(relogin["access_token"])
                ).status_code
                == 401
            )
    finally:
        services.engine.dispose()
        _cleanup(engine)
        engine.dispose()
