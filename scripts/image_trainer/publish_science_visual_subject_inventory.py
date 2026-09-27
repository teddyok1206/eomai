#!/usr/bin/env python3
"""Rebuild, validate, and publish one science visual subject inventory."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
from pathlib import Path

from eom_image_contracts import (
    LocalImageScienceVisualSubjectInventory,
    content_json_bytes,
    validate_contract,
)
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.database import build_engine
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from eom_orchestrator.settings import Settings
from pydantic import ValidationError as PydanticValidationError

from scripts.image_trainer.build_science_visual_subject_inventory import (
    ScienceVisualSubjectInventoryBuildError,
    build_science_visual_subject_inventory,
)

MAX_JSON_BYTES = 16 * 1024 * 1024
STATE_ROOT = Path("/var/lib/eom-workflow-runner")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class ScienceVisualSubjectInventoryPublicationError(RuntimeError):
    """Stable failure at the subject-inventory publication boundary."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def safe_read_subject_inventory(path: Path) -> bytes:
    if not path.is_absolute():
        raise ScienceVisualSubjectInventoryPublicationError(
            "SCIENCE_VISUAL_SUBJECT_INVENTORY_PATH_INVALID"
        )
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as exc:
        raise ScienceVisualSubjectInventoryPublicationError(
            "SCIENCE_VISUAL_SUBJECT_INVENTORY_MISSING"
        ) from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= MAX_JSON_BYTES
            or stat.S_IMODE(before.st_mode) & 0o022
        ):
            raise ScienceVisualSubjectInventoryPublicationError(
                "SCIENCE_VISUAL_SUBJECT_INVENTORY_FILE_INVALID"
            )
        payload = bytearray()
        while len(payload) < before.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, before.st_size - len(payload)))
            if not chunk:
                raise ScienceVisualSubjectInventoryPublicationError(
                    "SCIENCE_VISUAL_SUBJECT_INVENTORY_TRUNCATED"
                )
            payload.extend(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ScienceVisualSubjectInventoryPublicationError(
                "SCIENCE_VISUAL_SUBJECT_INVENTORY_CHANGED"
            )
    finally:
        os.close(descriptor)
    return bytes(payload)


def load_subject_inventory(payload: bytes) -> LocalImageScienceVisualSubjectInventory:
    try:
        value = json.loads(payload)
        if not isinstance(value, dict):
            raise TypeError("inventory is not an object")
        validate_contract("science-visual-subject-inventory", value)
        inventory = LocalImageScienceVisualSubjectInventory.model_validate(value)
    except (
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        PydanticValidationError,
    ) as exc:
        raise ScienceVisualSubjectInventoryPublicationError(
            "SCIENCE_VISUAL_SUBJECT_INVENTORY_INVALID"
        ) from exc
    if content_json_bytes(inventory.model_dump(mode="json")) != payload:
        raise ScienceVisualSubjectInventoryPublicationError(
            "SCIENCE_VISUAL_SUBJECT_INVENTORY_NOT_CANONICAL"
        )
    return inventory


def _write_receipt(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        if safe_read_subject_inventory(path) != payload:
            raise ScienceVisualSubjectInventoryPublicationError(
                "SCIENCE_VISUAL_SUBJECT_INVENTORY_RECEIPT_CONFLICT"
            )
        return
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)


def main() -> int:
    args = _parser().parse_args()
    if _COMMIT.fullmatch(args.source_commit) is None:
        raise ScienceVisualSubjectInventoryPublicationError(
            "SCIENCE_VISUAL_SUBJECT_SOURCE_COMMIT_INVALID"
        )
    payload = safe_read_subject_inventory(args.inventory)
    inventory = load_subject_inventory(payload)
    engine = build_engine()
    try:
        rebuilt = build_science_visual_subject_inventory(
            engine,
            authorization_pointer=inventory.training_authorization,
            pattern_pointer=inventory.pattern_inventory,
            created_at=inventory.created_at,
            created_by=inventory.created_by,
        )
        if rebuilt != inventory:
            raise ScienceVisualSubjectInventoryPublicationError(
                "SCIENCE_VISUAL_SUBJECT_SOURCE_REBUILD_MISMATCH"
            )
        summary = {
            "blocked_subject_count": sum(
                subject.render_route == "BLOCKED" for subject in inventory.subjects
            ),
            "covered_visual_observation_count": inventory.covered_visual_observation_count,
            "inventory_id": inventory.inventory_id,
            "inventory_sha256": inventory.inventory_sha256,
            "omission_count": len(inventory.omissions),
            "source_item_count": inventory.source_item_count,
            "source_visual_observation_count": inventory.source_visual_observation_count,
            "subject_count": len(inventory.subjects),
        }
        if args.preflight_only:
            print(json.dumps({**summary, "preflight": "PASS"}, sort_keys=True))
            return 0
        if os.geteuid() != 0:
            raise ScienceVisualSubjectInventoryPublicationError(
                "SCIENCE_VISUAL_SUBJECT_ROOT_REQUIRED"
            )
        adapter = LocalImageTrainingControlArtifactPublisher(
            ControlArtifactPublisher(engine, Settings.from_environment()),
            source_commit=args.source_commit,
        )
        pointer = adapter.commit_science_visual_subject_inventory(inventory)
    except ScienceVisualSubjectInventoryPublicationError:
        raise
    except ScienceVisualSubjectInventoryBuildError as exc:
        raise ScienceVisualSubjectInventoryPublicationError(
            "SCIENCE_VISUAL_SUBJECT_SOURCE_RESOLUTION_FAILED"
        ) from exc
    finally:
        engine.dispose()
    STATE_ROOT.mkdir(mode=0o750, parents=True, exist_ok=True)
    receipt_path = STATE_ROOT / (
        f"science-visual-subject-inventory-publication-{inventory.inventory_id}.json"
    )
    _write_receipt(
        receipt_path,
        content_json_bytes(
            {
                "schema_version": "science-visual-subject-inventory-publication-receipt/1.0",
                **summary,
                "inventory_artifact": pointer.model_dump(mode="json"),
                "source_commit": args.source_commit,
            }
        ),
    )
    print(
        json.dumps(
            {
                "artifact_id": pointer.artifact_id,
                "artifact_revision_id": pointer.artifact_revision_id,
                "inventory_id": inventory.inventory_id,
                "receipt": str(receipt_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
