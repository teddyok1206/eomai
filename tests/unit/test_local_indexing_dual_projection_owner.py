"""Explicit dual metadata composition, synthetic IAM/IO; no actual service grant."""

from copy import deepcopy
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_identifiers import canonical_json_bytes
from eom_identity_service import PostgresLocalIndexingServiceFence
from eom_identity_service.local_indexing_runtime import (
    AuthenticatedLocalIndexingRuntime,
    LocalIndexingRuntimePin,
)
from eom_workflow.local_indexing_owner_configuration import (
    LocalIndexingMixedOwnerConfiguration,
    LocalIndexingMultiviewOwnerConfiguration,
    LocalIndexingOwnerConfiguration,
    local_indexing_owner_configuration_bytes,
    parse_cpu_local_indexing_owner_configuration,
)
from eom_workflow_runner import local_indexing_service_entry as entry
from eom_workflow_runner import local_indexing_service_runtime as runtime
from eom_workflow_runner import native_cpu_scheduling_read as scheduling
from eom_workflow_runner.local_embedding_service_reconciliation import (
    LocalEmbeddingReconciliationResult,
    ReconciliationState,
)

from tests.unit.test_local_indexing_mixed_owner import VIEWS, mixed_owner_document
from tests.unit.test_local_indexing_owner_configuration import document
from tests.unit.test_mixed_local_embedding_owner_admission import mixed_scope


def dual_document(version=2):
    body = mixed_owner_document()
    legacy = document()
    for field in (
        "corpus_id",
        "recipe",
        "runtime_profile",
        "database_owner",
        "runtime_verifier",
        "cpu_environment_raw_sha256",
        "owner_environment_raw_sha256",
        "poll_interval_seconds",
    ):
        legacy[field] = deepcopy(body[field])
    legacy["namespace"] = deepcopy(body["namespace"])
    legacy["namespace"]["projection_version"] = "accepted-solution-comparison/1.0"
    if version == 2:
        legacy["schema_version"] = "local-indexing-owner-configuration/2.0"
        legacy["additional_namespaces"] = [
            legacy["namespace"] | {"view": view} for view in VIEWS[1:]
        ]
    body["legacy_configuration"] = legacy
    return body


@pytest.mark.parametrize("version", (1, 2))
def test_explicit_dual_configuration_preserves_each_strict_old_selection(version):
    raw = canonical_json_bytes(dual_document(version))
    selected = parse_cpu_local_indexing_owner_configuration(raw)
    assert type(selected) is LocalIndexingMixedOwnerConfiguration
    assert type(selected.legacy_configuration) is (
        LocalIndexingOwnerConfiguration
        if version == 1
        else LocalIndexingMultiviewOwnerConfiguration
    )
    assert local_indexing_owner_configuration_bytes(selected) == raw
    assert (
        selected.native_execution_policy_sha256
        != selected.legacy_configuration.native_execution_policy_sha256
    )
    assert selected.service_policy_sha256 != selected.legacy_configuration.service_policy_sha256
    assert len(selected.namespaces) + len(selected.legacy_configuration.namespaces) == (
        4 if version == 1 else 6
    )


def test_absent_optional_selection_preserves_original_config4_wire_hash():
    original = canonical_json_bytes(mixed_owner_document())
    parsed = parse_cpu_local_indexing_owner_configuration(original)
    assert parsed.legacy_configuration is None
    assert local_indexing_owner_configuration_bytes(parsed) == original
    explicit_null = canonical_json_bytes(mixed_owner_document() | {"legacy_configuration": None})
    with pytest.raises(ValueError):
        parse_cpu_local_indexing_owner_configuration(explicit_null)


