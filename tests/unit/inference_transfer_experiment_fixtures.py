"""Clearly labelled synthetic staged data; never a Catalog authorization receipt."""

from __future__ import annotations

from typing import Any

from eom_catalog_contracts.inference_transfer_experiment import (
    CanonicalExperimentItemText,
    ExperimentAdmissionScope,
    ExperimentBudget,
    ExperimentMetadataField,
    ExperimentViewRecipe,
    InferenceTransferExperimentRequest,
    StagedExperimentEntry,
    population_sha256,
    profile_set_sha256,
)
from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferProfile,
    InferenceTransferProfilePointer,
)
from eom_identifiers import content_sha256

from tests.unit.inference_transfer_fixtures import embedding_model, profile, sha


def entry(seed: str = "a", *, source_class: str = "PAST_EXAM") -> StagedExperimentEntry:
    body = profile(seed).model_dump(mode="json", exclude={"profile_sha256"})
    source = body["source_basis"]["source"]
    source["source_class"] = source_class
    source["item_id"] = "item_" + seed * 32
    source["item_revision_id"] = "itemrev_" + seed * 32
    source["artifact_member"].update(
        artifact_id="artifact_" + seed * 32,
        artifact_revision_id="rev_" + seed * 32,
        sha256=sha(seed),
    )
    parsed = InferenceTransferProfile.model_validate(
        body | {"profile_sha256": content_sha256(body)}
    )
    text = f"마찰이 없는 물체 {seed.upper()}의 속력은 36 km/h이다. 옳은 것을 고르시오."
    return StagedExperimentEntry(
        profile=parsed,
        content=CanonicalExperimentItemText(
            text=text,
            original_source=parsed.source_basis.source.artifact_member,
            text_sha256=content_sha256(text),
        ),
        metadata=(
            ExperimentMetadataField(
                key="CONCEPT",
                value="역학적 에너지",
                basis="ACCEPTED_SOLUTION",
                source_sha256=parsed.source_basis.solution_evidence.solution_report.sha256,
            ),
        ),
        limitations=("합성 입력: 실제 Catalog 인가 또는 실교육 품질 평가 증거가 아니다.",),
    )


def experiment_request(
    *entries: StagedExperimentEntry, **budget: Any
) -> InferenceTransferExperimentRequest:
    values = tuple(
        sorted(entries or (entry("a"), entry("b"), entry("c")), key=lambda e: e.profile.profile_id)
    )
    pointers = tuple(InferenceTransferProfilePointer.from_profile(e.profile) for e in values)
    recipe_body = ExperimentViewRecipe.model_construct(recipe_sha256=sha()).model_dump(
        mode="json", exclude={"recipe_sha256"}
    )
    recipe = ExperimentViewRecipe.model_validate(
        recipe_body | {"recipe_sha256": content_sha256(recipe_body)}
    )
    sources = tuple(
        sorted((e.profile.source_basis.source for e in values), key=lambda s: s.item_revision_id)
    )
    scope = ExperimentAdmissionScope(
        actor_id="synthetic-experiment",
        graph_snapshot=values[0].profile.source_basis.graph_snapshot,
        policy_revision_id="accessrev_" + "d" * 32,
        population_scope="ALL_ADMITTED_GRAPH_ITEMS",
        policy_sha256=sha("d"),
        population_sources=sources,
        population_sha256=population_sha256(sources),
        eligible_profile_set_sha256=profile_set_sha256(pointers),
        data_provenance="TEST_ONLY_SYNTHETIC",
        producer_admission="SYNTHETIC_NON_AUTHORITATIVE",
    )
    body = {
        "schema_version": "inference-transfer-experiment-request/1.0",
        "experiment_id": "embeddingexperiment_" + "1" * 32,
        "experiment_revision_id": "embeddingexperimentrev_" + "2" * 32,
        "scope": scope.model_dump(mode="json"),
        "model_spec": embedding_model("intfloat/multilingual-e5-small").model_dump(mode="json"),
        "recipe": recipe.model_dump(mode="json"),
        "entries": [e.model_dump(mode="json") for e in values],
        "queries": [pointers[0].model_dump(mode="json")],
        "baselines": [],
        "budget": ExperimentBudget(**({"minimum_common_candidates": 1} | budget)).model_dump(
            mode="json"
        ),
    }
    return InferenceTransferExperimentRequest.model_validate(
        body | {"request_sha256": content_sha256(body)}
    )
