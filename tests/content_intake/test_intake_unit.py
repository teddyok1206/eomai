from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_contracts import (
    HumanDecision,
    IntakeManifest,
    MappingProposal,
    UncertaintiesDocument,
    validate_contract,
)
from eom_catalog_service.artifacts import normalize_catalog_idempotency_key
from eom_catalog_service.intake_files import (
    REQUIRED_ANALYSIS_HEADINGS,
    discover_source_files,
    load_strict_json,
    load_strict_yaml,
    source_fingerprint,
    validate_analysis_markdown,
)
from eom_catalog_service.intake_service import (
    IntakeSourceDeclaration,
    _require_exact_replay,
    _source_declarations,
)
from eom_content_intake import IntakeError, IntakeErrorCode, IntakeState, require_transition
from pydantic import ValidationError


def _analysis(path: Path) -> Path:
    path.write_text(
        "\n\nPLACEHOLDER_CONTENT\n\n".join(REQUIRED_ANALYSIS_HEADINGS), encoding="utf-8"
    )
    return path


def _proposal(batch_id: str) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "proposal": {
            "key": "proposal_placeholder_001",
            "source_batch_id": batch_id,
            "analysis_source_type": "MANUAL_EXTERNAL_ANALYSIS",
            "created_by": "operator_01",
            "created_at": "2026-08-17T00:00:00Z",
        },
        "changes": {
            "taxonomies": {"add": [], "update": [], "retire": []},
            "item_types": {"add": [], "update": []},
            "profiles": {
                "authoring": {"add": [], "update": []},
                "review": {"add": [], "update": []},
                "image": {"add": [], "update": []},
                "registration": {"add": [], "update": []},
            },
            "prompt_templates": {"add": [], "update": []},
            "metadata_schemas": {"add": [], "update": []},
            "rubrics": {"add": [], "update": []},
        },
        "uncertainties": [],
        "excluded": [],
    }


def test_intake_contracts_validate_and_reject_unknown_fields() -> None:
    batch_id = "intake_" + "1" * 32
    manifest = {
        "schema_version": "1.0",
        "batch_id": batch_id,
        "batch_name": "PLACEHOLDER_SOURCE_BATCH",
        "received_at": "2026-08-17T00:00:00Z",
        "received_by": "operator_01",
        "source_owner": {
            "type": "internal_team_member",
            "reference": "team_lead_placeholder",
        },
        "purpose": "PLACEHOLDER_PURPOSE",
        "files": [
            {
                "source_file_id": "sourcefile_" + "2" * 32,
                "relative_path": "source/PLACEHOLDER_FILE.txt",
                "original_filename": "PLACEHOLDER_FILE.txt",
                "media_type": "text/plain",
                "size_bytes": 1,
                "sha256": "sha256:" + "3" * 64,
                "declared_role": "REFERENCE",
                "declared_description": "PLACEHOLDER_DESCRIPTION",
            }
        ],
    }
    validate_contract("intake-manifest", manifest)
    assert IntakeManifest.model_validate(manifest).batch_id == batch_id
    proposal = _proposal(batch_id)
    validate_contract("mapping-proposal", proposal)
    assert MappingProposal.model_validate(proposal).proposal.source_batch_id == batch_id
    uncertainties = {"schema_version": "1.0", "batch_id": batch_id, "items": []}
    validate_contract("uncertainties", uncertainties)
    assert UncertaintiesDocument.model_validate(uncertainties).items == ()
    decision = {
        "schema_version": "1.0",
        "batch_id": batch_id,
        "proposal_key": "proposal_placeholder_001",
        "decision": "ACCEPT",
        "decided_by": "operator_01",
        "decided_at": "2026-08-17T00:00:00Z",
        "accepted_change_keys": [],
        "rejected_change_keys": [],
        "required_corrections": [],
        "notes": "PLACEHOLDER_DECISION_NOTES",
    }
    validate_contract("human-decision", decision)
    assert HumanDecision.model_validate(decision).decision == "ACCEPT"
    with pytest.raises(ValidationError):
        IntakeManifest.model_validate({**manifest, "unexpected": True})


