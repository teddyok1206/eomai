"""Deterministic catalog projections for external JSON, JSONL, and CSV handoff."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.database import build_session_factory
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from eom_catalog_service.models import (
    DeliverableRecord,
    ItemRecord,
    ItemRevisionRecord,
    UsagePlanRecord,
    UsageRecord,
)

ExportKind = Literal["items", "usage", "snapshot"]
ExportFormat = Literal["json", "jsonl", "csv"]


@dataclass(frozen=True)
class ExportResult:
    output: Path
    manifest: Path
    row_count: int
    sha256: str
    migration_revision: str


class RegistryExporter:
    def __init__(self, engine: Engine) -> None:
        self.sessions = build_session_factory(engine)

    def export(self, kind: ExportKind, output_format: ExportFormat, output: Path) -> ExportResult:
        with self.sessions() as session:
            migration_revision = str(
                session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            )
            rows = self._rows(session, kind)
        payload = self._serialize(rows, output_format)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload)
        output.chmod(0o640)
        digest = sha256_bytes(payload)
        manifest = output.with_name(f"{output.name}.manifest.json")
        manifest.write_bytes(
            canonical_json_bytes(
                {
                    "schema_version": "1.0",
                    "export_kind": kind,
                    "format": output_format,
                    "exported_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    "migration_revision": migration_revision,
                    "row_count": len(rows),
                    "sha256": digest,
                    "output_file": output.name,
                }
            )
        )
        manifest.chmod(0o640)
        return ExportResult(output, manifest, len(rows), digest, migration_revision)

    @staticmethod
    def _rows(session: Session, kind: ExportKind) -> list[dict[str, Any]]:
        if kind == "items":
            result = session.execute(
                select(ItemRecord, ItemRevisionRecord)
                .join(
                    ItemRevisionRecord,
                    ItemRevisionRecord.item_revision_id == ItemRecord.current_revision_id,
                )
                .order_by(ItemRecord.created_at, ItemRecord.item_id)
            )
            return [
                {
                    "item_id": item.item_id,
                    "lifecycle_state": item.lifecycle_state,
                    "current_revision_id": revision.item_revision_id,
                    "revision_number": revision.revision_number,
                    "revision_state": revision.revision_state,
                    "content_pack_release_id": revision.content_pack_release_id,
                    "workflow_id": revision.workflow_id,
                    "manifest_artifact_id": revision.manifest_artifact_id,
                    "manifest_artifact_revision_id": revision.manifest_artifact_revision_id,
                    "manifest_sha256": revision.manifest_sha256,
                    "item_type_key": revision.item_type_key,
                    "metadata_sha256": revision.metadata_sha256,
                    "created_at": item.created_at.isoformat(),
                }
                for item, revision in result
            ]
        if kind == "usage":
            records = session.scalars(
                select(UsageRecord).order_by(UsageRecord.recorded_at, UsageRecord.usage_record_id)
            )
            return [
                {
                    "usage_record_id": record.usage_record_id,
                    "item_id": record.item_id,
                    "item_revision_id": record.item_revision_id,
                    "deliverable_id": record.deliverable_id,
                    "deliverable_revision_id": record.deliverable_revision_id,
                    "section": record.section,
                    "sequence": record.sequence,
                    "page": record.page,
                    "points": record.points,
                    "usage_role": record.usage_role,
                    "source_usage_plan_id": record.source_usage_plan_id,
                    "recorded_at": record.recorded_at.isoformat(),
                }
                for record in records
            ]
        items = RegistryExporter._rows(session, "items")
        usage = RegistryExporter._rows(session, "usage")
        deliverables = [
            {
                "deliverable_id": record.deliverable_id,
                "deliverable_key": record.deliverable_key,
                "deliverable_type": record.deliverable_type,
                "lifecycle_state": record.lifecycle_state,
            }
            for record in session.scalars(
                select(DeliverableRecord).order_by(DeliverableRecord.deliverable_id)
            )
        ]
        plans = [
            {
                "usage_plan_id": record.usage_plan_id,
                "item_id": record.item_id,
                "preferred_item_revision_id": record.preferred_item_revision_id,
                "deliverable_id": record.deliverable_id,
                "deliverable_revision_id": record.deliverable_revision_id,
                "status": record.status,
            }
            for record in session.scalars(
                select(UsagePlanRecord).order_by(UsagePlanRecord.usage_plan_id)
            )
        ]
        return [
            {"items": items, "deliverables": deliverables, "usage_plans": plans, "usage": usage}
        ]

    @staticmethod
    def _serialize(rows: list[dict[str, Any]], output_format: ExportFormat) -> bytes:
        if output_format == "json":
            return canonical_json_bytes({"schema_version": "1.0", "rows": rows})
        if output_format == "jsonl":
            return b"".join(canonical_json_bytes(row) + b"\n" for row in rows)
        if not rows:
            return b""
        if any(any(isinstance(value, (dict, list)) for value in row.values()) for row in rows):
            raise ValueError("CSV export requires flat rows")
        buffer = io.StringIO(newline="")
        fieldnames = list(rows[0])
        writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return buffer.getvalue().encode("utf-8")
