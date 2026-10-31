"""Exact metadata3/4 pins and independent coverage; no actual source/GPU grant."""

import pytest
from eom_catalog_service.embedding_device_index_pair import (
    EmbeddingDeviceIndexPairError,
    choose_public_solution_device_indexes,
    pair_embedding_device_indexes,
)
from eom_catalog_service.public_solution_index_assembly import (
    assemble_registered_public_solution_index,
)
from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.test_public_solution_index_assembly import assemble, setup
from tests.unit.test_registered_public_solution_index import registered_index_entry


def published_index(device, version):
    data = setup(device=device)
    seed = "c" if device == "CPU" else "d"
    if version == 4:
        entries, rows, shards, namespace, space = data
        result = assemble_registered_public_solution_index(
            tuple(
                sorted(
                    (*entries, registered_index_entry()), key=lambda e: e.source.item_revision_id
                )
            ),
            available_rows=rows,
            shards=shards,
            namespace=namespace,
            space=space,
            index_id="embeddingindex_" + seed * 32,
            index_revision_id="embeddingindexrev_" + seed * 32,
            previous_manifest=None,
            created_at=NOW,
        ).index
    else:
        original = assemble(data, revision=seed).index
        result = type(original).model_validate(
            seal(
                original.model_dump(mode="json") | {"index_id": "embeddingindex_" + seed * 32},
                "index_sha256",
            )
        )
    member = ArtifactMemberPointer(
        artifact_id="artifact_" + seed * 32,
        artifact_revision_id="rev_" + seed * 32,
        member_path="index.json",
        schema_ref="eom://schemas/knowledge/" + result.schema_version,
        media_type="application/json",
        sha256=content_sha256(result.model_dump(mode="json")),
    )
    return member, result


@pytest.mark.parametrize("versions", [(3, 4), (4, 3), (4, 4)])
def test_actual_index_families_keep_exact_members_and_independent_partial_coverage(versions):
    cpu_member, cpu = published_index("CPU", versions[0])
    cuda_member, cuda = published_index("CUDA", versions[1])
    arguments = dict(cpu_member=cpu_member, cpu_index=cpu, cuda_member=cuda_member, cuda_index=cuda)
    result = choose_public_solution_device_indexes(**arguments)
    assert result.select("CPU").manifest == cpu_member
    assert result.select("CUDA").manifest == cuda_member
    assert result.cpu_target_count == len(cpu.bindings)
    assert result.cuda_target_count == len(cuda.bindings)
    if versions[0] != versions[1]:
        # Released exact-target relation never silently becomes partial/mixed.
        with pytest.raises(EmbeddingDeviceIndexPairError, match="NAMESPACE_MISMATCH"):
            pair_embedding_device_indexes(**arguments)
    else:
        assert pair_embedding_device_indexes(**arguments).target_count == 3


@pytest.mark.parametrize("fault", ["member_schema", "member_hash", "shared_proof", "device"])
def test_migration_does_not_accept_relabelled_members_or_conflicting_shared_proofs(fault):
    cpu_member, cpu = published_index("CPU", 3)
    cuda_member, cuda = published_index("CUDA", 4)
    if fault == "member_schema":
        cuda_member = cuda_member.model_copy(update={"schema_ref": cpu_member.schema_ref})
    elif fault == "member_hash":
        cuda_member = cuda_member.model_copy(update={"sha256": "sha256:" + "0" * 64})
    elif fault == "shared_proof":
        body = cuda.model_dump(mode="json")
        binding = next(
            b for b in body["bindings"] if b["schema_version"] == "embedding-source-binding/3.0"
        )
        binding["policy_sha256"] = "sha256:" + "f" * 64
        binding.update(seal(binding, "binding_sha256"))
        cuda = type(cuda).model_validate(seal(body, "index_sha256"))
        cuda_member = cuda_member.model_copy(update={"sha256": content_sha256(cuda)})
    else:
        cpu_member, cuda_member, cpu, cuda = cuda_member, cpu_member, cuda, cpu
    with pytest.raises(EmbeddingDeviceIndexPairError):
        choose_public_solution_device_indexes(
            cpu_member=cpu_member, cpu_index=cpu, cuda_member=cuda_member, cuda_index=cuda
        )
