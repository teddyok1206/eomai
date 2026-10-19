"""Closed mixed reference selection with synthetic provider/filesystem IO, no activation."""

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_identity_service.installed_owner_session_provider import (
    ProtectedInstalledIdentityProviderAdmission,
)
from eom_workflow.private_chat_query_owner_configuration import (
    PrivateChatQueryServiceConfiguration,
    require_private_chat_query_reference_configuration,
)
from eom_workflow.reference_query_owner_configuration import (
    REFERENCE_QUERY_MIXED_OWNER_SCHEMA_SHA256,
    REFERENCE_QUERY_OWNER_SCHEMA_SHA256,
    ReferenceQueryOwnerConfigurationError,
    ReferenceQueryServiceConfiguration,
    ReferenceQueryServiceConfigurationV2,
    parse_reference_query_service_configuration,
    parse_supported_reference_query_service_configuration,
    reference_query_service_configuration_bytes,
    require_mixed_reference_query_cohost,
    supported_reference_query_service_configuration_bytes,
    validate_supported_reference_query_service_configuration,
)
from eom_workflow_runner import reference_query_owner_runtime as runtime

from tests.unit.test_installed_identity_provider_observation import observation as observation
from tests.unit.test_private_chat_query_owner_configuration import private_body
from tests.unit.test_reference_query_owner_admission import source as source
from tests.unit.test_reference_query_owner_configuration import owner_body
from tests.unit.test_reference_query_owner_runtime import configuration

ROOT = Path(__file__).resolve().parents[2]


def mixed_body(source):
    body = owner_body(source)
    body["schema_version"] = "reference-query-owner-configuration/2.0"
    body["namespace"].update(
        projection_version="mixed-solution-comparison/2.0",
        population_scope="ALL_ADMITTED_GRAPH_ITEMS",
    )
    return body


def test_schema2_mirror_pins_and_roundtrip_preserve_strict_legacy_selection(source):
    for version, expected in (
        (1, REFERENCE_QUERY_OWNER_SCHEMA_SHA256),
        (2, REFERENCE_QUERY_MIXED_OWNER_SCHEMA_SHA256),
    ):
        name = f"reference-query-owner-configuration-v{version}.schema.json"
        raw = (ROOT / "schemas/workflow" / name).read_bytes()
        assert raw == (ROOT / "packages/workflow/eom_workflow/resources" / name).read_bytes()
        assert sha256_bytes(raw) == expected
    old = ReferenceQueryServiceConfiguration.model_validate(owner_body(source))
    old_raw = reference_query_service_configuration_bytes(old)
    assert (
        parse_supported_reference_query_service_configuration(old_raw)
        == parse_reference_query_service_configuration(old_raw)
        == old
    )
    body = mixed_body(source)
    raw = canonical_json_bytes(body)
    selected = parse_supported_reference_query_service_configuration(raw)
    assert type(selected) is ReferenceQueryServiceConfigurationV2
    assert not isinstance(selected, ReferenceQueryServiceConfiguration)
    assert supported_reference_query_service_configuration_bytes(selected) == raw
    assert selected.source_classes == old.source_classes
    assert (
        selected.api_provider == old.api_provider and selected.runtime_bundle == old.runtime_bundle
    )
    with pytest.raises(ReferenceQueryOwnerConfigurationError):
        parse_reference_query_service_configuration(raw)
    with pytest.raises(ReferenceQueryOwnerConfigurationError):
        reference_query_service_configuration_bytes(selected)


@pytest.mark.parametrize(
    "fault",
    (
        "projection",
        "population",
        "recipe",
        "role",
        "bool",
        "unknown",
        "authority",
        "provider",
        "cuda",
        "newline",
        "duplicate",
        "budget",
    ),
)
def test_mixed_configuration_never_widens_or_normalizes_untrusted_selection(source, fault):
    body = mixed_body(source)
    if fault == "projection":
        body["namespace"]["projection_version"] = "accepted-solution-comparison/1.0"
    elif fault == "population":
        body["namespace"]["population_scope"] = "OCCURRENCE_BACKED_PAST_EXAM"
    elif fault == "recipe":
        body["namespace"]["recipe_sha256"] = "sha256:" + "0" * 64
    elif fault == "role":
        body["database_owner"]["role_name"] = "postgres"
    elif fault == "bool":
        body["database_owner"]["role_oid"] = True
    elif fault == "unknown":
        body["schema_version"] = "reference-query-owner-configuration/3.0"
    elif fault == "authority":
        body["roles"] = ["ADMIN"]
    elif fault == "provider":
        body["api_provider"]["code_members"][0]["path"] = "/tmp/evil.py"
    elif fault == "cuda":
        body["native_backend"] = {"device": "CUDA"}
    raw = canonical_json_bytes(body)
    if fault == "newline":
        raw += b"\n"
    elif fault == "duplicate":
        raw = raw[:-1] + b',"schema_version":"reference-query-owner-configuration/2.0"}'
    elif fault == "budget":
        raw = b" " * 65537
    with pytest.raises(ReferenceQueryOwnerConfigurationError):
        parse_supported_reference_query_service_configuration(raw)


