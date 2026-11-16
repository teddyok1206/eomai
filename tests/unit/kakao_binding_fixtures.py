"""Anonymous binding views shared by API/BFF transport tests; no live account data."""

from datetime import UTC, datetime

from eom_catalog_contracts.kakao_archive_binding import (
    KakaoBindingCreate,
    KakaoBindingRetire,
    KakaoCollectionPolicy,
    KakaoCollectionPolicyRevision,
    KakaoSourceBinding,
    collection_policy_sha256,
)

BINDING_ID = "kakaobinding_" + "1" * 32
POLICY_ID = "kakaopolicyrev_" + "2" * 32
NOW = datetime(2026, 11, 16, tzinfo=UTC)
KEY = "kakao-fixture-command-0001"


def source_binding(*, retired: bool = False) -> KakaoSourceBinding:
    policy = KakaoCollectionPolicy()
    return KakaoSourceBinding(
        source_binding_id=BINDING_ID,
        display_name="익명 연결",
        state="RETIRED" if retired else "DRAFT",
        resource_version=2 if retired else 1,
        policy_revision=KakaoCollectionPolicyRevision(
            source_binding_id=BINDING_ID,
            policy_revision_id=POLICY_ID,
            previous_revision_id=None,
            revision_number=1,
            sha256=collection_policy_sha256(policy),
            policy=policy,
            created_at=NOW,
        ),
        created_at=NOW,
        updated_at=NOW,
    )


def create_command() -> KakaoBindingCreate:
    return KakaoBindingCreate(display_name="익명 연결", policy=KakaoCollectionPolicy())


def retire_command() -> KakaoBindingRetire:
    return KakaoBindingRetire(parent_policy_revision_id=POLICY_ID, expected_resource_version=1)
