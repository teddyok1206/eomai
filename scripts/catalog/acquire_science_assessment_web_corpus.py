#!/usr/bin/env python3
"""Acquire and publish the immutable public science-assessment PDF corpus."""

from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path

from eom_catalog_contracts import ScienceAssessmentWebCorpusPlan, validate_contract
from eom_catalog_service.science_assessment_web_acquisition import ScienceAssessmentWebAcquirer
from eom_catalog_service.science_assessment_web_corpus_service import (
    ScienceAssessmentWebCorpusService,
)
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.database import build_engine


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--received-by", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--discover-only", action="store_true")
    return parser.parse_args()


def _load_plan(path: Path) -> ScienceAssessmentWebCorpusPlan:
    metadata = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise RuntimeError("SCIENCE_CORPUS_PLAN_INVALID")
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("SCIENCE_CORPUS_PLAN_INVALID")
    validate_contract("science-assessment-web-corpus-plan", value)
    return ScienceAssessmentWebCorpusPlan.model_validate(value)


def _require_workspace(path: Path) -> None:
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or any(path.iterdir())
    ):
        raise RuntimeError("SCIENCE_CORPUS_WORKSPACE_INVALID")


def _write_receipt(path: Path, value: dict[str, object]) -> None:
    parent = path.parent
    parent_metadata = parent.lstat()
    if parent.is_symlink() or not stat.S_ISDIR(parent_metadata.st_mode):
        raise RuntimeError("SCIENCE_CORPUS_RECEIPT_PARENT_INVALID")
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        payload = canonical_json_bytes(value)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short corpus receipt write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> None:
    args = _arguments()
    _require_workspace(args.workspace)
    plan = _load_plan(args.plan)
    acquirer = ScienceAssessmentWebAcquirer(plan)
    discovery = acquirer.discover()
    if args.discover_only:
        _write_receipt(
            args.receipt,
            {
                "status": "DISCOVERED",
                "plan_id": plan.plan_id,
                "post_count": discovery.post_count,
                "candidate_count": len(discovery.candidates),
                "rejected_link_count": discovery.rejected_link_count,
            },
        )
        return
    acquired, failures = acquirer.acquire(discovery, args.workspace)
    engine = build_engine()
    try:
        publication = ScienceAssessmentWebCorpusService(engine).publish(
            plan=plan,
            discovery=discovery,
            acquired=acquired,
            failures=failures,
            workspace=args.workspace,
            received_by=args.received_by,
        )
    finally:
        engine.dispose()
    _write_receipt(
        args.receipt,
        {
            "status": "PUBLISHED",
            "plan_id": plan.plan_id,
            "corpus_id": publication.manifest.corpus_id,
            "artifact_id": publication.artifact_id,
            "artifact_revision_id": publication.artifact_revision_id,
            "manifest_sha256": publication.manifest_sha256,
            "summary": publication.manifest.summary.model_dump(mode="json"),
        },
    )


if __name__ == "__main__":
    main()
