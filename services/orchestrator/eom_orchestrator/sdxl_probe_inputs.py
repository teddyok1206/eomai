"""Read-only admission and bounded materialization of exact SDXL diagnostic inputs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TypeVar

from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceCorpusTrainingAuthorization,
    LocalImageScienceCorpusVisualPilotPlanV3,
    LocalImageScienceCorpusVisualPilotResult,
    LocalImageScienceObjectLineArtCropSet,
    LocalImageScienceObjectLineArtSuitabilityReview,
    LocalImageScienceVisualCampaignPatternInventory,
    LocalImageSdxlLineartProbeCommand,
    LocalImageSdxlLineartPromptPolicy,
    ScienceObjectLineArtCropMember,
    SdxlLineartProbeCase,
    content_json_bytes,
    validate_contract,
    validate_science_object_line_art_crop_set,
    validate_science_visual_authorization_plan,
)
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel
from sqlalchemy import Engine

from eom_orchestrator.control_artifact_resolution import resolve_control_artifact_member

_Document = TypeVar("_Document", bound=BaseModel)
_MAX_METADATA_BYTES = 16 * 1024**2
_MAX_PNG_BYTES = 16 * 1024**2


class SdxlProbeAdmissionError(ValueError):
    """Invalid source/policy lineage, before dispatch or persistence."""


@dataclass(frozen=True, slots=True)
class SdxlProbeInputMember:
    member_path: str
    sha256: str
    payload: bytes


@dataclass(frozen=True, slots=True)
class PreparedSdxlProbeInputs:
    """Temporary input-boundary bytes, not canonical identity or persistent DB content."""

    command: LocalImageSdxlLineartProbeCommand
    files: tuple[SdxlProbeInputMember, ...]


@dataclass(frozen=True, slots=True)
class ResolvedSdxlTrainingSources:
    """One validated source lineage shared by diagnostic and micro-training admission."""

    crop_set: LocalImageScienceObjectLineArtCropSet
    crop_set_payload: bytes
    authorization_payload: bytes
    authorization: LocalImageScienceCorpusTrainingAuthorization
    inventory: LocalImageScienceVisualCampaignPatternInventory
    plans: tuple[LocalImageScienceCorpusVisualPilotPlanV3, ...]
    results: tuple[LocalImageScienceCorpusVisualPilotResult, ...]


@dataclass(frozen=True, slots=True)
class ResolvedSdxlProbeSources:
    policy: LocalImageSdxlLineartPromptPolicy
    policy_payload: bytes
    crop_set: LocalImageScienceObjectLineArtCropSet
    selected: tuple[tuple[SdxlLineartProbeCase, ScienceObjectLineArtCropMember], ...]


class _ResolvedDocuments:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.payloads: dict[ImageEvaluationArtifactMember, bytes] = {}

    def load(
        self,
        pointer: ImageEvaluationArtifactMember,
        contract: str,
        schema_ref: str,
        model: type[_Document],
    ) -> _Document:
        if pointer.schema_ref != schema_ref or pointer.media_type != "application/json":
            raise SdxlProbeAdmissionError("SDXL_PROBE_SOURCE_CONTRACT_INVALID")
        raw = self.payloads.get(pointer)
        if raw is None:
            raw = resolve_control_artifact_member(
                self.engine, pointer, maximum_bytes=_MAX_METADATA_BYTES
            )
            self.payloads[pointer] = raw
        try:
            value = json.loads(raw)
            validate_contract(contract, value)
            document = model.model_validate(value)
            canonical = content_json_bytes(document.model_dump(mode="json"))
            # Published historical pilot receipts retain one terminal newline. Their exact
            # pointer hash is already checked; never rewrite those bytes to admit a new run.
            accepted = (
                (canonical,)
                if contract == "sdxl-lineart-prompt-policy"
                else (canonical, canonical + b"\n")
            )
            if raw not in accepted:
                raise ValueError("noncanonical control input")
            return document
        except (ValueError, TypeError, JsonSchemaValidationError) as exc:
            raise SdxlProbeAdmissionError("SDXL_PROBE_SOURCE_DOCUMENT_INVALID") from exc


def resolve_sdxl_training_sources(
    engine: Engine,
    *,
    crop_set_pointer: ImageEvaluationArtifactMember,
    authorization_pointer: ImageEvaluationArtifactMember,
) -> ResolvedSdxlTrainingSources:
    """Check the complete historical provenance once, before any PNG materialization."""
    documents = _ResolvedDocuments(engine)
    prefix = "eom://schemas/image-provider/"
    crop_set = documents.load(
        crop_set_pointer,
        "science-object-line-art-crop-set",
        prefix + "local-image-science-object-line-art-crop-set/1.0",
        LocalImageScienceObjectLineArtCropSet,
    )
    if crop_set.training_authorization != authorization_pointer:
        raise SdxlProbeAdmissionError("SDXL_PROBE_AUTHORIZATION_POINTER_INVALID")
    authorization = documents.load(
        authorization_pointer,
        "science-corpus-training-authorization",
        prefix + "local-image-science-corpus-training-authorization/1.0",
        LocalImageScienceCorpusTrainingAuthorization,
    )
    inventory = documents.load(
        crop_set.pattern_inventory,
        "science-visual-campaign-pattern-inventory",
        prefix + "local-image-science-visual-campaign-pattern-inventory/1.0",
        LocalImageScienceVisualCampaignPatternInventory,
    )
    review = documents.load(
        crop_set.line_art_suitability_review,
        "science-object-line-art-suitability-review",
        prefix + "local-image-science-object-line-art-suitability-review/1.0",
        LocalImageScienceObjectLineArtSuitabilityReview,
    )
    plans, results = [], []
    for pilot in inventory.pilot_results:
        plan = documents.load(
            pilot.pilot_plan,
            "science-corpus-visual-pilot-plan-v3",
            prefix + "local-image-science-corpus-visual-pilot-plan/1.2",
            LocalImageScienceCorpusVisualPilotPlanV3,
        )
        result = documents.load(
            pilot.pilot_result,
            "science-corpus-visual-pilot-result",
            prefix + "local-image-science-corpus-visual-pilot-result/1.0",
            LocalImageScienceCorpusVisualPilotResult,
        )
        plans.append(plan)
        results.append(result)
    try:
        for plan in plans:
            validate_science_visual_authorization_plan(authorization, plan)
        validate_science_object_line_art_crop_set(
            plans=tuple(plans),
            plan_pointers=tuple(pilot.pilot_plan for pilot in inventory.pilot_results),
            results=tuple(results),
            result_pointers=tuple(pilot.pilot_result for pilot in inventory.pilot_results),
            inventory=inventory,
            review=review,
            crop_set=crop_set,
        )
    except ValueError as exc:
        raise SdxlProbeAdmissionError("SDXL_PROBE_SOURCE_LINEAGE_INVALID") from exc
    return ResolvedSdxlTrainingSources(
        crop_set,
        documents.payloads[crop_set_pointer],
        documents.payloads[authorization_pointer],
        authorization,
        inventory,
        tuple(plans),
        tuple(results),
    )


def resolve_sdxl_probe_sources(
    engine: Engine, command: LocalImageSdxlLineartProbeCommand
) -> ResolvedSdxlProbeSources:
    """Resolve exact approved provenance and TRAIN inputs, without dispatch or DB writes."""
    validate_contract("sdxl-lineart-probe-command", command.model_dump(mode="json"))
    if command.style_track != "OBJECT_LINE_ART":
        raise SdxlProbeAdmissionError("SDXL_PROBE_SOURCE_CONTRACT_INVALID")
    documents = _ResolvedDocuments(engine)
    prefix = "eom://schemas/image-provider/"
    policy = documents.load(
        command.prompt_policy,
        "sdxl-lineart-prompt-policy",
        prefix + "local-image-sdxl-lineart-prompt-policy/1.0",
        LocalImageSdxlLineartPromptPolicy,
    )
    if (
        policy.cases != command.cases
        or policy.experiment_authorization.approved_at > command.created_at
    ):
        raise SdxlProbeAdmissionError("SDXL_PROBE_PROMPT_PROVENANCE_INVALID")
    sources = resolve_sdxl_training_sources(
        engine,
        crop_set_pointer=policy.crop_set,
        authorization_pointer=policy.training_authorization,
    )
    crop_set = sources.crop_set

    members = {member.member_path: member for member in crop_set.members}
    references = set()
    depictions = set()
    selected = []
    # Admit the entire input set before materializing any image; a late bad case cannot
    # leave a partial valid-looking handoff for the isolated provider.
    for case in command.cases:
        pointer = case.reference_image
        member = members.get(pointer.member_path)
        if (
            member is None
            or pointer.artifact_id != policy.crop_set.artifact_id
            or pointer.artifact_revision_id != policy.crop_set.artifact_revision_id
            or pointer.schema_ref != prefix + "local-image-science-visual-crop/1.0"
            or pointer.sha256 != member.sha256
            or member.partition != "TRAIN"
            or (case.reference_width_px, case.reference_height_px)
            != (member.width_px, member.height_px)
            or member.size_bytes > _MAX_PNG_BYTES
            or pointer in references
            or case.depiction_key in depictions
        ):
            raise SdxlProbeAdmissionError("SDXL_PROBE_REFERENCE_SOURCE_INVALID")
        references.add(pointer)
        depictions.add(case.depiction_key)
        selected.append((case, member))
    return ResolvedSdxlProbeSources(
        policy, documents.payloads[command.prompt_policy], crop_set, tuple(selected)
    )


def materialize_sdxl_probe_inputs(
    engine: Engine, command: LocalImageSdxlLineartProbeCommand, sources: ResolvedSdxlProbeSources
) -> PreparedSdxlProbeInputs:
    files = []
    for case, member in sources.selected:
        payload = resolve_control_artifact_member(
            engine, case.reference_image, maximum_bytes=member.size_bytes
        )
        if len(payload) != member.size_bytes:
            raise SdxlProbeAdmissionError("SDXL_PROBE_REFERENCE_SIZE_INVALID")
        files.append(SdxlProbeInputMember(case.staged_member_path, member.sha256, payload))
    for name, payload in (
        ("command.json", content_json_bytes(command.model_dump(mode="json"))),
        ("inputs/prompt-policy.json", sources.policy_payload),
    ):
        files.append(
            SdxlProbeInputMember(name, "sha256:" + hashlib.sha256(payload).hexdigest(), payload)
        )
    return PreparedSdxlProbeInputs(
        command, tuple(sorted(files, key=lambda member: member.member_path))
    )


def prepare_sdxl_probe_inputs(
    engine: Engine, command: LocalImageSdxlLineartProbeCommand
) -> PreparedSdxlProbeInputs:
    sources = resolve_sdxl_probe_sources(engine, command)
    return materialize_sdxl_probe_inputs(engine, command, sources)