def test_source_discovery_hash_and_deterministic_fingerprint(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "PLACEHOLDER_FILE.txt").write_text("PLACEHOLDER_CONTENT", encoding="utf-8")
    nested = source / "nested"
    nested.mkdir()
    (nested / "PLACEHOLDER_METADATA.json").write_text("{}", encoding="utf-8")
    first = discover_source_files(source)
    second = discover_source_files(source)
    assert [file.normalized_relative_path for file in first] == [
        "PLACEHOLDER_FILE.txt",
        "nested/PLACEHOLDER_METADATA.json",
    ]
    assert source_fingerprint(first) == source_fingerprint(second)
    assert all(file.sha256.startswith("sha256:") for file in first)


def test_reviewed_source_declarations_must_exactly_cover_materialized_files(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / ("legacyentry_" + "a" * 32 + ".pdf")).write_bytes(b"%PDF-1.7\nsynthetic\n%%EOF\n")
    discovered = discover_source_files(source)
    declaration = IntakeSourceDeclaration(
        normalized_relative_path=discovered[0].normalized_relative_path,
        original_filename="reviewed-original.pdf",
        media_type="application/pdf",
        declared_role="GUIDELINE",
        declared_description="reviewed legacy source",
    )

    resolved = _source_declarations(discovered, (declaration,))

    assert resolved[declaration.normalized_relative_path] == declaration
    with pytest.raises(IntakeError, match="do not match"):
        _source_declarations(
            discovered,
            (
                IntakeSourceDeclaration(
                    normalized_relative_path="different.pdf",
                    original_filename="reviewed-original.pdf",
                    media_type="application/pdf",
                    declared_role="GUIDELINE",
                    declared_description="reviewed legacy source",
                ),
            ),
        )


def test_reviewed_source_replay_requires_exact_semantic_metadata(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "legacyentry_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.pdf").write_bytes(
        b"%PDF-1.7\nsynthetic\n%%EOF\n"
    )
    discovered = discover_source_files(source)
    declaration = IntakeSourceDeclaration(
        normalized_relative_path=discovered[0].normalized_relative_path,
        original_filename="reviewed-original.pdf",
        media_type="application/pdf",
        declared_role="GUIDELINE",
        declared_description="reviewed legacy source",
    )
    batch = SimpleNamespace(
        batch_name="legacy-selection",
        received_by="operator_01",
        purpose="reviewed purpose",
        source_owner_type="legacy_system",
        source_owner_reference="reviewed_owner",
    )
    row = SimpleNamespace(
        relative_path=f"source/{discovered[0].normalized_relative_path}",
        original_filename=declaration.original_filename,
        normalized_filename=discovered[0].normalized_filename,
        media_type=declaration.media_type,
        size_bytes=discovered[0].size_bytes,
        sha256=discovered[0].sha256,
        declared_role=declaration.declared_role,
        declared_description=declaration.declared_description,
    )

    _require_exact_replay(
        batch,  # type: ignore[arg-type]
        (row,),  # type: ignore[arg-type]
        sources=discovered,
        declarations={declaration.normalized_relative_path: declaration},
        batch_name=batch.batch_name,
        received_by=batch.received_by,
        purpose=batch.purpose,
        source_owner_type=batch.source_owner_type,
        source_owner_reference=batch.source_owner_reference,
    )
    row.declared_role = "REFERENCE"
    with pytest.raises(IntakeError) as conflict:
        _require_exact_replay(
            batch,  # type: ignore[arg-type]
            (row,),  # type: ignore[arg-type]
            sources=discovered,
            declarations={declaration.normalized_relative_path: declaration},
            batch_name=batch.batch_name,
            received_by=batch.received_by,
            purpose=batch.purpose,
            source_owner_type=batch.source_owner_type,
            source_owner_reference=batch.source_owner_reference,
        )
    assert conflict.value.code == IntakeErrorCode.CONTENT_INTAKE_IMMUTABLE


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo"])
def test_source_discovery_rejects_non_regular_or_linked_input(tmp_path: Path, kind: str) -> None:
    source = tmp_path / "source"
    source.mkdir()
    original = source / "PLACEHOLDER_FILE.txt"
    original.write_text("PLACEHOLDER_CONTENT", encoding="utf-8")
    if kind == "symlink":
        (source / "link.txt").symlink_to(original)
    elif kind == "hardlink":
        os.link(original, source / "hardlink.txt")
    else:
        os.mkfifo(source / "pipe")
    with pytest.raises(IntakeError):
        discover_source_files(source)


