"""Concrete readiness and exact selected-owner controls; not runtime/source activation."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service.embedding_registry_catalog_adapter import (
    EmbeddingRegistryOwnerConfiguration,
)
from eom_orchestrator.native_embedding_index_systemd import FixedNativeIndexLauncher
from eom_workflow_runner.document_embedding_cpu_execution import FixedCpuDocumentEmbeddingExecution
from eom_workflow_runner.local_embedding_native_executor import CatalogNativeEmbeddingExecutor
from eom_workflow_runner.local_embedding_owner_admission import LocalEmbeddingOwnerConfiguration

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_admission_fixtures import native_fixture
from tests.unit.test_control_file_set_publication import _publisher


@pytest.fixture
def executor(tmp_path):
    fixture = native_fixture()
    profile = fixture.policy.profiles[0]
    config = LocalEmbeddingOwnerConfiguration(
        EmbeddingRegistryOwnerConfiguration(
            fixture.plan.corpus_id,
            fixture.plan.namespace,
            profile.space,
            fixture.plan.recipe,
            ("PAST_EXAM",),
        ),
        fixture.request.native_execution_policy,
        fixture.request.native_execution_policy_sha256,
    )
    owner = SimpleNamespace(configuration=config, identity=Mock())
    launcher = Mock(spec=FixedNativeIndexLauncher)
    publisher, _ = _publisher(tmp_path)
    return (
        fixture,
        CatalogNativeEmbeddingExecutor(
            owner=owner,
            publisher=publisher,
            execution_backend=FixedCpuDocumentEmbeddingExecution(launcher),
            runtime_profile=profile,
            source_commit="a" * 40,
        ),
        launcher,
        owner,
    )


def test_readiness_reads_installed_closure_without_authentication_claim_or_model(executor) -> None:
    fixture, service, launcher, owner = executor
    assert service.evaluate(fixture.request).ready
    launcher.assert_current_runtime.assert_called_once()
    launcher.run.assert_not_called()
    owner.identity.fence_current_operator.assert_not_called()


@pytest.mark.parametrize(
    "field", ["source_policy", "source_hash", "namespace", "space", "installed"]
)
def test_wrong_configured_controls_fail_before_model_or_scope_mutation(executor, field) -> None:
    fixture, service, launcher, owner = executor
    body = fixture.request.model_dump(mode="json")
    if field == "source_policy":
        body["native_execution_policy"]["artifact_revision_id"] = "rev_" + "f" * 32
    if field == "source_hash":
        body["native_execution_policy_sha256"] = "sha256:" + "f" * 64
    if field == "namespace":
        body["namespace"]["view"] = "METADATA_ONLY"
    if field == "space":
        service.runtime_profile = native_fixture(device="CUDA").policy.profiles[0]
    if field == "installed":
        launcher.assert_current_runtime.side_effect = ValueError("synthetic installed mismatch")
    request = type(fixture.request).model_validate(seal(body, "request_sha256"))
    assert not service.evaluate(request).ready
    launcher.run.assert_not_called()
    owner.identity.fence_current_operator.assert_not_called()