@pytest.mark.parametrize(
    "fault",
    (
        "corpus",
        "database",
        "verifier",
        "cpu_env",
        "owner_env",
        "cadence",
        "partition",
        "recipe",
        "runtime",
        "same_grant_revision",
        "same_grant_hash",
        "same_native_policy",
        "recursive",
        "native3",
        "collision",
        "legacy_extra",
        "nested_extra",
        "constructed",
    ),
)
def test_dual_selection_rejects_mismatched_runtime_borrowing_or_namespace_collision(fault):
    body = dual_document()
    old = body["legacy_configuration"]
    if fault == "corpus":
        old["corpus_id"] = "corpus_" + "f" * 32
    elif fault == "database":
        old["database_owner"]["role_oid"] += 1
    elif fault == "verifier":
        old["runtime_verifier"]["script_raw_sha256"] = "sha256:" + "f" * 64
    elif fault in {"cpu_env", "owner_env"}:
        old[("cpu" if fault == "cpu_env" else "owner") + "_environment_raw_sha256"] = (
            "sha256:" + "f" * 64
        )
    elif fault == "cadence":
        old["poll_interval_seconds"] += 30
    elif fault == "partition":
        old["namespace"]["storage_partition"] = "different.partition"
        for namespace in old["additional_namespaces"]:
            namespace["storage_partition"] = "different.partition"
    elif fault == "recipe":
        old["namespace"]["recipe_sha256"] = "sha256:" + "f" * 64
    elif fault == "runtime":
        old["runtime_profile"]["resource_profile"]["device"] = "CUDA"
    elif fault == "same_grant_revision":
        old["service_policy_revision_id"] = body["service_policy_revision_id"]
    elif fault == "same_grant_hash":
        old["service_policy_sha256"] = body["service_policy_sha256"]
    elif fault == "same_native_policy":
        old["native_execution_policy_sha256"] = body["native_execution_policy_sha256"]
    elif fault == "recursive":
        old["legacy_configuration"] = deepcopy(old)
    elif fault == "native3":
        old["schema_version"] = "local-indexing-owner-configuration/3.0"
    elif fault == "collision":
        old["namespace"] = deepcopy(body["namespace"])
    elif fault == "legacy_extra":
        old["permissions"] = ["ADMIN"]
    elif fault == "nested_extra":
        checked = LocalIndexingMixedOwnerConfiguration.model_validate(body)
        old = checked.legacy_configuration.model_copy(
            update={
                "runtime_verifier": checked.legacy_configuration.runtime_verifier.model_copy(
                    update={"permissions": ["ADMIN"]}
                )
            }
        )
        body = checked.model_copy(update={"legacy_configuration": old})
    else:
        body = LocalIndexingMixedOwnerConfiguration.model_validate(body).model_copy(
            update={
                "legacy_configuration": LocalIndexingOwnerConfiguration.model_construct(
                    schema_version="local-indexing-owner-configuration/1.0"
                )
            }
        )
    with pytest.raises(ValueError):
        local_indexing_owner_configuration_bytes(body) if isinstance(
            body, LocalIndexingMixedOwnerConfiguration
        ) else LocalIndexingMixedOwnerConfiguration.model_validate(body)


def compose(monkeypatch, *, deny_legacy=False):
    body = dual_document()
    _scope, _compiled, grant = mixed_scope()
    pin = LocalIndexingRuntimePin(grant.service, "e" * 40, "sha256:" + "a" * 64)
    capture = object.__new__(AuthenticatedLocalIndexingRuntime)
    monkeypatch.setattr(
        AuthenticatedLocalIndexingRuntime,
        "read_owner_configuration",
        lambda _: canonical_json_bytes(body),
    )
    current = Mock()
    monkeypatch.setattr(AuthenticatedLocalIndexingRuntime, "assert_current", current)
    monkeypatch.setattr(PostgresLocalIndexingServiceFence, "fence_current_service", Mock())
    engine, publisher = Mock(), MagicMock()
    monkeypatch.setattr(runtime, "build_native_embedding_controller_engine", lambda: engine)
    monkeypatch.setattr(runtime, "ControlFileSetPublisher", lambda *_: publisher)
    monkeypatch.setattr(runtime, "catalog_runtime_privileges_ready", lambda _: True)
    for name in ("require_protocol", "require_mixed_ownership_protocol"):
        monkeypatch.setattr(runtime.EmbeddingEncodingReservationStorage, name, Mock())
    monkeypatch.setattr(
        runtime,
        "FixedIndexingRuntimeVerification",
        Mock(return_value=Mock(spec=runtime.FixedIndexingRuntimeVerification)),
    )
    launcher = Mock(return_value=Mock(spec=runtime.FixedNativeIndexLauncher))
    monkeypatch.setattr(runtime, "FixedNativeIndexLauncher", launcher)
    owners, runner_calls, runners = [], [], []

    def owner_factory(_engine, configuration, *, source_authority, settings):
        assert _engine is engine
        owner = Mock()
        owner.current_reconciliation_lookup.return_value = "synthetic current graph lookup"
        if (
            deny_legacy
            and configuration.registry.namespace.projection_version
            == "accepted-solution-comparison/1.0"
        ):
            owner.resolve_reconciliation_controls.side_effect = ValueError(
                "synthetic current legacy grant denied"
            )
        owners.append((owner, configuration, source_authority))
        return owner

    monkeypatch.setattr(
        runtime.CatalogLocalEmbeddingOwnerAdmission, "for_indexing_service", owner_factory
    )
    monkeypatch.setattr(runtime, "CatalogNativeEmbeddingExecutor", Mock())

    def runner(*args, **kwargs):
        runner_calls.append(kwargs)
        result = Mock()
        runners.append(result)
        return result

    monkeypatch.setattr(runtime, "WorkflowRunner", runner)
    monkeypatch.setattr(runtime, "LocalEmbeddingServiceReconciliation", Mock())
    return SimpleNamespace(
        body=body,
        capture=capture,
        pin=pin,
        engine=engine,
        publisher=publisher,
        launcher=launcher,
        current=current,
        owners=owners,
        runner_calls=runner_calls,
        runners=runners,
    )


