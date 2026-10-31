"""Actual Registry transaction/replay logic with synthetic IAM/storage and a memory DB.

No PostgreSQL, model, runtime activation or source-authority claim is made here.
The later guarded database suite owns actual constraints/concurrent transactions.
"""

from pathlib import Path

import pytest
from eom_catalog_contracts.inference_transfer_experiment import population_sha256
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from eom_catalog_contracts.public_solution_embedding_registry import (
    RegisterPublicSolutionIndexCommand,
)
from eom_catalog_contracts.registered_public_solution_index import PublicSolutionEmbeddingIndexV4
from eom_catalog_contracts.registered_public_solution_registry import (
    PublicSolutionIndexRegistrationResultV4,
    RegisterPublicSolutionIndexCommandV4,
    validate_public_solution_registration_result_v4,
)
from eom_catalog_contracts.validation import load_schema, validate_contract
from eom_catalog_service import embedding_registry_application as application
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
    RegisteredEmbeddingIndexRead,
)
from eom_catalog_service.embedding_registry_repository import (
    PUBLIC_SOLUTION_ASSOCIATION_COLUMNS,
    artifact_member,
)
from eom_catalog_service.public_solution_index_assembly import assemble_public_solution_binding
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema import Draft202012Validator

from tests.unit.embedding_registry_application_fixtures import (
    MemoryRepository,
    MemorySession,
    SyntheticVerifier,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.test_embedding_registry_contracts import registration_command
from tests.unit.test_public_solution_index_assembly import assemble, setup
from tests.unit.test_registered_public_solution_index import registered_index_entry

CALLER = EmbeddingRegistryCaller("operator_" + "1" * 32)


def _base(entry, seed):
    value = entry.model_dump(mode="json")
    value["base_analysis_run_id"] = "analysisrun_" + seed * 32
    if "solution" in value["evidence"]:
        pointer = value["evidence"]["solution"]
        pointer["base_analysis_run_id"] = value["base_analysis_run_id"]
        pointer["pointer_sha256"] = seal(pointer, "pointer_sha256")["pointer_sha256"]
    return type(entry).model_validate(seal(value, "entry_sha256"))


def _member(index, seed):
    return ArtifactMemberPointer(
        artifact_id="artifact_" + seed * 32,
        artifact_revision_id="rev_" + seed * 32,
        member_path="index.json",
        schema_ref="eom://schemas/knowledge/" + index.schema_version,
        media_type="application/json",
        sha256=content_sha256(index.model_dump(mode="json")),
    )


def _command(index, pointer, entries, namespace, previous=None, generation=1):
    body = registration_command().model_dump(mode="json")
    registered = isinstance(index, PublicSolutionEmbeddingIndexV4)
    body.update(
        schema_version="embedding-registry-registration-command/4.0"
        if registered
        else "embedding-registry-registration-command/3.0",
        namespace=namespace.model_dump(mode="json"),
        index_id=index.index_id,
        index_revision_id=index.index_revision_id,
        index_manifest=pointer.model_dump(mode="json"),
        index_sha256=index.index_sha256,
        graph_snapshot=entries[0].graph_snapshot.model_dump(mode="json"),
        policy_revision_id=entries[0].policy_revision_id,
        policy_sha256=entries[0].policy_sha256,
        expected_current_index_revision_id=None if previous is None else previous.index_revision_id,
        expected_lock_version=generation,
        operation_key="registered-public:" + str(generation),
        source_set_sha256=population_sha256(tuple(entry.source for entry in entries)),
        binding_set_sha256=content_sha256([binding.binding_sha256 for binding in index.bindings]),
        eligible_source_count=len(entries),
        binding_count=len(index.bindings),
    )
    model = (
        RegisterPublicSolutionIndexCommandV4 if registered else RegisterPublicSolutionIndexCommand
    )
    return model.model_validate(seal(body, "request_sha256"))


def cases():
    from eom_catalog_service.embedding_registry_ports import ResolvedEmbeddingRegistration

    data = setup(device="CUDA")
    entries, rows, shards, namespace, space = data
    old = tuple(
        _base(entry, "a" if entry.evidence.kind == "ACCEPTED_SOLUTION_ANALYSIS" else "b")
        for entry in entries
    )
    parent = assemble((old, rows, shards, namespace, space)).index
    parent_pointer = _member(parent, "c")
    ai = _base(registered_index_entry(), "c")
    binding = assemble_public_solution_binding(ai, row=rows[0], space=space, namespace=namespace)
    selected = tuple(sorted((*old, ai), key=lambda entry: entry.source.item_revision_id))
    body = parent.model_dump(mode="json")
    body.update(
        schema_version="embedding-index-manifest/4.0",
        index_revision_id="embeddingindexrev_" + "4" * 32,
        previous_manifest=parent_pointer.model_dump(mode="json"),
        bindings=[
            value.model_dump(mode="json")
            for value in sorted(
                (*parent.bindings, binding), key=lambda value: value.source.item_revision_id
            )
        ],
    )
    current = PublicSolutionEmbeddingIndexV4.model_validate(seal(body, "index_sha256"))
    result = []
    for index, pointer, values, previous, generation in (
        (parent, parent_pointer, old, None, 1),
        (current, _member(current, "d"), selected, (parent_pointer, parent), 2),
    ):
        command = _command(
            index, pointer, values, namespace, None if previous is None else previous[1], generation
        )
        resolved = ResolvedEmbeddingRegistration(
            command.corpus_id,
            index,
            shards,
            previous,
            tuple(entry.source for entry in values),
            values,
            base_analysis_run_ids=tuple(
                (entry.source.item_revision_id, entry.base_analysis_run_id) for entry in values
            ),
        )
        result.append((command, resolved))
    return tuple(result)


class PublicMemoryRepository(MemoryRepository):
    """Same in-memory transaction/CAS, with the existing public ledger key fields."""

    def bindings(self, keys):
        wanted = {key.columns() for key in keys}
        return {
            digest: row
            for digest, row in self.session.state["bindings"].items()
            if row.evidence_kind == "PUBLIC_SOLUTION_REPORT"
            and tuple(getattr(row, name) for name in PUBLIC_SOLUTION_ASSOCIATION_COLUMNS) in wanted
        }

    def read_pinned_revision(self, index_id, revision_id):
        row = self.revision(revision_id)
        head = self.head(index_id)
        if row is None or head is None or row.index_id != index_id:
            return None
        return RegisteredEmbeddingIndexRead(
            head.corpus_id,
            PublicSolutionIndexNamespace.model_validate(
                {name: getattr(head, name) for name in PublicSolutionIndexNamespace.model_fields}
            ),
            row.index_id,
            row.index_revision_id,
            artifact_member(row, "manifest_"),
            row.index_sha256,
            row.graph_snapshot_revision_id,
            row.policy_revision_id,
            row.policy_sha256,
            row.binding_count,
            row.binding_set_sha256,
        )


@pytest.fixture
def memory(monkeypatch):
    values = cases()
    monkeypatch.setattr(application, "EmbeddingRegistryRepository", PublicMemoryRepository)
    return MemorySession(), SyntheticVerifier(*(capture for _command, capture in values)), values


def register(session, owner, command):
    return application.register_embedding_index(session, CALLER, command, owner, now=NOW)


def test_existing_transaction_registers_index4_once_reuses_vectors_and_preserves_binding3_origins(
    memory,
):
    session, owner, ((old, parent), (command, current)) = memory
    register(session, owner, old)
    origins = {
        key: artifact_member(row, "binding_manifest_")
        for key, row in session.state["bindings"].items()
    }
    result = register(session, owner, command)
    assert isinstance(result, PublicSolutionIndexRegistrationResultV4)
    assert len(session.state["encodings"]) == 1 and len(session.state["bindings"]) == 3
    assert len(session.state["revisions"]) == 2
    assert (
        application.verify_embedding_index_registration_observation(
            session, CALLER, command, result, owner
        )
        == current
    )
    assert all(
        artifact_member(session.state["bindings"][key], "binding_manifest_") == pointer
        for key, pointer in origins.items()
    )
    replay = register(session, owner, command)
    assert replay.replayed and replay.is_current
    historical = register(session, owner, old)
    assert historical.replayed and not historical.is_current
    assert historical.current_index_revision_id == command.index_revision_id
    assert (
        session.state["heads"][command.index_id].current_index_revision_id
        == command.index_revision_id
    )
    assert parent.index.bindings == tuple(
        value
        for value in current.index.bindings
        if value.schema_version == "embedding-source-binding/3.0"
    )


def test_interrupted_cas_rolls_back_new_binding_and_replay_can_continue_without_duplicate_encoding(
    memory,
):
    session, owner, ((old, _), (command, _)) = memory
    register(session, owner, old)
    session.cas_succeeds = False
    with pytest.raises(EmbeddingRegistryError, match="STALE_CURRENT"):
        register(session, owner, command)
    assert len(session.state["encodings"]) == 1 and len(session.state["bindings"]) == 2
    assert len(session.state["revisions"]) == 1
    session.cas_succeeds = True
    assert not register(session, owner, command).replayed
    assert len(session.state["bindings"]) == 3


def test_replay_still_checks_actual_authority_and_current_source(memory):
    session, owner, ((old, _), (command, _)) = memory
    register(session, owner, old)
    register(session, owner, command)
    owner.item_state = "REVOKED"
    with pytest.raises(EmbeddingRegistryError, match="FORBIDDEN"):
        register(session, owner, command)
    assert len(session.state["revisions"]) == 2


@pytest.mark.parametrize("fault", ["pointer", "raw_float", "extra", "coverage", "self_parent"])
def test_new_registry_contract_refuses_coercion_foreign_schema_or_bad_head(fault):
    command = cases()[1][0]
    value = command.model_dump(mode="json")
    if fault == "pointer":
        value["index_manifest"]["schema_ref"] = (
            "eom://schemas/knowledge/embedding-index-manifest/3.0"
        )
    elif fault == "raw_float":
        value["expected_lock_version"] = float(value["expected_lock_version"])
    elif fault == "extra":
        value["administrator_override"] = True
    elif fault == "coverage":
        value["binding_count"] = value["eligible_source_count"] + 1
    else:
        value["expected_current_index_revision_id"] = value["index_revision_id"]
    with pytest.raises(ValueError):
        RegisterPublicSolutionIndexCommandV4.model_validate(
            value if fault == "raw_float" else seal(value, "request_sha256")
        )


def test_new_result_binds_exact_command_and_packaged_schema(memory):
    session, owner, ((old, _), (command, _)) = memory
    register(session, owner, old)
    result = register(session, owner, command)
    assert validate_public_solution_registration_result_v4(command, result) == result
    changed = result.model_dump(mode="json")
    changed["operation_key"] = "other-operation"
    changed = PublicSolutionIndexRegistrationResultV4.model_validate(seal(changed, "result_sha256"))
    with pytest.raises(ValueError):
        validate_public_solution_registration_result_v4(command, changed)
    root = Path(__file__).resolve().parents[2]
    relative = "knowledge/public-solution-embedding-registry-v4.schema.json"
    assert (root / "schemas" / relative).read_bytes() == (
        root / "packages/catalog_contracts/eom_catalog_contracts/resources" / relative
    ).read_bytes()
    Draft202012Validator.check_schema(load_schema("public-solution-embedding-registry-v4"))
    validate_contract("public-solution-embedding-registry-v4", result.model_dump(mode="json"))
    assert canonical_json_bytes(result) != canonical_json_bytes(command)
