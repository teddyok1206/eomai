"Orchestrator-owned immutable reset plans/receipts, not duplicated Item payloads."

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from eom_protocol.prelaunch_item_reset import PrelaunchItemResetPlan, PrelaunchItemResetReceipt
from sqlalchemy import Engine

from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
    PublishedControlFileSet,
)
from eom_orchestrator.settings import Settings


def reset_document_bytes(value: PrelaunchItemResetPlan | PrelaunchItemResetReceipt) -> bytes:
    return (
        json.dumps(
            value.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        + "\n"
    ).encode()


class PrelaunchResetArtifacts:
    def __init__(
        self, engine: Engine, source_commit: str, settings: Settings | None = None
    ) -> None:
        self.publisher = ControlFileSetPublisher(engine, settings)
        self.source_commit = source_commit

    def _publish(
        self,
        value: PrelaunchItemResetPlan | PrelaunchItemResetReceipt,
        plan: PrelaunchItemResetPlan,
        kind: str,
    ) -> PublishedControlFileSet:
        payload = reset_document_bytes(value)
        root = self.publisher.settings.staging_root
        with tempfile.TemporaryDirectory(prefix="prelaunch-reset-", dir=root) as directory:
            source = Path(directory) / f"{kind}.json"
            source.write_bytes(payload)
            source.chmod(0o400)
            return self.publisher.publish(
                members=(
                    ControlFileSetMember(
                        source.name,
                        source,
                        "sha256:" + hashlib.sha256(payload).hexdigest(),
                        len(payload),
                        f"eom://schemas/operations/prelaunch-item-reset-{kind}/1.0",
                        "application/json",
                    ),
                ),
                primary_file=source.name,
                artifact_type=f"control_prelaunch_item_reset_{kind}",
                manifest_version=value.schema_version,
                idempotency_key=f"prelaunch-reset-{kind}:{plan.plan_sha256}",
                source_commit=self.source_commit,
                created_at=datetime.fromisoformat(plan.created_at_utc.replace("Z", "+00:00")),
            )

    def publish_plan(self, plan: PrelaunchItemResetPlan) -> PublishedControlFileSet:
        return self._publish(plan, plan, "plan")

    def require_plan(self, plan: PrelaunchItemResetPlan) -> None:
        published = self.publisher.find_published(
            idempotency_key=f"prelaunch-reset-plan:{plan.plan_sha256}",
            artifact_type="control_prelaunch_item_reset_plan",
        )
        if (
            published is None
            or published.primary_sha256
            != "sha256:" + hashlib.sha256(reset_document_bytes(plan)).hexdigest()
        ):
            raise ValueError("ITEM_RESET_PUBLISHED_PLAN_REQUIRED")

    def find_receipt(
        self, plan: PrelaunchItemResetPlan
    ) -> tuple[PrelaunchItemResetReceipt, PublishedControlFileSet] | None:
        published = self.publisher.find_published(
            idempotency_key=f"prelaunch-reset-receipt:{plan.plan_sha256}",
            artifact_type="control_prelaunch_item_reset_receipt",
        )
        if published is None:
            return None
        path = Path(published.nas_path) / published.primary_file
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            payload = os.read(descriptor, 131073)
        finally:
            os.close(descriptor)
        if (
            len(payload) > 131072
            or "sha256:" + hashlib.sha256(payload).hexdigest() != published.primary_sha256
        ):
            raise ValueError("ITEM_RESET_RECEIPT_BYTES_INVALID")
        value = PrelaunchItemResetReceipt.model_validate_json(payload)
        if value.plan_sha256 != plan.plan_sha256 or value.database != plan.database:
            raise ValueError("ITEM_RESET_RECEIPT_IDENTITY_INVALID")
        return value, published

    def publish_receipt(
        self, plan: PrelaunchItemResetPlan, receipt: PrelaunchItemResetReceipt
    ) -> PublishedControlFileSet:
        if (
            receipt.plan_sha256 != plan.plan_sha256
            or receipt.protected_sha256 != plan.protected_sha256
        ):
            raise ValueError("ITEM_RESET_RECEIPT_IDENTITY_INVALID")
        return self._publish(receipt, plan, "receipt")
