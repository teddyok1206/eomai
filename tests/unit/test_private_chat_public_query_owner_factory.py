"""Common CPU leaf uses the existing private factory; origin/runtime seams are fixtures.

No routed GPU activation, production authentication or live numerical inference is performed.
"""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.public_solution_embedding_index import MAX_PUBLIC_SOLUTION_SOURCES
from eom_orchestrator.models import JobRecord
from eom_workflow.admission import workflow_definition_is_admitted
from sqlalchemy import func, select

from tests.unit import test_private_chat_query_owner_factory as legacy
from tests.unit.test_private_chat_public_query_execution import execution_case
from tests.unit.test_private_chat_public_query_source_owner import make_private_public_source_case


@pytest.fixture
def factory(tmp_path, monkeypatch):
    current = make_private_public_source_case(tmp_path, monkeypatch)
    source = SimpleNamespace(
        publisher=current.old.publisher,
        owner=current.owner,
        policy=current.policy,
        projection=current.old.projection,
    )
    with legacy.make_private_query_owner_factory_case(source, monkeypatch) as value:
        yield value


def test_common_cpu_leaf_retains_actual_origin_and_independent_owners(factory):
    legacy.test_each_original_gets_distinct_actual_private_owners_and_one_shared_finite_driver(
        factory
    )


def test_common_factory_carries_common_controls_and_bound_without_starting_work(factory):
    value = factory
    with value.source.publisher.sessions() as session:
        before = session.scalar(select(func.count()).select_from(JobRecord))
    dispatch = value.factory.application(value.source.projection.origin)
    config = dispatch.application.owner.configuration
    assert config is value.source.owner.configuration
    assert config.registry.namespace.view == "CONCRETE_FACETS"
    assert config.native_execution_policy.schema_ref.endswith(
        "private-chat-query-execution-policy/2.0"
    )
    assert dispatch.maximum_sources == MAX_PUBLIC_SOLUTION_SOURCES == 16384
    assert dispatch.top_k == 64
    assert not workflow_definition_is_admitted("local-embedding-private-chat-query", "2.0.0")
    with value.source.publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == before
    assert not value.factory.driver.observe().active


@pytest.mark.parametrize(
    "fault",
    (
        "source_denied",
        "origin_changed",
        "runtime_changed",
        "configuration_changed",
        "late_configuration_changed",
    ),
)
def test_common_current_denial_never_constructs_executor_or_runner(factory, monkeypatch, fault):
    legacy.test_current_origin_or_runtime_failure_never_constructs_executor_or_runner(
        factory, monkeypatch, fault
    )


@pytest.mark.parametrize(
    "fault", ("engine", "driver", "launcher", "chat", "source", "space", "configuration_guard")
)
def test_common_mixed_runtime_composition_is_rejected_before_source_rpc(factory, fault):
    legacy.test_mixed_composition_is_rejected_before_source_rpc(factory, fault)


def test_common_fixed_cpu_leaf_cannot_misrepresent_a_cuda_namespace_as_executable(factory):
    value = factory
    _, policy, _ = execution_case("CUDA")
    registry = value.factory.configuration.registry
    config = replace(
        value.factory.configuration,
        registry=replace(
            registry,
            space=policy.spaces.document,
            namespace=registry.namespace.model_copy(
                update={"space_sha256": policy.spaces.document.space_sha256}
            ),
        ),
    )
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_OWNER_COMPOSITION_INVALID"):
        replace(value.factory, configuration=config, spaces=policy.spaces)
    value.authorize.assert_not_called()
    assert not value.factory.driver.observe().active


def test_common_factory_never_uses_a_legacy_view_from_mutated_metadata(factory):
    value = factory
    registry = value.factory.configuration.registry
    with pytest.raises(ValueError):
        config = replace(
            value.factory.configuration,
            registry=replace(
                registry, namespace=registry.namespace.model_copy(update={"view": "CONTENT_ONLY"})
            ),
        )
        replace(value.factory, configuration=config)
    value.authorize.assert_not_called()
