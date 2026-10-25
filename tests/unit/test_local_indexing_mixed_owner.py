"""Additive CPU configuration4; synthetic composition is not operating authority."""

from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.local_indexing_owner_configuration import (
    LOCAL_INDEXING_MIXED_OWNER_SCHEMA_SHA256,
    LOCAL_INDEXING_MULTIVIEW_OWNER_SCHEMA_SHA256,
    LOCAL_INDEXING_NATIVE_OWNER_SCHEMA_SHA256,
    LOCAL_INDEXING_OWNER_SCHEMA_SHA256,
    LocalIndexingMixedOwnerConfiguration,
    LocalIndexingOwnerConfigurationError,
    local_indexing_owner_configuration_bytes,
    parse_cpu_local_indexing_owner_configuration,
    parse_local_indexing_owner_configuration,
    parse_supported_local_indexing_owner_configuration,
)
from eom_workflow_runner import local_indexing_service_runtime as composition

from tests.unit.test_local_indexing_owner_configuration import document
from tests.unit.test_mixed_local_embedding_owner_admission import mixed_scope
from tests.unit.test_native_embedding_backend_selection import owner_document

ROOT = Path(__file__).resolve().parents[2]
VIEWS = ("CONTENT_ONLY", "CONCRETE_FACETS", "METADATA_ONLY")


def mixed_owner_document():
    c, _compiled, grant = mixed_scope()
    body = document() | {
        "schema_version": "local-indexing-owner-configuration/4.0",
        "corpus_id": c.plan.corpus_id,
        "namespace": c.plan.namespace.model_dump(mode="json"),
        "recipe": c.plan.recipe.model_dump(mode="json"),
        "source_classes": ["APPROVED_ITEM", "PAST_EXAM"],
        "service_policy_revision_id": grant.access_policy_revision_id,
        "service_policy_sha256": grant.content_sha256,
        "native_execution_policy": c.request.native_execution_policy.model_dump(mode="json"),
        "native_execution_policy_sha256": c.policy.policy_sha256,
        "runtime_profile": c.policy.profiles[0].model_dump(mode="json"),
    }
    body["namespace"]["view"] = VIEWS[0]
    body["additional_namespaces"] = [body["namespace"] | {"view": v} for v in VIEWS[1:]]
    return body


def test_schema4_is_additive_and_exact_cpu_dispatch_keeps_old_parser_closed():
    for version, expected in enumerate(
        (
            LOCAL_INDEXING_OWNER_SCHEMA_SHA256,
            LOCAL_INDEXING_MULTIVIEW_OWNER_SCHEMA_SHA256,
            LOCAL_INDEXING_NATIVE_OWNER_SCHEMA_SHA256,
            LOCAL_INDEXING_MIXED_OWNER_SCHEMA_SHA256,
        ),
        start=1,
    ):
        name = f"local-indexing-owner-configuration-v{version}.schema.json"
        raw = (ROOT / "schemas/workflow" / name).read_bytes()
        assert raw == (ROOT / "packages/workflow/eom_workflow/resources" / name).read_bytes()
        assert sha256_bytes(raw) == expected
    raw = canonical_json_bytes(mixed_owner_document())
    selected = parse_cpu_local_indexing_owner_configuration(raw)
    assert type(selected) is LocalIndexingMixedOwnerConfiguration
    assert selected == parse_supported_local_indexing_owner_configuration(raw)
    assert local_indexing_owner_configuration_bytes(selected) == raw
    assert tuple(n.view for n in selected.namespaces) == VIEWS
    with pytest.raises(LocalIndexingOwnerConfigurationError):
        parse_local_indexing_owner_configuration(raw)
    for device in ("CPU", "CUDA"):
        with pytest.raises(LocalIndexingOwnerConfigurationError):
            parse_cpu_local_indexing_owner_configuration(
                canonical_json_bytes(owner_document(device)[0])
            )


