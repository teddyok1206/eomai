"""Independent partial public indexes; no authority, model or runtime activation."""

import pytest
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionEmbeddingIndex
from eom_catalog_service.embedding_device_index_pair import (
    EmbeddingDeviceIndexPairError,
    choose_public_solution_device_indexes,
    pair_embedding_device_indexes,
)
from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_public_solution_index_assembly import assemble, setup


def coverage(device, count):
    data = setup(device=device, different_text=True)
    seed = "2" if device == "CPU" else "3"
    index = assemble(data, rows=data[1][:count], revision=seed).index
    index = PublicSolutionEmbeddingIndex.model_validate(
        seal(
            index.model_dump(mode="json") | {"index_id": "embeddingindex_" + seed * 32},
            "index_sha256",
        )
    )
    return member(index, seed), index


def member(index, seed):
    return ArtifactMemberPointer(
        artifact_id="artifact_" + seed * 32,
        artifact_revision_id="rev_" + seed * 32,
        member_path="index.json",
        schema_ref="eom://schemas/knowledge/embedding-index-manifest/3.0",
        media_type="application/json",
        sha256=content_sha256(index.model_dump(mode="json")),
    )


@pytest.mark.parametrize("counts", ((1, 2), (2, 1), (2, 2)))
def test_public_partial_counts_are_independent_but_original_pins_stay_exact(counts):
    cpu_member, cpu = coverage("CPU", counts[0])
    cuda_member, cuda = coverage("CUDA", counts[1])
    arguments = dict(cpu_member=cpu_member, cpu_index=cpu, cuda_member=cuda_member, cuda_index=cuda)
    selected = choose_public_solution_device_indexes(**arguments)
    assert (selected.cpu_target_count, selected.cuda_target_count) == counts
    assert selected.select("CPU").manifest == cpu_member
    assert selected.select("CUDA").manifest == cuda_member
    assert not hasattr(selected, "target_count")
    if counts[0] != counts[1]:
        with pytest.raises(EmbeddingDeviceIndexPairError, match="TARGET_SET_MISMATCH"):
            pair_embedding_device_indexes(**arguments)


@pytest.mark.parametrize("fault", ("policy", "lineage", "hash", "device"))
def test_partial_coverage_does_not_allow_conflicting_shared_proofs_or_bad_members(fault):
    cpu_member, cpu = coverage("CPU", 2)
    cuda_member, cuda = coverage("CUDA", 2)
    if fault in {"policy", "lineage"}:
        body = cuda.model_dump(mode="json")
        binding = next(
            b
            for b in body["bindings"]
            if b["evidence"]["kind"] == "REGISTERED_CREATIVE_SOURCE_REPORT"
        )
        if fault == "policy":
            binding["policy_sha256"] = "sha256:" + "f" * 64
        else:
            binding["evidence"]["lineage_sha256"] = "sha256:" + "f" * 64
        binding.update(seal(binding, "binding_sha256"))
        cuda = PublicSolutionEmbeddingIndex.model_validate(seal(body, "index_sha256"))
        cuda_member = member(cuda, "3")
    elif fault == "hash":
        cuda_member = cuda_member.model_copy(update={"sha256": "sha256:" + "f" * 64})
    else:
        cpu, cuda = cuda, cpu
        cpu_member, cuda_member = cuda_member, cpu_member
    with pytest.raises(EmbeddingDeviceIndexPairError):
        choose_public_solution_device_indexes(
            cpu_member=cpu_member, cpu_index=cpu, cuda_member=cuda_member, cuda_index=cuda
        )
