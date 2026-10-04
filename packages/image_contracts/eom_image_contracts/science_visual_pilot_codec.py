"""Closed pilot-version codec shared by staging, isolated worker and result admission."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from eom_image_contracts.models import ImageEvaluationArtifactMember, content_sha256
from eom_image_contracts.science_corpus_visual import (
    LocalImageScienceCorpusVisualPilotCommand,
    LocalImageScienceCorpusVisualPilotCommandV2,
    LocalImageScienceCorpusVisualPilotCommandV3,
    LocalImageScienceCorpusVisualPilotPlan,
    LocalImageScienceCorpusVisualPilotPlanV2,
    LocalImageScienceCorpusVisualPilotPlanV3,
    validate_science_visual_pilot_command,
)
from eom_image_contracts.science_visual_expansion import (
    LocalImageScienceCorpusVisualPilotCommandV4,
    LocalImageScienceCorpusVisualPilotPlanV4,
    validate_science_visual_expansion_command,
)
from eom_image_contracts.validation import validate_contract

ScienceVisualPilotPlan = (
    LocalImageScienceCorpusVisualPilotPlan
    | LocalImageScienceCorpusVisualPilotPlanV2
    | LocalImageScienceCorpusVisualPilotPlanV3
    | LocalImageScienceCorpusVisualPilotPlanV4
)
ScienceVisualPilotCommand = (
    LocalImageScienceCorpusVisualPilotCommand
    | LocalImageScienceCorpusVisualPilotCommandV2
    | LocalImageScienceCorpusVisualPilotCommandV3
    | LocalImageScienceCorpusVisualPilotCommandV4
)


@dataclass(frozen=True, slots=True)
class _PilotProtocol:
    version: str
    plan_model: type[ScienceVisualPilotPlan]
    command_model: type[ScienceVisualPilotCommand]
    plan_contract: str
    command_contract: str


_PROTOCOLS = (
    _PilotProtocol(
        "1.0",
        LocalImageScienceCorpusVisualPilotPlan,
        LocalImageScienceCorpusVisualPilotCommand,
        "science-corpus-visual-pilot-plan",
        "science-corpus-visual-pilot-command",
    ),
    _PilotProtocol(
        "1.1",
        LocalImageScienceCorpusVisualPilotPlanV2,
        LocalImageScienceCorpusVisualPilotCommandV2,
        "science-corpus-visual-pilot-plan-v2",
        "science-corpus-visual-pilot-command-v2",
    ),
    _PilotProtocol(
        "1.2",
        LocalImageScienceCorpusVisualPilotPlanV3,
        LocalImageScienceCorpusVisualPilotCommandV3,
        "science-corpus-visual-pilot-plan-v3",
        "science-corpus-visual-pilot-command-v3",
    ),
    _PilotProtocol(
        "1.3",
        LocalImageScienceCorpusVisualPilotPlanV4,
        LocalImageScienceCorpusVisualPilotCommandV4,
        "science-corpus-visual-pilot-plan-v4",
        "science-corpus-visual-pilot-command-v4",
    ),
)
_BY_PLAN_TYPE = MappingProxyType({protocol.plan_model: protocol for protocol in _PROTOCOLS})
_BY_COMMAND_TYPE = MappingProxyType({protocol.command_model: protocol for protocol in _PROTOCOLS})
_BY_COMMAND_VERSION = MappingProxyType(
    {
        "local-image-science-corpus-visual-pilot-command/" + protocol.version: protocol
        for protocol in _PROTOCOLS
    }
)


def parse_science_visual_pilot_command(value: object) -> ScienceVisualPilotCommand:
    if not isinstance(value, dict):
        raise ValueError("science visual pilot command must be an object")
    version = value.get("schema_version")
    if not isinstance(version, str) or version not in _BY_COMMAND_VERSION:
        raise ValueError("unsupported science visual pilot command version")
    protocol = _BY_COMMAND_VERSION[version]
    validate_contract(protocol.command_contract, value)
    return protocol.command_model.model_validate(value)


def parse_science_visual_pilot_plan(
    value: object,
    command: ScienceVisualPilotCommand,
) -> ScienceVisualPilotPlan:
    if not isinstance(value, dict):
        raise ValueError("science visual pilot plan must be an object")
    protocol = _BY_COMMAND_TYPE.get(type(command))
    if protocol is None:
        raise ValueError("unsupported science visual pilot command type")
    validate_contract(protocol.plan_contract, value)
    plan = protocol.plan_model.model_validate(value)
    if isinstance(plan, LocalImageScienceCorpusVisualPilotPlanV4):
        if not isinstance(command, LocalImageScienceCorpusVisualPilotCommandV4):
            raise ValueError("science visual expansion command version differs")
        validate_science_visual_expansion_command(plan, command)
    else:
        validate_science_visual_pilot_command(plan, command)
    return plan


def build_science_visual_pilot_command(
    *,
    plan: ScienceVisualPilotPlan,
    plan_pointer: ImageEvaluationArtifactMember,
    requested_at: datetime,
    requested_by: str,
) -> ScienceVisualPilotCommand:
    protocol = _BY_PLAN_TYPE.get(type(plan))
    if protocol is None:
        raise ValueError("unsupported science visual pilot plan type")
    body: dict[str, object] = {
        "schema_version": "local-image-science-corpus-visual-pilot-command/" + protocol.version,
        "plan": plan_pointer.model_dump(mode="json"),
        "plan_sha256": plan.plan_sha256,
        "staged_plan_member": "input/visual-pilot-plan.json",
        "staged_sources": [
            {
                "document_id": source.document_id,
                "staged_pdf_member": f"input/pdfs/{source.document_id}.pdf",
                "sha256": source.pdf.sha256,
                "bytes": source.bytes,
                "page_count": source.page_count,
            }
            for source in plan.selected_sources
        ],
        "result_member": "manifests/visual-pilot-result.json",
        "requested_at": requested_at.isoformat().replace("+00:00", "Z"),
        "requested_by": requested_by,
    }
    body["attempt_id"] = "imgscivisattempt_" + content_sha256(body)[7:39]
    body["command_sha256"] = content_sha256(body)
    validate_contract(protocol.command_contract, body)
    command = protocol.command_model.model_validate(body)
    parse_science_visual_pilot_plan(plan.model_dump(mode="json"), command)
    return command