def test_one_actual_capture_and_launcher_compose_six_independently_pinned_owner_leaves(monkeypatch):
    c = compose(monkeypatch)
    result = runtime.build_local_indexing_service_runtime(c.capture, c.pin)
    assert result.engine is c.engine and len(result.namespaces) == 6
    assert (
        len(
            {
                canonical_json_bytes(raw_similarity_contract_value(leaf.namespace))
                for leaf in result.namespaces
            }
        )
        == 6
    )
    c.current.assert_called_once_with(
        service=c.pin.service,
        runtime_source_commit=c.pin.runtime_source_commit,
        configuration_sha256=c.pin.configuration_sha256,
    )
    c.launcher.assert_called_once()
    authorities = {id(a): a for _o, _config, a in c.owners}
    assert len(authorities) == 2
    assert {a.service_policy_revision_id for a in authorities.values()} == {
        c.body["service_policy_revision_id"],
        c.body["legacy_configuration"]["service_policy_revision_id"],
    }
    fences = {
        id(a.authority.service_fence): a.authority.service_fence for a in authorities.values()
    }
    assert len(fences) == 1 and next(iter(fences.values())).pin == c.pin
    for (owner, config, authority), runner in zip(c.owners, c.runner_calls, strict=True):
        owner.current_reconciliation_lookup.assert_called_once()
        owner.resolve_reconciliation_controls.assert_called_once()
        assert authority.native_execution_policy_sha256 == config.native_execution_policy_sha256
        assert runner["command_actor_selection"].namespace == config.registry.namespace
        assert runner["command_actor_selection"].actor_id == c.pin.service.service_id
        assert runner["local_embedding_owner"] is owner


def test_denied_legacy_current_controls_abort_entire_construction_without_serving(monkeypatch):
    c = compose(monkeypatch, deny_legacy=True)
    with pytest.raises(ValueError, match="synthetic current legacy grant denied"):
        runtime.build_local_indexing_service_runtime(c.capture, c.pin)
    c.engine.dispose.assert_called_once()
    assert len(c.runner_calls) == 3
    c.launcher.return_value.run.assert_not_called()
    for runner in c.runners:
        runner.run_once.assert_not_called()


def test_existing_round_robin_visits_all_six_without_aliasing_same_view(monkeypatch):
    stop = Event()
    selected = LocalIndexingMixedOwnerConfiguration.model_validate(dual_document())
    leaves = []
    for configuration in (selected, selected.legacy_configuration):
        for namespace in configuration.namespaces:
            runner, reconciliation = Mock(), Mock()
            runner.run_once.return_value = None
            reconciliation.run_once.return_value = LocalEmbeddingReconciliationResult(
                ReconciliationState.UP_TO_DATE, "synthetic same graph"
            )
            leaves.append(
                runtime.LocalIndexingNamespaceRuntime(
                    namespace=namespace, runner=runner, reconciliation=reconciliation
                )
            )
    last = leaves[-1].reconciliation.run_once.return_value
    leaves[-1].reconciliation.run_once.side_effect = lambda: (stop.set(), last)[1]
    monkeypatch.setattr(scheduling, "should_defer_background_cpu_claim", lambda _: False)
    entry.serve_local_indexing(
        SimpleNamespace(engine=Mock(), configuration=selected, namespaces=tuple(leaves)), stop
    )
    for leaf in leaves:
        leaf.runner.run_once.assert_called_once()
        leaf.reconciliation.run_once.assert_called_once()
