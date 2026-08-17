"""Materialize non-canonical intake pointers in the NAS operations area."""

from __future__ import annotations

import os
from pathlib import Path

from eom_identifiers import canonical_json_bytes


class IntakePointerStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, area: str, batch_id: str, artifact_id: str, revision_id: str) -> None:
        directory = self.root / area / batch_id
        directory.mkdir(parents=True, mode=0o750, exist_ok=True)
        pointer = directory / "intake-pointer.json"
        temporary = directory / f".intake-pointer-{os.getpid()}.tmp"
        temporary.write_bytes(
            canonical_json_bytes(
                {
                    "schema_version": "1.0",
                    "batch_id": batch_id,
                    "artifact_id": artifact_id,
                    "revision_id": revision_id,
                }
            )
        )
        temporary.chmod(0o640)
        temporary.replace(pointer)
