"""Identifier generation and deterministic JSON serialization."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4


def new_job_id() -> str:
    return f"job_{uuid4().hex}"


def new_logical_artifact_id() -> str:
    return f"artifact_{uuid4().hex}"


def new_revision_id() -> str:
    return f"rev_{uuid4().hex}"


def new_hwpx_template_id() -> str:
    return f"hwpxtpl_{uuid4().hex}"


def new_hwpx_template_revision_id() -> str:
    return f"hwpxrev_{uuid4().hex}"


def new_hwpx_build_id() -> str:
    return f"hwpxbuild_{uuid4().hex}"


def new_hwpx_validation_id() -> str:
    return f"hwpxval_{uuid4().hex}"


def new_instruction_bundle_id() -> str:
    return f"instrbundle_{uuid4().hex}"


def new_instruction_bundle_revision_id() -> str:
    return f"instrrev_{uuid4().hex}"


def new_reference_bundle_id() -> str:
    return f"refbundle_{uuid4().hex}"


def new_reference_bundle_revision_id() -> str:
    return f"refrev_{uuid4().hex}"


def new_execution_preset_id() -> str:
    return f"execpreset_{uuid4().hex}"


def new_execution_preset_revision_id() -> str:
    return f"execpresetrev_{uuid4().hex}"


def new_capacity_policy_id() -> str:
    return f"capacity_{uuid4().hex}"


def new_capacity_policy_revision_id() -> str:
    return f"capacityrev_{uuid4().hex}"


def new_execution_plan_id() -> str:
    return f"execplan_{uuid4().hex}"


def new_auth_binding_id() -> str:
    return f"authbinding_{uuid4().hex}"


def new_capability_snapshot_id() -> str:
    return f"capsnap_{uuid4().hex}"


def new_worker_lease_id() -> str:
    return f"workerlease_{uuid4().hex}"


def new_codex_control_command_id() -> str:
    return f"codexcmd_{uuid4().hex}"


def new_codex_auth_enrollment_id() -> str:
    return f"authflow_{uuid4().hex}"


def new_codex_auth_assignment_revision_id() -> str:
    return f"authassignrev_{uuid4().hex}"


def new_execution_preset_evaluation_id() -> str:
    return f"preseteval_{uuid4().hex}"


def new_knowledge_analysis_request_id() -> str:
    return f"knowledgeanalysis_{uuid4().hex}"


def new_knowledge_analysis_run_id() -> str:
    return f"analysisrun_{uuid4().hex}"


def new_knowledge_analysis_result_id() -> str:
    return f"knowledgeanalysisresult_{uuid4().hex}"


def new_knowledge_analysis_decision_id() -> str:
    return f"analysisdecision_{uuid4().hex}"


def new_knowledge_analysis_batch_id() -> str:
    return f"analysisbatch_{uuid4().hex}"


def new_knowledge_analysis_range_id() -> str:
    return f"analysisrange_{uuid4().hex}"


def new_organization_id() -> str:
    return f"org_{uuid4().hex}"


def new_organization_revision_id() -> str:
    return f"orgrev_{uuid4().hex}"


def new_assessment_occurrence_id() -> str:
    return f"occurrence_{uuid4().hex}"


def new_assessment_occurrence_revision_id() -> str:
    return f"occurrev_{uuid4().hex}"


def new_item_origin_profile_id() -> str:
    return f"originprofile_{uuid4().hex}"


def new_assessment_source_bundle_id() -> str:
    return f"assessbundle_{uuid4().hex}"


def new_assessment_source_bundle_revision_id() -> str:
    return f"assessbundlerev_{uuid4().hex}"


def new_assessment_source_bundle_member_id() -> str:
    return f"assessbundlemember_{uuid4().hex}"


def new_assessment_layout_observation_id() -> str:
    return f"assessmentlayout_{uuid4().hex}"


def new_legacy_item_extraction_request_id() -> str:
    return f"itemextractreq_{uuid4().hex}"


def new_legacy_item_extraction_result_id() -> str:
    return f"itemextractresult_{uuid4().hex}"


def new_legacy_item_acceptance_id() -> str:
    return f"itemacceptance_{uuid4().hex}"


def new_legacy_item_coverage_id() -> str:
    return f"itemcoverage_{uuid4().hex}"


def educational_document_id(document_key: str) -> str:
    """Return the stable logical ID for one normalized educational-document key."""
    digest = hashlib.sha256(f"educational-document:{document_key}".encode()).hexdigest()
    return f"edudoc_{digest[:32]}"


def educational_document_revision_id(registration_request_sha256: str) -> str:
    """Return a replay-stable immutable revision ID for one exact registration request."""
    digest = hashlib.sha256(
        f"educational-document-revision:{registration_request_sha256}".encode()
    ).hexdigest()
    return f"edudocrev_{digest[:32]}"


def educational_document_registration_id(registration_request_sha256: str) -> str:
    """Return the replay-stable saga ID for one exact document registration."""
    digest = hashlib.sha256(
        f"educational-document-registration:{registration_request_sha256}".encode()
    ).hexdigest()
    return f"edudocreg_{digest[:32]}"


def new_educational_document_rights_attestation_id() -> str:
    return f"edurights_{uuid4().hex}"


def _canonical_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="python")
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("canonical JSON object keys must be strings")
        return {key: _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("canonical timestamps must be timezone-aware")
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, Enum):
        return _canonical_value(value.value)
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        raise TypeError("floats are not allowed in canonical EOM messages")
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    canonical = _canonical_value(value)
    return json.dumps(
        canonical,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def content_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"