@pytest.mark.parametrize("fault", ("root", "namespace", "provider", "constructed"))
def test_copied_models_are_checked_before_serialization_or_runtime_provider(
    source, monkeypatch, fault
):
    selected = ReferenceQueryServiceConfigurationV2.model_validate(mixed_body(source))
    if fault == "root":
        selected = selected.model_copy(update={"permissions": ["ADMIN"]})
    elif fault == "namespace":
        selected = selected.model_copy(
            update={"namespace": selected.namespace.model_copy(update={"permission": "ADMIN"})}
        )
    elif fault == "provider":
        selected = selected.model_copy(
            update={
                "api_provider": selected.api_provider.model_copy(update={"secret": "synthetic"})
            }
        )
    else:
        selected = ReferenceQueryServiceConfigurationV2.model_construct(
            schema_version="reference-query-owner-configuration/2.0"
        )
    for call in (
        validate_supported_reference_query_service_configuration,
        supported_reference_query_service_configuration_bytes,
    ):
        with pytest.raises(ReferenceQueryOwnerConfigurationError):
            call(selected)
    provider = Mock(side_effect=AssertionError("must validate raw configuration before provider"))
    monkeypatch.setattr(runtime, "require_current_reference_query_provider", provider)
    with pytest.raises(ReferenceQueryOwnerConfigurationError):
        runtime.build_reference_query_owner_runtime(selected, object())
    provider.assert_not_called()


def test_private_chat1_is_not_silently_promoted_to_the_mixed_reference_runtime(source):
    old = ReferenceQueryServiceConfiguration.model_validate(owner_body(source))
    # The shared supervisor will keep this primary1; optional mixed2 is a separate runtime.
    selected = ReferenceQueryServiceConfigurationV2.model_validate(mixed_body(source))
    body = private_body(source, old)
    body["native_execution_policy"]["schema_ref"] = (
        "eom://schemas/workflow/private-chat-query-execution-policy/1.0"
    )
    private = PrivateChatQueryServiceConfiguration.model_validate(body)
    with pytest.raises(ReferenceQueryOwnerConfigurationError):
        require_private_chat_query_reference_configuration(private, selected)


def test_cohost_guard_only_compares_deployment_identity_not_source_authority(source):
    primary = ReferenceQueryServiceConfiguration.model_validate(owner_body(source))
    mixed = ReferenceQueryServiceConfigurationV2.model_validate(mixed_body(source))
    assert require_mixed_reference_query_cohost(primary, mixed) is None
    # Each actual runtime must still independently resolve its controls/source policy.
    different_controls = mixed_body(source)
    different_controls["native_execution_policy_sha256"] = "sha256:" + "9" * 64
    assert (
        require_mixed_reference_query_cohost(
            primary, ReferenceQueryServiceConfigurationV2.model_validate(different_controls)
        )
        is None
    )


