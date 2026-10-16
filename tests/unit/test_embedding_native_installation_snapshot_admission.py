"""Synthetic ROOTLOCAL/config/snapshot composition; never an actual installation grant."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from eom_catalog_contracts.embedding_host_configuration import (
    EmbeddingHostConfigurationPointer,
    parse_host_configuration_snapshot,
)
from eom_catalog_contracts.embedding_native_installation_evidence import (
    parse_rootlocal_native_admission_receipt_metadata,
    parse_rootlocal_prefix_inventory_candidate,
    rootlocal_native_admission_receipt_metadata_bytes,
    rootlocal_prefix_inventory_candidate_bytes,
)
from eom_catalog_contracts.embedding_native_runtime_config import (
    installed_embedding_native_runtime_config_bytes,
)
from eom_catalog_service import embedding_native_installation_admission as admission
from eom_catalog_service.embedding_native_installation_admission import (
    NativeInstallationAdmissionError,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes

from tests.unit.embedding_native_runtime_config_v11_fixtures import native_config_metadata_v11
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_host_configuration_contracts import snapshot_body
from tests.unit.test_embedding_native_installation_admission import Scenario
from tests.unit.test_embedding_native_installation_admission import state as state
from tests.unit.test_embedding_native_installation_evidence import INVENTORY_DRAFT, RECEIPT_DRAFT


def select_snapshot_configuration(state: Scenario, monkeypatch: pytest.MonkeyPatch) -> None:
    config, _bundle, _proof = native_config_metadata_v11()
    snapshot = parse_host_configuration_snapshot(snapshot_body())
    (old_inventory,) = [path for path in state.files if path.name == "inventory.json"]
    inventory_body = json.loads(state.files[old_inventory])
    inventory_body["host_seed_sha256"] = snapshot.host_seed_sha256
    inventory = parse_rootlocal_prefix_inventory_candidate(
        canonical_json_bytes(seal(inventory_body, "inventory_sha256")),
        schema_raw=INVENTORY_DRAFT.read_bytes(),
    )
    inventory_raw = rootlocal_prefix_inventory_candidate_bytes(inventory)
    config_raw = installed_embedding_native_runtime_config_bytes(config)
    (old_receipt,) = [path for path in state.files if path.name == "receipt.json"]
    receipt_body = json.loads(state.files[old_receipt])
    receipt_body["configuration"] = {
        "configuration_id": config.configuration_id,
        "configuration_revision_id": config.configuration_revision_id,
        "configuration_raw_sha256": sha256_bytes(config_raw),
        "configuration_sha256": config.config_sha256,
    }
    receipt_body["inventory"]["inventory_raw_sha256"] = sha256_bytes(inventory_raw)
    receipt_body["inventory"]["inventory_sha256"] = inventory.inventory_sha256
    receipt = parse_rootlocal_native_admission_receipt_metadata(
        canonical_json_bytes(seal(receipt_body, "receipt_sha256")),
        schema_raw=RECEIPT_DRAFT.read_bytes(),
    )
    raw = rootlocal_native_admission_receipt_metadata_bytes(receipt)
    base = admission._EVIDENCE_ROOT / config.configuration_id / config.configuration_revision_id
    state.files[base / "inventory.json"] = inventory_raw
    state.files[base / "receipt.json"] = raw
    state.files[
        admission._CONFIG_ROOT
        / config.configuration_id
        / config.configuration_revision_id
        / "config.json"
    ] = config_raw
    state.configuration = receipt.configuration
    state.receipt_pin = sha256_bytes(raw)
    resolved = SimpleNamespace(snapshot=snapshot)
    mount = SimpleNamespace(configuration=resolved)

    def resolve(pointer: EmbeddingHostConfigurationPointer) -> Any:
        state.events.append("snapshot-resolve")
        assert pointer == config.host_configuration
        if state.broken in {"missing", "stale", "snapshot_hash"}:
            raise ValueError("synthetic snapshot missing/stale/raw hash mismatch")
        return resolved

    def require_mount(value: Any) -> Any:
        state.events.append("snapshot-mount")
        assert value is resolved
        if state.broken == "mount":
            raise ValueError("synthetic pre-exec mount missing")
        return mount

    class Host:
        def assert_current(self) -> None:
            state.events.append("snapshot-host-epochs")
            if state.broken in {"host", "snapshot", "mount"}:
                raise ValueError("synthetic namespace/snapshot/host drift")

        def close(self) -> None:
            state.host_closes += 1

    def capture(*, expected_seed_sha256: str, files: object, snapshot_mount: Any) -> Any:
        assert files is not None and snapshot_mount is mount
        state.events.append("snapshot-capture")
        if expected_seed_sha256 != snapshot.host_seed_sha256 or state.broken == "target_seed":
            raise ValueError("synthetic inventory/target host seed mismatch")
        return Host()

    monkeypatch.setattr(admission, "resolve_host_configuration_snapshot", resolve)
    monkeypatch.setattr(admission, "require_host_configuration_snapshot_mount", require_mount)
    monkeypatch.setattr(admission, "capture_snapshot_embedding_host", capture)


def test_v11_closes_exact_receipt_snapshot_and_mounted_host_once_then_rechecks(
    state: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    select_snapshot_configuration(state, monkeypatch)
    with state.capture() as captured:
        before = len(state.reads)
        assert state.events.count("snapshot-resolve") == 1
        assert state.events.count("snapshot-mount") == 1
        assert state.events.count("snapshot-capture") == 1
        assert "host-capture" not in state.events
        assert (
            state.events.index("snapshot-resolve")
            < state.events.index("snapshot-mount")
            < state.events.index("snapshot-capture")
        )

        def denied(*args: Any, **kwargs: Any) -> Any:
            pytest.fail("held admission must not resolve a new snapshot or reread metadata")

        monkeypatch.setattr(admission, "resolve_host_configuration_snapshot", denied)
        monkeypatch.setattr(
            admission, "parse_installed_embedding_native_runtime_config_bytes", denied
        )
        for _ in range(3):
            state.assert_current(captured)
        assert len(state.reads) == before and state.events.count("snapshot-host-epochs") >= 4
    assert state.host_closes == 1


@pytest.mark.parametrize("fault", ("missing", "stale", "snapshot_hash", "mount", "target_seed"))
def test_invalid_host_selection_never_falls_back_to_legacy_or_opens_backend(
    state: Scenario, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    select_snapshot_configuration(state, monkeypatch)
    state.broken = fault
    with pytest.raises(
        NativeInstallationAdmissionError, match="NATIVE_INSTALLATION_CAPTURE_INVALID"
    ):
        state.capture()
    assert state.host_closes == 0 and "host-capture" not in state.events


@pytest.mark.parametrize("fault", ("host", "snapshot", "mount"))
def test_namespace_or_snapshot_drift_stops_current_use_and_releases_host(
    state: Scenario, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    select_snapshot_configuration(state, monkeypatch)
    captured = state.capture()
    state.broken = fault
    with pytest.raises(NativeInstallationAdmissionError, match="NATIVE_INSTALLATION_CHANGED"):
        state.assert_current(captured)
    with pytest.raises(NativeInstallationAdmissionError, match="NATIVE_INSTALLATION_CHANGED"):
        captured.close()
    assert state.host_closes == 1


def test_new_snapshot_body_cannot_replace_independently_pinned_configuration(
    state: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    select_snapshot_configuration(state, monkeypatch)
    state.receipt_pin = "sha256:" + "f" * 64
    with pytest.raises(
        NativeInstallationAdmissionError, match="NATIVE_INSTALLATION_CAPTURE_INVALID"
    ):
        state.capture()
    assert "snapshot-resolve" not in state.events and state.host_closes == 0
