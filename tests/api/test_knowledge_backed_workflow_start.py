from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_api.services.catalog_application_client import CatalogApplicationClientError
from eom_api.services.command_adapter import CommandAdapter
from eom_api_contracts.workflows import WorkflowStartRequest
from eom_catalog_contracts import CreateItemProductionEvidenceCommand, EvidenceBudget
from eom_operator_identity import (
    ActorContext,
    ActorSource,
    ActorType,
    PermissionKey,
)
from eom_workflow import compile_definition
from eom_workflow_runner.models import WorkflowInstanceRecord

ROOT = Path(__file__).resolve().parents[2]


def _request(definition_version: str = "1.8.0") -> WorkflowStartRequest:
    if definition_version in {"1.11.0", "1.12.0", "1.13.0"}:
        return WorkflowStartRequest.model_validate(
            {
                "definition_key": "generic-item-development",
                "definition_version": definition_version,
                "request_name": "GENERATED_KNOWLEDGE_ITEM_REQUEST",
                "image_mode": "skip",
                "pack_key": "generated-knowledge-item",
                "execution_preset_key": "knowledge-grounded-item",
                "item_brief": {
                    "schema_version": "4.0",
                    "subject": "통합과학",
                    "topic": "시간과 공간에서 물체의 운동 분석",
                    "task_type": "TEXT",
                    "difficulty": "중",
                    "authoring_guidance": (
                        "통합과학 시간과 공간 범위에서 자료를 해석하는 문항을 출제한다."
                    ),
                    "authoring_guidance_sha256": (
                        "sha256:038af27cedd6eab2a978f5d9c8d647eed36d455b52d41aca01ec2c5f5e1fd228"
                    ),
                    "curriculum_selected_unit_key": "eom.is.middle.1-1",
                    "mock_exam_slot": None,
                    "material_requirement": {
                        "schema_version": "content-team-material-requirement/1.0",
                        "form": "TABLE",
                        "panel_count": 1,
                    },
                    "original_request_sha256": (
                        "038af27cedd6eab2a978f5d9c8d647eed36d455b52d41aca01ec2c5f5e1fd228"
                    ),
                },
                "educational_retrieval": {
                    "schema_version": "educational-retrieval-requirement/1.0",
                    "corpus_key": "integrated-science-textbooks",
                    "query_kind": "ITEM_PREPARATION",
                    "curriculum_root_key": None,
                    "topic_keys": [],
                    "required_item_elements": ["choice", "paragraph", "table"],
                    "source_classes": ["PAST_EXAM"],
                },
            }
        )
    return WorkflowStartRequest.model_validate(
        {
            "definition_key": "generic-item-development",
            "definition_version": "1.8.0",
            "request_name": "GENERATED_KNOWLEDGE_ITEM_REQUEST",
            "image_mode": "required",
            "pack_key": "generated-knowledge-item",
            "execution_preset_key": "knowledge-grounded-item",
            "item_brief": {
                "subject": "통합과학",
                "topic": "판 경계",
                "task_type": "data_interpretation",
                "difficulty": "hard",
                "choice_count": 5,
                "equation_required": True,
                "image_required": True,
                "quality_profile": "deep",
                "original_request_sha256": "0" * 64,
            },
            "educational_retrieval": {
                "schema_version": "educational-retrieval-requirement/1.0",
                "corpus_key": "science-core",
                "query_kind": "ITEM_PREPARATION",
                "curriculum_root_key": "earth.plate-boundary",
                "topic_keys": ["earth.plate-boundary"],
                "required_item_elements": ["statement_set", "table"],
                "source_classes": ["APPROVED_ITEM", "TEXTBOOK"],
            },
        }
    )


class _ReadSession:
    def __init__(self, definition: object) -> None:
        self.definition = definition

    def __enter__(self) -> _ReadSession:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def scalar(self, _statement: object) -> object:
        descriptions = getattr(_statement, "column_descriptions", ())
        if descriptions and descriptions[0].get("entity") is WorkflowInstanceRecord:
            return None
        return self.definition


class _GraphMissCatalog:
    def __init__(self) -> None:
        self.command: CreateItemProductionEvidenceCommand | None = None

    def create_item_production_evidence(self, command: CreateItemProductionEvidenceCommand) -> None:
        self.command = command
        raise CatalogApplicationClientError("KNOWLEDGE_RETRIEVAL_CORPUS_UNAVAILABLE", "graph miss")


@pytest.mark.parametrize(
    ("definition_version", "expected_solution_requirement"),
    (
        ("1.8.0", "NONE"),
        ("1.11.0", "REQUIRE_ACCEPTED_SOLUTION_REPORT"),
        ("1.12.0", "REQUIRE_ACCEPTED_SOLUTION_REPORT"),
        ("1.13.0", "REQUIRE_ACCEPTED_SOLUTION_REPORT"),
    ),
)
def test_graph_miss_happens_before_workflow_transaction_or_worker_claim_and_pins_solution_policy(
    monkeypatch: pytest.MonkeyPatch,
    definition_version: str,
    expected_solution_requirement: str,
) -> None:
    definition_name = "generic-item-development.v" + definition_version.removesuffix(".0") + ".yaml"
    compiled = compile_definition(
        ROOT / "config" / "workflows" / definition_name,
        {"authoring", "image", "review", "item_management"},
    )
    definition = SimpleNamespace(
        canonical_definition=compiled.as_dict(),
        source_path=compiled.source_path,
        definition_hash=compiled.sha256,
    )
    adapter = object.__new__(CommandAdapter)
    adapter.sessions = lambda: _ReadSession(definition)  # type: ignore[method-assign]
    catalog = _GraphMissCatalog()
    adapter.catalog_application = catalog  # type: ignore[assignment]
    retrieval_policy = SimpleNamespace(
        maximum_budget=EvidenceBudget(
            max_documents=2,
            max_item_revisions=2,
            max_graph_nodes=8,
            max_claims=2,
            max_context_tokens=2000,
        ),
        access_policy_revision_id="accessrev_" + "1" * 32,
        access_policy_sha256="sha256:" + "1" * 64,
    )
    preset = SimpleNamespace(
        preset_revision_id="execpresetrev_" + "2" * 32,
        retrieval_policy=retrieval_policy,
    )
    monkeypatch.setattr(
        "eom_api.services.command_adapter.current_knowledge_backed_preset",
        lambda *_args, **_kwargs: preset,
    )
    monkeypatch.setattr(
        "eom_api.services.command_adapter.validate_educational_retrieval_policy",
        lambda *_args, **_kwargs: None,
    )
    transaction_started = False

    @contextmanager
    def forbidden_transaction(*_args: object, **_kwargs: object):
        nonlocal transaction_started
        transaction_started = True
        raise AssertionError("graph miss must not start a workflow transaction")
        yield

    monkeypatch.setattr("eom_api.services.command_adapter.transaction", forbidden_transaction)
    actor = ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id="operator_" + "3" * 32,
        session_id="apisession_" + "4" * 32,
        request_id="request_" + "5" * 32,
        authentication_time=datetime(2026, 8, 24, 3, 0, tzinfo=UTC),
        permissions=frozenset(PermissionKey),
        source=ActorSource.APPLICATION_API,
    )
    with pytest.raises(CatalogApplicationClientError) as captured:
        adapter.start_workflow(
            _request(definition_version), actor, idempotency_key="api:" + "6" * 64
        )
    assert captured.value.code == "KNOWLEDGE_RETRIEVAL_CORPUS_UNAVAILABLE"
    assert catalog.command is not None
    assert catalog.command.solution_evidence_requirement == expected_solution_requirement
    assert not transaction_started
