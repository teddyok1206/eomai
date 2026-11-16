"""Bootstrap contracts cannot claim verified channel authority or accept private paths."""

from __future__ import annotations

import importlib.util
import io
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from eom_catalog_contracts.kakao_archive_binding import (
    KakaoBindingCommand,
    KakaoBindingCreate,
    KakaoBindingRetire,
    KakaoCollectionPolicy,
    KakaoCollectionPolicyRevision,
    KakaoSourceBinding,
    collection_policy_sha256,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, validate_contract
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError, authorize_kakao_actor
from eom_catalog_service.kakao_archive_models import (
    KakaoBindingCommandRecord,
    KakaoChannelBindingRecord,
    KakaoCollectionPolicyRevisionRecord,
)
from eom_identity_service.models import OperatorRecord
from eom_operator_identity.contracts import (
    ROLE_PERMISSIONS,
    ActorContext,
    ActorSource,
    ActorType,
    PermissionKey,
    RoleKey,
)
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.schema import CreateTable

ROOT = Path(__file__).resolve().parents[2]
BINDING = "kakaobinding_" + "a" * 32
POLICY = "kakaopolicyrev_" + "b" * 32


def binding_payload() -> dict:
    policy = KakaoCollectionPolicy()
    return {
        "source_binding_id": BINDING,
        "display_name": "질문 보관",
        "state": "DRAFT",
        "resource_version": 1,
        "policy_revision": {
            "source_binding_id": BINDING,
            "policy_revision_id": POLICY,
            "previous_revision_id": None,
            "revision_number": 1,
            "sha256": collection_policy_sha256(policy),
            "policy": policy.model_dump(mode="json"),
            "created_at": datetime(2026, 11, 16, tzinfo=UTC),
        },
        "created_at": datetime(2026, 11, 16, tzinfo=UTC),
        "updated_at": datetime(2026, 11, 16, tzinfo=UTC),
    }


def test_binding_bootstrap_contract_matches_registered_schema() -> None:
    view = KakaoSourceBinding.model_validate(binding_payload())
    assert view.schedule_enabled is False
    assert view.capability_state == "NOT_VERIFIED"
    assert view.policy_revision.policy.include_images is True
    validate_contract("kakao-source-binding-v1", view.model_dump(mode="json"))
    command = KakaoBindingCreate(display_name="질문 보관", policy=KakaoCollectionPolicy())
    validate_contract("kakao-source-binding-create-v1", command.model_dump(mode="json"))


@pytest.mark.parametrize(
    "name", ["source-binding", "source-binding-create", "source-binding-command"]
)
def test_binding_schema_resource_bytes_are_exact(name: str) -> None:
    resource = CATALOG_SCHEMA_RESOURCES[f"kakao-{name}-v1"]
    assert (ROOT / resource.canonical_path).read_bytes() == (
        ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
    ).read_bytes()


@pytest.mark.parametrize(
    "action", ["VERIFY_CHANNEL", "ENABLE_SCHEDULE", "DISABLE_SCHEDULE", "ACTIVE"]
)
def test_unimplemented_channel_authority_is_not_a_command(action: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(KakaoBindingCommand).validate_python(
            {
                "action": action,
                "parent_policy_revision_id": POLICY,
                "expected_resource_version": 1,
            }
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("state", "ACTIVE"),
        ("schedule_enabled", True),
        ("capability_state", "VERIFIED"),
        ("resource_version", True),
        ("display_name", "\nsecret"),
        ("display_name", "   "),
        ("profile_path", "/private/profile"),
        ("actor_id", "operator_" + "c" * 32),
    ],
)
def test_binding_rejects_forged_authority_and_invalid_fields(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        KakaoSourceBinding.model_validate({**binding_payload(), field: value})


@pytest.mark.parametrize(
    "updates",
    [
        {"interval_minutes": True},
        {"interval_minutes": 0},
        {"interval_minutes": 10081},
        {"include_images": False},
        {"include_images": 1},
        {"question_rule_version": "ai_guess"},
        {"cookie": "forbidden"},
        {"source_timezone": "auto"},
    ],
)
def test_policy_is_bounded_and_never_silently_omits_images(updates: dict) -> None:
    with pytest.raises(ValueError):
        KakaoCollectionPolicy.model_validate(updates)


def test_policy_hash_and_same_binding_are_checked() -> None:
    payload = binding_payload()
    payload["policy_revision"]["sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="POLICY_HASH_MISMATCH"):
        KakaoSourceBinding.model_validate(payload)
    payload = binding_payload()
    payload["policy_revision"]["source_binding_id"] = "kakaobinding_" + "c" * 32
    with pytest.raises(ValueError, match="POLICY_BINDING_MISMATCH"):
        KakaoSourceBinding.model_validate(payload)
    payload = binding_payload()["policy_revision"]
    payload["previous_revision_id"] = POLICY
    with pytest.raises(ValueError, match="POLICY_LINEAGE_INVALID"):
        KakaoCollectionPolicyRevision.model_validate(payload)


def test_retirement_requires_exact_revision_and_version() -> None:
    request = KakaoBindingRetire(parent_policy_revision_id=POLICY, expected_resource_version=1)
    validate_contract("kakao-source-binding-command-v1", request.model_dump(mode="json"))
    with pytest.raises(ValueError):
        KakaoBindingRetire.model_validate({"expected_resource_version": 1})


def test_new_permissions_are_not_granted_to_existing_nonadmin_roles() -> None:
    keys = {value for value in PermissionKey if value.value.startswith("kakao_archive:")}
    assert len(keys) == 5
    assert keys <= ROLE_PERMISSIONS[RoleKey.ADMIN]
    assert all(
        not keys.intersection(values)
        for role, values in ROLE_PERMISSIONS.items()
        if role != RoleKey.ADMIN
    )


def test_binding_tables_are_small_and_postgresql_ddl_compiles() -> None:
    assert OperatorRecord.__table__.metadata is KakaoChannelBindingRecord.__table__.metadata
    for record in (
        KakaoChannelBindingRecord,
        KakaoCollectionPolicyRevisionRecord,
        KakaoBindingCommandRecord,
    ):
        table = record.__table__
        assert str(CreateTable(table).compile(dialect=dialect()))
        assert all(isinstance(column.type, (String, Integer, DateTime)) for column in table.columns)
        assert not {"body", "csv", "cookie", "token", "profile_path"}.intersection(
            table.columns.keys()
        )
    current = next(
        constraint
        for constraint in KakaoChannelBindingRecord.__table__.foreign_key_constraints
        if constraint.name == "fk_kakao_binding_current_policy"
    )
    assert current.deferrable and current.initially == "DEFERRED"
    assert len(current.elements) == 2


def test_migration_is_additive_and_uses_existing_immutable_trigger() -> None:
    path = ROOT / "migrations/versions/20261116_0080_kakao_binding_bootstrap.py"
    spec = importlib.util.spec_from_file_location("kakao_bootstrap_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={
            "as_sql": True,
            "output_buffer": output,
            "literal_binds": True,
        },
    )
    with Operations.context(context):
        module.upgrade()
    ddl = output.getvalue()
    assert module.down_revision == "20261112_0079"
    assert ddl.count("CREATE TABLE kakao_") == 3
    assert ddl.count("reject_control_plane_immutable_mutation()") == 2
    assert "DEFERRABLE INITIALLY DEFERRED" in ddl
    assert "DROP TABLE" not in ddl
    assert module._stable_id("role_", "ADMIN") in ddl
    assert module._stable_id("role_", "VIEWER") not in ddl


def test_migration_downgrade_never_removes_binding_history(monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location(
        "kakao_bootstrap_downgrade",
        ROOT / "migrations/versions/20261116_0080_kakao_binding_bootstrap.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    connection = Mock()
    monkeypatch.setattr(module.op, "get_bind", lambda: connection)
    connection.scalar.return_value = True
    with pytest.raises(RuntimeError, match="KAKAO_ARCHIVE_HISTORY_EXISTS"):
        module.downgrade()
    connection.scalar.return_value = False
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={
            "as_sql": True,
            "output_buffer": output,
            "literal_binds": True,
        },
    )
    with Operations.context(context):
        module.downgrade()
    ddl = output.getvalue()
    assert ddl.count("DROP TABLE kakao_") == 3
    assert ddl.count("DELETE FROM role_permissions") == 5
    assert ddl.count("DELETE FROM permissions") == 5


@pytest.mark.parametrize("failure", ["expired_idle", "expired_absolute", "revoked", "wrong_owner"])
def test_expired_or_wrong_api_session_denied_before_permission_query(failure: str) -> None:
    now = datetime(2026, 11, 16, tzinfo=UTC)
    owner = "operator_" + "c" * 32
    actor = ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id=owner,
        session_id="apisession_" + "d" * 32,
        request_id="synthetic-request",
        authentication_time=now,
        permissions=frozenset(PermissionKey),
        source=ActorSource.APPLICATION_API,
    )
    session = Mock()
    session.get.return_value = SimpleNamespace(
        operator_id=owner,
        status="ACTIVE",
        deleted_at=None,
        must_change_password=False,
    )
    session.execute.return_value.one_or_none.return_value = SimpleNamespace(
        operator_id="operator_" + "e" * 32 if failure == "wrong_owner" else owner,
        revoked_at=now if failure == "revoked" else None,
        absolute_expires_at=now if failure == "expired_absolute" else now + timedelta(hours=1),
        idle_expires_at=now if failure == "expired_idle" else now + timedelta(hours=1),
    )
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        authorize_kakao_actor(session, actor, PermissionKey.KAKAO_ARCHIVE_READ, now=now)
    assert session.execute.call_count == 1
    sql = str(session.execute.call_args.args[0])
    assert "token_family" not in sql and "client_name" not in sql
    assert "absolute_expires_at" in sql and "idle_expires_at" in sql
