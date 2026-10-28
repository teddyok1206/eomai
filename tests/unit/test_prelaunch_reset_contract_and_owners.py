from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_service import prelaunch_item_cleanup as catalog
from eom_hwpx_manager import prelaunch_item_cleanup as hwpx
from eom_orchestrator import prelaunch_artifact_cleanup as artifacts
from eom_orchestrator.metadata_reset_transaction import MetadataResetTransaction
from eom_orchestrator.prelaunch_reset_host import RESET_PAUSED_UNITS, InstalledPrelaunchResetFence
from eom_protocol import prelaunch_item_reset as contract
from eom_protocol.prelaunch_item_reset import PrelaunchItemResetPlan, PrelaunchItemResetReceipt
from eom_workflow_runner import prelaunch_item_cleanup as workflows
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError


def synthetic_body() -> dict:
    return {
        "schema_version": "prelaunch-item-reset-plan/1.0",
        "scope": "AI_PRELAUNCH_20261028",
        "database": "eom_api_test_unit",
        "item_ids": [f"item_{x:032x}" for x in range(1000, 1110)],
        "item_revision_ids": [f"itemrev_{x:032x}" for x in range(2000, 2111)],
        "workflow_ids": [f"workflow_{x:032x}" for x in range(170)],
        "job_ids": ["job_" + "a" * 32],
        "graph_pins": [
            {"revision_id": x, "sha256": "sha256:" + "a" * 64}
            for x in sorted((contract.BASE_GRAPH, *contract.MIXED_GRAPHS))
        ],
        "protected_sha256": "0" * 64,
        "baseline_sha256": "1" * 64,
        "backup": {
            "file_name": "eom_20261028T000000Z_aaaaaaaaaaaa.dump",
            "sha256": "a" * 64,
            "size_bytes": 1,
        },
        "created_at_utc": "2026-10-28T00:00:00Z",
    }


def signed(value: dict) -> dict:
    return value | {"plan_sha256": contract.reset_digest(value)}


@pytest.fixture
def parser_scope(monkeypatch):
    # Only parser mechanics use synthetic IDs. The unmodified, exact approved
    # target hash is exercised by the opt-in snapshot integration suite.
    value = synthetic_body()
    monkeypatch.setattr(contract, "TARGET_SHA256", contract.reset_digest(value["item_ids"]))
    return value


def test_unmodified_approval_rejects_a_different_110_item_set() -> None:
    assert (
        contract.TARGET_SHA256 == "fd53d8cae3e79069d3af824fbbbae91932eb3202724ae988a3d418492f5c3b6c"
    )
    with pytest.raises(ValueError, match="target set differs"):
        PrelaunchItemResetPlan.model_validate(signed(synthetic_body()))


@pytest.mark.parametrize("kind", ["plan", "receipt"])
def test_packaged_schemas_match_the_canonical_release_contract(kind) -> None:
    root = Path(__file__).resolve().parents[2]
    filename = f"prelaunch-item-reset-{kind}-v1.schema.json"
    canonical = (root / "schemas" / "operations" / filename).read_bytes()
    bundled = (root / "packages" / "protocol" / "eom_protocol" / "schemas" / filename).read_bytes()
    assert canonical == bundled
    Draft202012Validator.check_schema(json.loads(canonical))


def test_parser_is_frozen_canonical_and_does_not_grant_authority(parser_scope) -> None:
    plan = PrelaunchItemResetPlan.model_validate(signed(parser_scope))
    assert PrelaunchItemResetPlan.model_validate_json(plan.model_dump_json()) == plan
    with pytest.raises(ValidationError):
        plan.database = "other"
    assert "permissions" not in type(plan).model_fields


def test_plan_publication_uses_the_real_orchestrator_control_file_set_contract(
    parser_scope, tmp_path
) -> None:
    from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
    from eom_orchestrator.prelaunch_reset_artifacts import PrelaunchResetArtifacts

    plan = PrelaunchItemResetPlan.model_validate(signed(parser_scope))
    validator = object.__new__(ControlFileSetPublisher)
    captured = []

    def publish(**kwargs):
        captured.append(
            ControlFileSetPublisher._request(
                validator,
                **{key: value for key, value in kwargs.items() if key != "idempotency_key"},
            )
        )
        return "TEST_PUBLISHED"

    owner = object.__new__(PrelaunchResetArtifacts)
    owner.source_commit = "a" * 40
    owner.publisher = SimpleNamespace(
        settings=SimpleNamespace(staging_root=tmp_path), publish=publish
    )
    assert owner.publish_plan(plan) == "TEST_PUBLISHED"
    assert captured[0]["artifact_type"] == "control_prelaunch_item_reset_plan"


