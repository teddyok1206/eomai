"""Local-owner interface for the narrowly approved, installed reset application."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import psycopg
import typer
from eom_orchestrator.database import build_engine
from eom_orchestrator.prelaunch_item_reset_service import PrelaunchItemResetService
from eom_orchestrator.prelaunch_reset_artifacts import PrelaunchResetArtifacts, reset_document_bytes
from eom_orchestrator.prelaunch_reset_host import InstalledPrelaunchResetFence
from eom_protocol.prelaunch_item_reset import PrelaunchItemResetPlan, ResetBackupPin
from sqlalchemy import Engine

prelaunch_reset_app = typer.Typer(no_args_is_help=True)


def _bounded_document(path: Path, limit: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
            raise ValueError("ITEM_RESET_INPUT_FILE_INVALID")
        payload = os.read(descriptor, limit + 1)
        after = os.fstat(descriptor)
        if (
            len(payload) != before.st_size
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
        ):
            raise ValueError("ITEM_RESET_INPUT_FILE_CHANGED")
        return payload
    finally:
        os.close(descriptor)


def _compose() -> tuple[
    PrelaunchItemResetService,
    PrelaunchResetArtifacts,
    psycopg.Connection[tuple[object, ...]],
    Engine,
]:
    from eom_catalog_service import prelaunch_item_cleanup as catalog
    from eom_hwpx_manager import prelaunch_item_cleanup as hwpx
    from eom_orchestrator import prelaunch_artifact_cleanup as artifacts
    from eom_workflow_runner import prelaunch_item_cleanup as workflows

    host = InstalledPrelaunchResetFence()
    host.authorize_local_owner()
    application = PrelaunchItemResetService(
        catalog=catalog, workflows=workflows, hwpx=hwpx, artifacts=artifacts, host=host
    )
    url = host.owner_database_url()
    if url.get_backend_name() != "postgresql" or url.host != "127.0.0.1":
        raise ValueError("ITEM_RESET_LOCAL_DATABASE_REQUIRED")
    connection = psycopg.connect(
        url.set(drivername="postgresql").render_as_string(hide_password=False),
        options="-csearch_path=app,pg_catalog",
    )
    engine = build_engine(url.render_as_string(hide_password=False))
    return application, PrelaunchResetArtifacts(engine, host.source_commit), connection, engine


@prelaunch_reset_app.command("plan")
def prepare_plan(
    backup_manifest: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option()],
) -> None:
    value = json.loads(_bounded_document(backup_manifest, 16384))
    backup = ResetBackupPin(
        file_name=value["file"], sha256=value["sha256"], size_bytes=value["size_bytes"]
    )
    service, artifacts, connection, engine = _compose()
    try:
        with connection:
            plan = service.prepare(connection, backup)
        published = artifacts.publish_plan(plan)
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(reset_document_bytes(plan))
        typer.echo(
            json.dumps(
                {
                    "plan_file": str(output),
                    "plan_sha256": plan.plan_sha256,
                    "items": len(plan.item_ids),
                    "workflows": len(plan.workflow_ids),
                    "artifact": asdict(published),
                },
                ensure_ascii=False,
            )
        )
    finally:
        connection.close()
        engine.dispose()


@prelaunch_reset_app.command("apply")
def apply_plan(
    plan_file: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    expected_plan_sha256: Annotated[str, typer.Option()],
) -> None:
    descriptor = os.open(plan_file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        meta = os.fstat(descriptor)
        if (
            not stat.S_ISREG(meta.st_mode)
            or meta.st_size > 2 * 1024 * 1024
            or stat.S_IMODE(meta.st_mode) & 0o022
        ):
            raise ValueError("ITEM_RESET_PLAN_FILE_INVALID")
        payload = os.read(descriptor, 2 * 1024 * 1024 + 1)
    finally:
        os.close(descriptor)
    plan = PrelaunchItemResetPlan.model_validate_json(payload)
    if plan.plan_sha256 != expected_plan_sha256:
        raise ValueError("ITEM_RESET_PLAN_HASH_MISMATCH")
    service, artifacts, connection, engine = _compose()
    try:
        artifacts.require_plan(plan)
        existing = artifacts.find_receipt(plan)
        replay = existing is not None
        if existing is None:
            with connection:
                receipt = service.apply(connection, plan)
            published = artifacts.publish_receipt(plan, receipt)
        else:
            receipt, published = existing
        typer.echo(
            json.dumps(
                {
                    "replayed": replay,
                    "receipt": receipt.model_dump(mode="json"),
                    "artifact": asdict(published),
                },
                ensure_ascii=False,
            )
        )
    finally:
        connection.close()
        engine.dispose()
