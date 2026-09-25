#!/usr/bin/env python3
"""Publish one explicitly approved local-image LoRA authorization."""

from __future__ import annotations

import argparse
import json
from datetime import datetime

from eom_catalog_service.local_image_training_authorization import (
    build_training_authorization,
    resolve_training_authorization_scope,
)
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.database import build_engine
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from eom_orchestrator.settings import Settings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph-revision-id", required=True)
    parser.add_argument("--graph-snapshot-sha256", required=True)
    parser.add_argument("--graph-manifest-sha256", required=True)
    parser.add_argument("--expected-target-count", type=int, required=True)
    parser.add_argument("--approved-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--source-commit", required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    engine = build_engine()
    try:
        snapshot, rights = resolve_training_authorization_scope(
            engine,
            graph_revision_id=args.graph_revision_id,
            expected_graph_snapshot_sha256=args.graph_snapshot_sha256,
            expected_graph_manifest_sha256=args.graph_manifest_sha256,
            expected_target_count=args.expected_target_count,
        )
        authorization = build_training_authorization(
            source_snapshot=snapshot,
            rights_policies=rights,
            approved_at=args.approved_at,
            approved_by=args.approved_by,
        )
        pointer = LocalImageTrainingControlArtifactPublisher(
            ControlArtifactPublisher(engine, Settings.from_environment()),
            source_commit=args.source_commit,
        ).commit_authorization(authorization)
    finally:
        engine.dispose()
    print(
        json.dumps(
            {
                "status": "SUCCEEDED",
                "authorization_id": authorization.authorization_id,
                "authorization_revision_id": authorization.authorization_revision_id,
                "authorization_sha256": authorization.authorization_sha256,
                "rights_policy_count": len(authorization.rights_policies),
                "artifact_id": pointer.artifact_id,
                "artifact_revision_id": pointer.artifact_revision_id,
                "artifact_sha256": pointer.sha256,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
