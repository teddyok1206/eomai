"""Synthetic plan/context association, not current source authorization or query execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.inference_transfer_experiment import StagedExperimentEntry
from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferProfile,
    InferenceTransferProfilePointer,
)
from eom_catalog_contracts.similarity_context import parse_similarity_context
from eom_catalog_contracts.similarity_delivery import parse_similarity_context_delivery
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_workflow.control_plane import ResolvedExecutionPlanV19
from eom_workflow.similarity_control import bind_similarity_execution_plan

from tests.unit.inference_transfer_embedding_fixtures import embedding_entry, seal
from tests.unit.test_execution_materializer import _past_exam_variation_fixture
from tests.unit.test_similarity_context_contracts import context_body
from tests.unit.test_similarity_delivery_contracts import delivery_body


def similarity_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    fixture = _past_exam_variation_fixture(tmp_path, monkeypatch)
    record = fixture["session"].records[(ResolvedExecutionPlanRecord, fixture["plan_id"])]
    body = record.canonical_document | {
        "schema_version": "resolved-execution-plan/19.0",
        "resolver_version": "19.0.0",
        "workflow_definition_version": "1.16.0",
    }
    base = ResolvedExecutionPlanV19.model_validate(seal(body, "plan_sha256"))
    raw = context_body(ready=False)
    raw["request"].update(
        graph_snapshot=base.graph_snapshot.model_dump(mode="json"),
        policy_revision_id=base.access_policy_revision_id,
        policy_sha256=base.access_policy_sha256,
    )
    original = fixture["manifest"]["entries"][0]["source"]
    raw["request"]["anchor"]["source"] = original
    profile_raw = embedding_entry().profile.model_dump(mode="json")
    profile_raw["source_basis"]["source"] = original
    profile_raw["source_basis"]["graph_snapshot"] = base.graph_snapshot.model_dump(mode="json")
    anchor_profile = InferenceTransferProfile.model_validate(seal(profile_raw, "profile_sha256"))
    raw["request"]["anchor"]["profile"] = InferenceTransferProfilePointer.from_profile(
        anchor_profile
    ).model_dump(mode="json")
    entry_raw = embedding_entry("b").model_dump(mode="json")
    entry_raw["profile"]["source_basis"]["graph_snapshot"] = base.graph_snapshot.model_dump(
        mode="json"
    )
    entry_raw["profile"] = seal(entry_raw["profile"], "profile_sha256")
    candidate_entry = StagedExperimentEntry.model_validate(entry_raw)
    raw["candidates"][0]["profile"] = InferenceTransferProfilePointer.from_profile(
        candidate_entry.profile
    ).model_dump(mode="json")
    raw["request"] = seal(raw["request"], "request_sha256")
    context = parse_similarity_context(seal(raw, "context_sha256"))
    delivery = parse_similarity_context_delivery(delivery_body(context))
    plan = bind_similarity_execution_plan(base, delivery, context)
    fixture.update(
        base=base,
        context=context,
        delivery=delivery,
        plan=plan,
        original_source=original,
        anchor_profile=anchor_profile,
        reference_entries=(candidate_entry,),
    )
    return fixture