@pytest.mark.parametrize(
    "fault",
    (
        "legacy_projection",
        "past_population",
        "space",
        "recipe",
        "partition",
        "duplicate",
        "fourth",
        "cuda",
        "extra",
        "bool",
    ),
)
def test_configuration4_never_silently_upgrades_scope_or_device(fault):
    body = mixed_owner_document()
    if fault == "legacy_projection":
        body["namespace"]["projection_version"] = "accepted-solution-comparison/1.0"
    elif fault == "past_population":
        body["namespace"]["population_scope"] = "OCCURRENCE_BACKED_PAST_EXAM"
    elif fault in {"space", "recipe"}:
        body["additional_namespaces"][0][fault + "_sha256"] = "sha256:" + "f" * 64
    elif fault == "partition":
        body["additional_namespaces"][0]["storage_partition"] = "different.partition"
    elif fault == "duplicate":
        body["additional_namespaces"][0] = deepcopy(body["namespace"])
    elif fault == "fourth":
        body["additional_namespaces"].append(deepcopy(body["namespace"]))
    elif fault == "cuda":
        body["runtime_profile"]["resource_profile"]["device"] = "CUDA"
    elif fault == "extra":
        body["permissions"] = ["ADMIN"]
    else:
        body["maximum_targets"] = True
    with pytest.raises(ValueError):
        parse_cpu_local_indexing_owner_configuration(canonical_json_bytes(body))


@pytest.mark.parametrize("fault", ("top", "nested", "constructed", "noncanonical"))
def test_configuration4_revalidates_copied_and_constructed_values(fault):
    selected = LocalIndexingMixedOwnerConfiguration.model_validate(mixed_owner_document())
    if fault == "noncanonical":
        with pytest.raises(ValueError):
            parse_cpu_local_indexing_owner_configuration(
                local_indexing_owner_configuration_bytes(selected) + b"\n"
            )
        return
    if fault == "top":
        selected = selected.model_copy(update={"permissions": ["ADMIN"]})
    elif fault == "nested":
        selected = selected.model_copy(
            update={"namespace": selected.namespace.model_copy(update={"permission": "ADMIN"})}
        )
    else:
        selected = LocalIndexingMixedOwnerConfiguration.model_construct(
            schema_version="local-indexing-owner-configuration/4.0"
        )
    with pytest.raises(ValueError):
        local_indexing_owner_configuration_bytes(selected)


def test_factory_selects_config4_before_engine_without_borrowing_config3(monkeypatch):
    from eom_identity_service.local_indexing_runtime import (
        AuthenticatedLocalIndexingRuntime,
        LocalIndexingRuntimePin,
    )

    capture = object.__new__(AuthenticatedLocalIndexingRuntime)
    _scope, _compiled, grant = mixed_scope()
    pin = LocalIndexingRuntimePin(grant.service, "e" * 40, "sha256:" + "a" * 64)
    selected = canonical_json_bytes(mixed_owner_document())
    monkeypatch.setattr(
        AuthenticatedLocalIndexingRuntime, "read_owner_configuration", lambda _: selected
    )
    checked = Mock(side_effect=ValueError("synthetic current runtime fence"))
    monkeypatch.setattr(AuthenticatedLocalIndexingRuntime, "assert_current", checked)
    engine = Mock(side_effect=AssertionError("must not build engine before runtime fence"))
    monkeypatch.setattr(composition, "build_native_embedding_controller_engine", engine)
    with pytest.raises(ValueError, match="synthetic current runtime fence"):
        composition.build_local_indexing_service_runtime(capture, pin)
    checked.assert_called_once_with(
        service=grant.service,
        runtime_source_commit="e" * 40,
        configuration_sha256="sha256:" + "a" * 64,
    )
    engine.assert_not_called()


