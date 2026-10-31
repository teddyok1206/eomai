"""Actual local index4/shard bytes; source/IAM/ledger ports are explicitly synthetic."""

from dataclasses import replace

import pytest
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryError
from eom_orchestrator.models import ArtifactRecord

from tests.unit.test_embedding_registry_catalog_adapter import owner as owner
from tests.unit.test_public_solution_registry_read import invoke
from tests.unit.test_public_solution_registry_read import public_read as public_read


@pytest.mark.parametrize("public_read", ["registered"], indirect=True)
def test_actual_reader4_resolves_all_three_proof_families_and_one_unchanged_row(public_read):
    observed = invoke(public_read)
    assert observed.available_binding_count == len(observed.profiles) == 3
    assert len(observed.numerical_rows) == 1
    assert {binding.evidence.kind for binding in observed.bindings} == {
        "ACCEPTED_SOLUTION_ANALYSIS",
        "REGISTERED_CREATIVE_SOURCE_REPORT",
        "ACCEPTED_REGISTERED_SOLUTION_ANALYSIS",
    }
    assert {profile.profile.schema_ref for profile in observed.profiles} == {
        "eom://schemas/knowledge/public-solution-embedding-entry/1.0",
        "eom://schemas/knowledge/public-solution-embedding-entry/2.0",
    }


@pytest.mark.parametrize("fault", ["binary", "revoked", "report", "old_selection"])
@pytest.mark.parametrize("public_read", ["registered"], indirect=True)
def test_actual_reader4_keeps_physical_hash_lifecycle_and_report_validation(
    public_read, monkeypatch, fault
):
    value = public_read
    if fault == "binary":
        (
            value.root / value.shard.artifact_id / value.shard.artifact_revision_id / "vectors.f32"
        ).write_bytes(b"bad")
    elif fault == "revoked":
        value.session.get(ArtifactRecord, value.shard.artifact_id).approved = False
    elif fault == "old_selection":
        value.intent = replace(value.intent, selection=value.original_request.views[0])
    else:
        original = value.verifier._captured_lookup

        def changed(*args):
            current = original(*args)
            return replace(
                current,
                entries=tuple(
                    entry.model_copy(update={"permission_override": True})
                    if entry.schema_version == "public-solution-embedding-entry/2.0"
                    else entry
                    for entry in current.entries
                ),
            )

        monkeypatch.setattr(value.verifier, "_captured_lookup", changed)
    with pytest.raises(EmbeddingRegistryError):
        invoke(value)