@pytest.mark.parametrize(
    "change",
    [
        lambda v: v.update(scope="ANY_ITEM"),
        lambda v: v.update(database="../production"),
        lambda v: v.update(created_at_utc="2026-10-28T09:00:00+09:00"),
        lambda v: v["item_ids"].__setitem__(0, contract.KEEP_ITEM_ID),
        lambda v: v["item_revision_ids"].__setitem__(0, contract.KEEP_REVISION_ID),
        lambda v: v["workflow_ids"].reverse(),
        lambda v: v["job_ids"].append(v["job_ids"][0]),
        lambda v: v["graph_pins"][0].update(revision_id="graphrev_" + "f" * 32),
        lambda v: v.update(unreviewed_force=True),
    ],
)
def test_invalid_pins_cannot_be_fixed_by_rehashing(parser_scope, change) -> None:
    change(parser_scope)
    with pytest.raises((ValidationError, ValueError, SchemaError)):
        PrelaunchItemResetPlan.model_validate(signed(parser_scope))


def test_hash_tampering_is_rejected(parser_scope) -> None:
    value = signed(parser_scope)
    value["plan_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash mismatch"):
        PrelaunchItemResetPlan.model_validate(value)


def test_receipt_requires_balanced_job_counts() -> None:
    value = {
        "schema_version": "prelaunch-item-reset-receipt/1.0",
        "plan_sha256": "a" * 64,
        "database": "eom",
        "deleted_items": 110,
        "deleted_item_revisions": 111,
        "deleted_workflows": 902,
        "candidate_jobs": 2096,
        "shared_jobs_preserved": 1197,
        "exclusive_jobs_deleted": 899,
        "protected_sha256": "b" * 64,
        "nas_action": "PRESERVED",
        "outcome": "COMPLETED",
    }
    assert PrelaunchItemResetReceipt.model_validate(value).deleted_items == 110
    with pytest.raises(ValueError, match="do not balance"):
        PrelaunchItemResetReceipt.model_validate(value | {"exclusive_jobs_deleted": 900})


def test_shared_dependency_closure_retains_cycles_but_not_unreachable_jobs() -> None:
    assert artifacts.protected_reset_dependencies(
        {"a": {"b"}, "b": {"a", "c"}, "c": set(), "delete": {"c"}}, {"a"}
    ) == {"a", "b", "c"}
    with pytest.raises(ValueError, match="DEPENDENCY_SCOPE"):
        artifacts.protected_reset_dependencies({"a": {"missing"}}, set())


def test_pointer_scan_handles_nested_keys_and_deep_json() -> None:
    value = {"artifact_key": [{"revision": "rev_a"}]}
    assert artifacts.reset_pointer_strings(value) == {"artifact_key", "revision", "rev_a"}
    for _ in range(2000):
        value = [value]
    assert "rev_a" in artifacts.reset_pointer_strings(value)