@pytest.mark.parametrize(
    "fault",
    (
        "owner",
        "provider_source",
        "provider_wheel",
        "provider_configuration",
        "provider_member",
        "database_oid",
        "primary_extra",
        "mixed_extra",
        "nested_extra",
        "old_as_mixed",
        "mixed_as_primary",
    ),
)
def test_cohost_guard_revalidates_exact_families_and_independent_deployment_pins(source, fault):
    primary = ReferenceQueryServiceConfiguration.model_validate(owner_body(source))
    body = mixed_body(source)
    if fault == "owner":
        body["owner_source_commit"] = "0" * 40
    elif fault in {"provider_source", "provider_wheel", "provider_configuration"}:
        field = {
            "provider_source": "source_commit",
            "provider_wheel": "wheel_sha256",
            "provider_configuration": "configuration_sha256",
        }[fault]
        body["api_provider"][field] = "0" * 40 if field == "source_commit" else "sha256:" + "0" * 64
    elif fault == "provider_member":
        body["api_provider"]["code_members"][0]["sha256"] = "sha256:" + "0" * 64
    elif fault == "database_oid":
        body["database_owner"]["role_oid"] += 1
    mixed = ReferenceQueryServiceConfigurationV2.model_validate(body)
    if fault == "primary_extra":
        primary = primary.model_copy(update={"permissions": ["ADMIN"]})
    elif fault == "mixed_extra":
        mixed = mixed.model_copy(update={"permissions": ["ADMIN"]})
    elif fault == "nested_extra":
        mixed = mixed.model_copy(
            update={
                "api_provider": mixed.api_provider.model_copy(update={"credential": "synthetic"})
            }
        )
    elif fault == "old_as_mixed":
        mixed = primary
    elif fault == "mixed_as_primary":
        primary = mixed
    with pytest.raises(ValueError):
        require_mixed_reference_query_cohost(primary, mixed)


def test_actual_factory_keeps_cpu_controls_and_exact_mixed_namespace(
    source, observation, monkeypatch
):
    from eom_workflow.reference_query_execution import parse_reference_query_execution_policy

    from tests.unit.inference_transfer_embedding_fixtures import seal
    from tests.unit.test_native_embedding_query_handoff import prepared

    policy = parse_reference_query_execution_policy(
        seal(
            source.policy.model_dump(mode="json")
            | {"resource_profile": prepared().policy.resource_profile.model_dump(mode="json")},
            "policy_sha256",
        )
    )
    body = configuration(source, observation).model_dump(mode="json")
    body["schema_version"] = "reference-query-owner-configuration/2.0"
    body["namespace"].update(
        projection_version="mixed-solution-comparison/2.0",
        population_scope="ALL_ADMITTED_GRAPH_ITEMS",
    )
    body["native_execution_policy_sha256"] = policy.policy_sha256
    body["native_execution_policy"]["sha256"] = sha256_bytes(
        canonical_json_bytes(policy.model_dump(mode="json"))
    )
    selected = ReferenceQueryServiceConfigurationV2.model_validate(body)
    provider = ProtectedInstalledIdentityProviderAdmission(observation[0])
    identity = SimpleNamespace(owner_uid=1000, owner_gid=1000)
    monkeypatch.setattr(runtime, "fixed_owner_identity", lambda: identity)
    monkeypatch.setattr(runtime.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(runtime.os, "getegid", lambda: 1000)
    monkeypatch.setattr(runtime.os, "getgroups", lambda: [])
    monkeypatch.setattr(runtime, "protected_cpu_handoff_directory", lambda *_a, **_k: nullcontext())
    engine, publisher = Mock(), MagicMock()
    monkeypatch.setattr(runtime, "build_native_embedding_controller_engine", lambda: engine)
    monkeypatch.setattr(runtime, "ControlFileSetPublisher", lambda *_: publisher)
    monkeypatch.setattr(runtime, "require_reference_query_database_owner", Mock())
    monkeypatch.setattr(runtime, "PinnedArtifactReadContext", Mock())
    controls = Mock(return_value=(policy, Mock()))
    monkeypatch.setattr(runtime, "read_selected_reference_query_controls", controls)
    verifier = Mock(return_value=Mock(spec=runtime.FixedIndexingRuntimeVerification))
    launcher = Mock(return_value=Mock(spec=runtime.FixedNativeQueryLauncher))
    monkeypatch.setattr(runtime, "FixedIndexingRuntimeVerification", verifier)
    monkeypatch.setattr(runtime, "FixedNativeQueryLauncher", launcher)
    result = runtime.build_reference_query_owner_runtime(selected, provider)
    try:
        assert result.configuration == selected
        assert result.owner_configuration.registry.namespace == selected.namespace
        assert result.owner_configuration.registry.source_classes == selected.source_classes
        assert result.spaces == source.policy.spaces
        assert controls.call_args.kwargs["policy_member"] == selected.native_execution_policy
        assert controls.call_args.kwargs["runtime_bundle"] == selected.runtime_bundle
        assert launcher.call_args.args[:2] == (
            selected.cpu_environment_raw_sha256.removeprefix("sha256:"),
            selected.owner_environment_raw_sha256.removeprefix("sha256:"),
        )
        result.launcher.run.assert_not_called()
    finally:
        result.close()