@pytest.mark.parametrize("missing", (False, True))
def test_factory_checks_both_installed_protocols_before_launcher_or_queue(monkeypatch, missing):
    from eom_identity_service.local_indexing_runtime import (
        AuthenticatedLocalIndexingRuntime,
        LocalIndexingRuntimePin,
    )

    capture = object.__new__(AuthenticatedLocalIndexingRuntime)
    _scope, _compiled, grant = mixed_scope()
    pin = LocalIndexingRuntimePin(grant.service, "e" * 40, "sha256:" + "a" * 64)
    monkeypatch.setattr(
        AuthenticatedLocalIndexingRuntime,
        "read_owner_configuration",
        lambda _: canonical_json_bytes(mixed_owner_document()),
    )
    monkeypatch.setattr(AuthenticatedLocalIndexingRuntime, "assert_current", Mock())
    engine, publisher = Mock(), MagicMock()
    monkeypatch.setattr(composition, "build_native_embedding_controller_engine", lambda: engine)
    monkeypatch.setattr(composition, "ControlFileSetPublisher", lambda *_: publisher)
    monkeypatch.setattr(composition, "PostgresLocalIndexingServiceFence", Mock())
    monkeypatch.setattr(composition, "CatalogLocalIndexingSourceAuthority", Mock())
    monkeypatch.setattr(composition, "CatalogIndexingRegistrySourceAuthority", Mock())
    monkeypatch.setattr(
        composition,
        "FixedIndexingRuntimeVerification",
        Mock(return_value=Mock(spec=composition.FixedIndexingRuntimeVerification)),
    )
    monkeypatch.setattr(composition, "catalog_runtime_privileges_ready", lambda _: True)
    order = []
    first = Mock(side_effect=lambda _: order.append("numeric1"))

    def require_mixed(_):
        order.append("ownership2")
        if missing:
            raise ValueError("synthetic missing mixed ownership protocol")

    monkeypatch.setattr(composition.EmbeddingEncodingReservationStorage, "require_protocol", first)
    monkeypatch.setattr(
        composition.EmbeddingEncodingReservationStorage,
        "require_mixed_ownership_protocol",
        require_mixed,
    )
    launcher = Mock(return_value=Mock(spec=composition.FixedNativeIndexLauncher))
    launcher.return_value.assert_current_runtime.side_effect = ValueError(
        "synthetic launcher boundary"
    )
    monkeypatch.setattr(composition, "FixedNativeIndexLauncher", launcher)
    with pytest.raises(ValueError, match="synthetic missing" if missing else "synthetic launcher"):
        composition.build_local_indexing_service_runtime(capture, pin)
    assert order == ["numeric1", "ownership2"]
    assert launcher.call_count == (0 if missing else 1)
    engine.dispose.assert_called_once()


@pytest.mark.parametrize("view", VIEWS)
def test_factory_leaf_preserves_exact_mixed_namespace_and_current_authority(monkeypatch, view):
    from types import SimpleNamespace

    selected = LocalIndexingMixedOwnerConfiguration.model_validate(mixed_owner_document())
    namespace = next(n for n in selected.namespaces if n.view == view)
    publisher = MagicMock()
    owner_factory = Mock()
    monkeypatch.setattr(
        composition.CatalogLocalEmbeddingOwnerAdmission, "for_indexing_service", owner_factory
    )
    for name in (
        "CatalogNativeEmbeddingExecutor",
        "WorkflowRunner",
        "LocalEmbeddingServiceReconciliation",
    ):
        monkeypatch.setattr(composition, name, Mock())
    authority, launcher = Mock(), Mock()
    pin = SimpleNamespace(
        service=SimpleNamespace(service_id="localindexservice_" + "a" * 32),
        runtime_source_commit="e" * 40,
    )
    result = composition._build_namespace_runtime(
        Mock(), publisher, authority, selected, namespace, pin, Mock(), launcher
    )
    assert result.namespace == namespace
    assert owner_factory.call_args.args[1].registry.namespace == namespace
    assert owner_factory.call_args.kwargs["source_authority"] is authority
    assert (
        composition.WorkflowRunner.call_args.kwargs["command_actor_selection"].namespace
        == namespace
    )
    backend = composition.CatalogNativeEmbeddingExecutor.call_args.kwargs["execution_backend"]
    assert type(backend) is composition.FixedCpuDocumentEmbeddingExecution
    assert backend.launcher is launcher