@pytest.mark.parametrize("owner", [catalog, workflows, hwpx, artifacts])
def test_each_component_writes_only_its_owned_tables(owner) -> None:
    tree = ast.parse(Path(owner.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for table in re.findall(r"(?:DELETE FROM|UPDATE) ([a-z_]+)", node.value):
                assert table in owner.OWNED_TABLES


def test_dependency_direction_and_cli_are_not_sql_or_business_owners() -> None:
    import eom_orchestrator.prelaunch_item_reset_service as application
    import eomctl.prelaunch_reset as cli

    tree = ast.parse(Path(application.__file__).read_text())
    forbidden = ("eom_catalog_service", "eom_workflow_runner", "eom_hwpx_manager")
    assert not any(
        isinstance(n, ast.ImportFrom) and n.module and n.module.startswith(forbidden)
        for n in ast.walk(tree)
    )
    text = Path(cli.__file__).read_text()
    assert "DELETE FROM" not in text and "ALTER TABLE" not in text


def test_component_scope_rejects_mutation_before_any_cursor_access() -> None:
    transaction = MetadataResetTransaction(None)
    with pytest.raises(ValueError, match="COMPONENT_SCOPE"):
        hwpx.delete_prelaunch_builds(transaction, ())


def test_runtime_api_role_cannot_authorize_owner_metadata_mutation() -> None:
    cursor = SimpleNamespace(
        execute=lambda *_: None,
        fetchone=lambda: ("runtime", "runtime", False, "off"),
        fetchall=lambda: [("jobs", "schema_owner")],
    )
    with pytest.raises(ValueError, match="OWNER_REQUIRED"):
        MetadataResetTransaction(cursor).require_owner(("jobs",))


def test_source_checkout_is_not_a_production_maintenance_release() -> None:
    with pytest.raises(ValueError, match="INSTALLED_RELEASE"):
        InstalledPrelaunchResetFence()


def test_running_service_cannot_be_claimed_quiescent(monkeypatch) -> None:
    from eom_orchestrator import prelaunch_reset_host as host

    fence = object.__new__(InstalledPrelaunchResetFence)
    monkeypatch.setattr(fence, "authorize_local_owner", lambda: None)
    monkeypatch.setattr(
        host.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout="ActiveState=active\nMainPID=5\nControlPID=0\n"
        ),
    )
    with pytest.raises(ValueError, match="SERVICE_NOT_QUIESCENT"):
        fence.verify()
    assert len(RESET_PAUSED_UNITS) == 7


@pytest.mark.parametrize(
    "state,pid,control,job,allowed",
    [
        ("inactive", "0", "0", "", True),
        ("failed", "0", "0", "", True),
        ("failed", "5", "0", "", False),
        ("failed", "0", "1", "", False),
        ("failed", "0", "0", "123 /job/123", False),
        ("activating", "0", "0", "", False),
    ],
)
def test_quiescence_preserves_failed_history_but_rejects_live_or_reserved_work(
    monkeypatch, state, pid, control, job, allowed
) -> None:
    from eom_orchestrator import prelaunch_reset_host as host

    fence = object.__new__(InstalledPrelaunchResetFence)
    monkeypatch.setattr(fence, "authorize_local_owner", lambda: None)

    def observe(command, **_kwargs):
        value = (
            f"ActiveState={state}\nMainPID={pid}\nControlPID={control}\nJob={job}\n"
            if "show" in command
            else ""
        )
        return SimpleNamespace(stdout=value)

    monkeypatch.setattr(host.subprocess, "run", observe)
    if allowed:
        fence.verify()
    else:
        with pytest.raises(ValueError, match="SERVICE_NOT_QUIESCENT"):
            fence.verify()


def test_bounded_cli_document_rejects_symlink_and_oversize(tmp_path) -> None:
    from eomctl.prelaunch_reset import _bounded_document

    source = tmp_path / "value.json"
    source.write_bytes(b"{}")
    assert _bounded_document(source, 10) == b"{}"
    with pytest.raises(ValueError, match="INPUT_FILE_INVALID"):
        _bounded_document(source, 1)
    linked = tmp_path / "linked.json"
    linked.symlink_to(source)
    with pytest.raises(OSError):
        _bounded_document(linked, 10)


def test_real_owner_database_configuration_is_not_selected_by_model_or_runtime_env(
    monkeypatch,
) -> None:
    from eom_orchestrator import prelaunch_reset_host as host

    fence = object.__new__(InstalledPrelaunchResetFence)
    monkeypatch.setattr(fence, "authorize_local_owner", lambda: None)
    monkeypatch.setenv("EOM_DATABASE_URL", "postgresql://worker@evil.example/other")
    monkeypatch.setattr(
        host.Path,
        "lstat",
        lambda _self: SimpleNamespace(st_mode=0o100640, st_uid=0, st_nlink=1, st_size=100),
    )
    seen = []

    def configuration(path):
        seen.append(str(path))
        return {
            "POSTGRES_USER": "test_owner",
            "POSTGRES_PASSWORD": "TEST_ONLY",
            "POSTGRES_DB": "test_db",
        }

    monkeypatch.setattr(host, "_read_secret_environment", configuration)
    result = fence.owner_database_url()
    assert result.host == "127.0.0.1" and result.database == "test_db"
    assert result.query.get("options") == "-csearch_path=app,pg_catalog"
    assert seen == ["/etc/eom/secrets/postgres.env"]
    assert "TEST_ONLY" not in repr(result)


def test_audit_publisher_rejects_an_owner_engine_without_the_fixed_schema() -> None:
    from eom_orchestrator.prelaunch_reset_artifacts import PrelaunchResetArtifacts
    from sqlalchemy import create_engine

    engine = create_engine("postgresql+psycopg://owner@127.0.0.1/eom")
    try:
        with pytest.raises(ValueError, match="OWNER_SCHEMA_REQUIRED"):
            PrelaunchResetArtifacts(engine, "a" * 40)
    finally:
        engine.dispose()
