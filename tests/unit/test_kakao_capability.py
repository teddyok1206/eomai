"""Schema-first manual capability values do not grant automatic collection."""

from pathlib import Path

import pytest
from eom_catalog_contracts.kakao_capability import (
    CAPABILITY_VERIFICATION_REF,
    ConfirmKakaoCapability,
    KakaoCapabilityVerification,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES
from eom_catalog_service.kakao_capability_service import (
    capability_within_observed_evidence,
    manual_room_capability,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_kakao_archive_contracts.capture import validate_capture_contract

from tests.unit.test_kakao_room_intake import evidence


def command():
    return ConfirmKakaoCapability(
        source_binding_id="kakaobinding_" + "a" * 32,
        room_id="kakaoroom_" + "e" * 32,
        expected_binding_version=1,
    )


def pointer(schema, name):
    return dict(
        artifact_id="artifact_" + "1" * 32,
        artifact_revision_id="rev_" + "2" * 32,
        member_path=name,
        schema_ref=schema,
        media_type="application/json",
        sha256="sha256:" + "3" * 64,
    )


def verification():
    from eom_catalog_contracts.kakao_room_intake import MANUAL_ROOM_EVIDENCE_REF
    from eom_catalog_contracts.kakao_rooms import ROOM_OBSERVATION_REF

    request = command()
    return KakaoCapabilityVerification(
        request=request,
        request_sha256=sha256_bytes(canonical_json_bytes(request.model_dump(mode="json"))),
        created_by="operator_" + "f" * 32,
        capability_revision_id="kakaocapabilityrev_" + "4" * 32,
        adapter_release_sha256="sha256:" + "5" * 64,
        room_observation=pointer(ROOM_OBSERVATION_REF, "observation.json"),
        manual_proof=pointer(MANUAL_ROOM_EVIDENCE_REF, "proof.json"),
        capability_sha256="sha256:" + "6" * 64,
    )


def test_schema_hash_mirror_and_immutable_roundtrip():
    root = Path(__file__).resolve().parents[2]
    resource = CATALOG_SCHEMA_RESOURCES["kakao-capability-verification-v1"]
    raw = (root / resource.canonical_path).read_bytes()
    assert sha256_bytes(raw) == resource.sha256
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    value = verification()
    assert CAPABILITY_VERIFICATION_REF.endswith("/1.0")
    assert KakaoCapabilityVerification.model_validate_json(value.model_dump_json()) == value
    with pytest.raises(ValueError):
        value.request.expected_binding_version = 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("channel_verified", True),
        ("adapter_release_sha256", "sha256:" + "0" * 64),
        ("path", "/private"),
        ("role", "ADMIN"),
        ("schedule_enabled", True),
        ("expected_binding_version", True),
        ("room_id", "../other"),
    ],
)
def test_request_does_not_accept_capability_or_authority_claims(field, value):
    with pytest.raises(ValueError):
        ConfirmKakaoCapability.model_validate(command().model_dump() | {field: value})


def test_verification_requires_exact_request_and_schema_pointer():
    raw = verification().model_dump(mode="json")
    with pytest.raises(ValueError):
        KakaoCapabilityVerification.model_validate(raw | {"request_sha256": "sha256:" + "0" * 64})
    with pytest.raises(ValueError):
        KakaoCapabilityVerification.model_validate(raw | {"manual_proof": raw["room_observation"]})


def test_manual_capability_preserves_all_unmeasured_fields_as_unknown():
    from eom_catalog_contracts.kakao_room_intake import KakaoManualRoomEvidence

    proof = KakaoManualRoomEvidence.model_validate(evidence())
    raw = canonical_json_bytes(proof.model_dump(mode="json"))
    result = manual_room_capability(
        proof, raw, revision="kakaocapabilityrev_" + "7" * 32, adapter_sha256="sha256:" + "8" * 64
    )
    validate_capture_contract("capability", result.model_dump(mode="json"))
    assert result.channel_verified and result.room_identity == "manual_binding"
    for name in (
        "message_identity",
        "csv_scope",
        "csv_order",
        "source_timezone",
        "direction_evidence",
        "album_enumeration",
        "original_download",
        "opening_marks_read",
    ):
        assert getattr(result, name) == "unknown"
    assert result.visible_scope_ids == ("MANUAL_SELECTED_ROOM",)
    assert result.evidence[0].sha256 == sha256_bytes(raw)
    assert result.evidence[0].relative_path == "inputs/manual-room-proof.json"
    with pytest.raises(ValueError):
        manual_room_capability(
            proof,
            b"{}",
            revision=result.capability_revision_id,
            adapter_sha256=result.adapter_release_sha256,
        )


def test_historical_unknown_is_not_reinterpreted_or_stronger_than_its_evidence():
    from eom_catalog_contracts.kakao_room_intake import KakaoManualRoomEvidence

    proof = KakaoManualRoomEvidence.model_validate(evidence())
    raw = canonical_json_bytes(proof.model_dump(mode="json"))
    old = manual_room_capability(
        proof, raw, revision="kakaocapabilityrev_" + "7" * 32, adapter_sha256="sha256:" + "8" * 64
    )
    measured = old.model_copy(update={"source_timezone": "Asia/Seoul"})
    assert capability_within_observed_evidence(old, measured)
    assert old.source_timezone == "unknown"
    assert not capability_within_observed_evidence(measured, old)
    assert not capability_within_observed_evidence(
        old.model_copy(update={"adapter_release_sha256": "sha256:" + "9" * 64}), old
    )
