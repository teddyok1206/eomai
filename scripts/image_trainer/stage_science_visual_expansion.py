#!/usr/bin/env python3
"""Compose supported admission/planning/staging for a frozen supplemental CPU pilot."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from eom_catalog_service.science_visual_expansion_planning import (
    build_science_visual_expansion_plan,
)
from eom_image_contracts import ImageEvaluationArtifactMember, ScienceVisualToolSet
from eom_image_contracts.science_visual_pilot_codec import build_science_visual_pilot_command
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.database import build_engine
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from eom_orchestrator.sdxl_probe_inputs import resolve_sdxl_training_sources
from eom_orchestrator.settings import Settings

from scripts.image_trainer import stage_science_visual_pilot as stage
from scripts.image_trainer.publication_io import read_regular_file


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--basis-crop-set-pointer", type=Path, required=True)
    parser.add_argument("--authorization-pointer", type=Path, required=True)
    parser.add_argument("--created-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--created-by", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--campaign-shard-index", type=int, required=True)
    parser.add_argument("--campaign-shard-count", type=int, default=3)
    parser.add_argument("--source-limit", type=int, default=54)
    parser.add_argument("--page-limit", type=int, default=384)
    parser.add_argument("--candidate-limit", type=int, default=512)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _pointer(path: Path) -> ImageEvaluationArtifactMember:
    return ImageEvaluationArtifactMember.model_validate_json(
        read_regular_file(path, maximum_bytes=8 * 1024)
    )


def main() -> int:
    args = _parser().parse_args()
    stage._require_utc(args.created_at, "CREATION")
    stage._require_release(args.source_commit)
    basis_pointer = _pointer(args.basis_crop_set_pointer)
    authorization_pointer = _pointer(args.authorization_pointer)
    engine = build_engine()
    try:
        sources = resolve_sdxl_training_sources(
            engine,
            crop_set_pointer=basis_pointer,
            authorization_pointer=authorization_pointer,
        )
        corpus = stage._load_corpus(engine, sources.authorization.corpus_manifest)
        first = sources.plans[0]
        plan = build_science_visual_expansion_plan(
            corpus=corpus,
            corpus_manifest=sources.authorization.corpus_manifest,
            authorization=sources.authorization,
            authorization_pointer=authorization_pointer,
            predecessor_plans=sources.plans,
            predecessor_plan_pointers=tuple(
                pilot.pilot_plan for pilot in sources.inventory.pilot_results
            ),
            selection_seed_sha256=first.selection_seed_sha256,
            campaign_shard_index=args.campaign_shard_index,
            campaign_shard_count=args.campaign_shard_count,
            guidance_authorities=stage._guidance(args.source_commit),
            tools=ScienceVisualToolSet(
                pdftoppm=stage._tool("/usr/bin/pdftoppm", "-v"),
                tesseract=stage._tool("/usr/bin/tesseract", "--version"),
            ),
            source_commit=args.source_commit,
            created_at=args.created_at,
            created_by=args.created_by,
            locator_policy=first.locator_policy,
            source_limit=args.source_limit,
            page_limit=args.page_limit,
            max_visual_candidates=args.candidate_limit,
            max_lora_training_crops=24,
        )
        if args.preflight_only:
            print(
                json.dumps(
                    {
                        "preflight": "PASS_METADATA_ONLY_NO_PDF_READ",
                        "schema_version": plan.schema_version,
                        "plan_sha256": plan.plan_sha256,
                        "historical_source_count": sum(
                            len(prior.selected_sources) for prior in sources.plans
                        ),
                        "new_selected_sources": len(plan.selected_sources),
                        "new_selected_pages": plan.max_page_images,
                        "shard_index": plan.campaign_shard_index,
                        "shard_count": plan.campaign_shard_count,
                        "gpu_calls": 0,
                        "registry_writes": 0,
                    },
                    sort_keys=True,
                )
            )
            return 0
        publisher = LocalImageTrainingControlArtifactPublisher(
            ControlArtifactPublisher(engine, Settings.from_environment()),
            source_commit=args.source_commit,
        )
        plan_pointer = publisher.commit_science_visual_pilot_plan_v4(plan)
        command = build_science_visual_pilot_command(
            plan=plan,
            plan_pointer=plan_pointer,
            requested_at=args.created_at,
            requested_by=args.created_by,
        )
        workspace = stage._stage_workspace(
            engine=engine,
            plan=plan,
            plan_pointer=plan_pointer,
            command=command,
        )
        receipt = stage._write_receipt(
            command=command,
            plan_pointer=plan_pointer,
            authorization_pointer=authorization_pointer,
            workspace=workspace,
        )
        print(
            json.dumps(
                {
                    "attempt_id": command.attempt_id,
                    "receipt": str(receipt),
                    "systemd_unit": f"eom-image-science-visual-pilot@{command.attempt_id}.service",
                    "new_sources": len(plan.selected_sources),
                    "old_authorization": "UNCHANGED",
                    "worker_started": False,
                },
                sort_keys=True,
            )
        )
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