def test_source_discovery_rejects_unicode_case_collision_and_secret(tmp_path: Path) -> None:
    source = tmp_path / "unicode"
    source.mkdir()
    (source / "PLACEHOLDER.txt").write_text("one", encoding="utf-8")
    (source / "placeholder.TXT").write_text("two", encoding="utf-8")
    with pytest.raises(IntakeError, match="collide"):
        discover_source_files(source)

    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / "credential.txt").write_text(
        "-----BEGIN OPENSSH " + "PRIVATE KEY-----\nPLACEHOLDER", encoding="utf-8"
    )
    with pytest.raises(IntakeError, match="secret"):
        discover_source_files(secret)


def test_strict_analysis_yaml_json_markdown(tmp_path: Path) -> None:
    report = _analysis(tmp_path / "analysis.md")
    assert "PLACEHOLDER_CONTENT" in validate_analysis_markdown(report)
    report.write_text("# 분석 개요\n<script>alert(1)</script>", encoding="utf-8")
    with pytest.raises(IntakeError):
        validate_analysis_markdown(report)

    yaml_path = tmp_path / "proposal.yaml"
    yaml_path.write_text("schema_version: '1.0'\nschema_version: '1.0'\n", encoding="utf-8")
    with pytest.raises(IntakeError, match="duplicate"):
        load_strict_yaml(yaml_path)
    yaml_path.write_text("value:\n  shell: PLACEHOLDER\n", encoding="utf-8")
    with pytest.raises(IntakeError, match="executable"):
        load_strict_yaml(yaml_path)

    json_path = tmp_path / "uncertainties.json"
    json_path.write_text('{"schema_version":"1.0","schema_version":"1.0"}', encoding="utf-8")
    with pytest.raises(IntakeError, match="duplicate"):
        load_strict_json(json_path)


def test_intake_state_machine_accept_reject_supersede_and_invalid_transition() -> None:
    require_transition(IntakeState.RECEIVED, IntakeState.HASHED)
    require_transition(IntakeState.NEEDS_DECISION, IntakeState.ACCEPTED)
    require_transition(IntakeState.NEEDS_DECISION, IntakeState.REJECTED)
    require_transition(IntakeState.NEEDS_DECISION, IntakeState.SUPERSEDED)
    with pytest.raises(IntakeError, match="invalid intake transition"):
        require_transition(IntakeState.ACCEPTED, IntakeState.RECEIVED)


def test_timestamp_must_be_utc() -> None:
    decision = {
        "batch_id": "intake_" + "1" * 32,
        "proposal_key": "proposal_placeholder_001",
        "decision": "ACCEPT",
        "decided_by": "operator_01",
        "decided_at": datetime(2026, 8, 17),
        "accepted_change_keys": [],
        "rejected_change_keys": [],
        "required_corrections": [],
        "notes": "PLACEHOLDER_DECISION_NOTES",
    }
    with pytest.raises(Exception, match="UTC"):
        HumanDecision.model_validate(decision)
    assert datetime.now(UTC).utcoffset() is not None


def test_catalog_idempotency_key_is_bounded_and_deterministic() -> None:
    long_key = "content-intake-analysis:" + "a" * 160
    normalized = normalize_catalog_idempotency_key(long_key)
    assert len(normalized) <= 128
    assert normalized == normalize_catalog_idempotency_key(long_key)
    assert normalized != normalize_catalog_idempotency_key(long_key + "b")
    assert normalize_catalog_idempotency_key("short-key") == "short-key"
