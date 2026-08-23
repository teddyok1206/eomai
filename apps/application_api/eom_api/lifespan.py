"""Application service composition and lifecycle."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from eom_catalog_service.registry_service import RegistryService
from eom_hwpx_manager import HwpxApplicationService, HwpxCapabilityService
from eom_identity_service.auth_service import AuthService, LoginPolicy
from eom_identity_service.service import OperatorService
from eom_identity_service.tokens import SessionTokenService, TokenCodec, TokenPolicy
from eom_orchestrator.database import build_engine
from fastapi import FastAPI
from sqlalchemy import Engine

from eom_api.rate_limit import BoundedRateLimiter
from eom_api.services.audit_service import AuditService
from eom_api.services.catalog_application_client import CatalogApplicationClient
from eom_api.services.command_adapter import CommandAdapter
from eom_api.services.control_plane_adapter import ControlPlaneAdapter
from eom_api.services.hwpx_download_client import HwpxDownloadClient
from eom_api.services.idempotency_service import IdempotencyService
from eom_api.services.query_adapter import QueryAdapter
from eom_api.settings import ApiSecrets, ApiSettings, load_secrets, load_settings


class AppServices:
    def __init__(self, settings: ApiSettings, secrets: ApiSecrets, engine: Engine) -> None:
        token_key = secrets.token_hash_key.get_secret_value().encode("utf-8")
        fingerprint_key = secrets.fingerprint_key.get_secret_value().encode("utf-8")
        self.settings = settings
        self.secrets = secrets
        self.engine = engine
        token_service = SessionTokenService(
            TokenCodec(token_key),
            TokenPolicy(
                access_seconds=settings.auth.access_token_seconds,
                refresh_seconds=settings.auth.refresh_token_seconds,
                session_absolute_seconds=settings.auth.session_absolute_seconds,
                session_idle_seconds=settings.auth.session_idle_seconds,
            ),
        )
        self.auth = AuthService(
            engine,
            token_service,
            login_policy=LoginPolicy(
                failure_limit=settings.auth.login_failure_limit,
                failure_window_seconds=settings.auth.login_failure_window_seconds,
                lock_seconds=settings.auth.lock_seconds,
            ),
        )
        self.operators = OperatorService(engine)
        self.queries = QueryAdapter(engine, fingerprint_key)
        self.registry = RegistryService(engine)
        self.catalog_application = CatalogApplicationClient()
        self.commands = CommandAdapter(engine, catalog_application=self.catalog_application)
        self.control_plane = ControlPlaneAdapter(engine)
        self.idempotency = IdempotencyService(engine, token_key)
        self.audit = AuditService(engine)
        self.hwpx = HwpxApplicationService(engine, registry=self.registry)
        self.hwpx_downloads = HwpxDownloadClient()
        self.hwpx_capability = HwpxCapabilityService(manager_registered=True)
        self.rate_limiter = BoundedRateLimiter(settings.rate_limit.maximum_buckets)
        self.fingerprint_key = fingerprint_key


def build_services(
    settings: ApiSettings | None = None,
    secrets: ApiSecrets | None = None,
) -> AppServices:
    actual_settings = settings or load_settings()
    actual_secrets = secrets or load_secrets()
    engine = build_engine(actual_secrets.database_url.get_secret_value())
    return AppServices(actual_settings, actual_secrets, engine)


def lifespan_for(
    services: AppServices,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        services.engine.dispose()

    return lifespan
