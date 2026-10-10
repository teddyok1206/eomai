"""Synthetic snapshot values; self-consistent hashes are not real owner authorization."""

from __future__ import annotations

from typing import Any

from eom_catalog_contracts.inference_transfer_experiment import (
    StagedExperimentEntry,
    SuppliedGraphBaseline,
    population_sha256,
    profile_set_sha256,
)
from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotChunkBudget,
    InferenceTransferSnapshotHeader,
    InferenceTransferSnapshotIndexEntry,
    InferenceTransferSnapshotPrepareRequest,
    InferenceTransferSnapshotPrepareResult,
    InferenceTransferSnapshotReadRequest,
    InferenceTransferSnapshotReadResult,
    InferenceTransferSnapshotRecord,
    snapshot_index_sha256,
)
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_catalog_contracts.knowledge import ApprovedPastExamItemKnowledgeSourceV3
from eom_catalog_contracts.models import FrozenModel
from eom_identifiers import content_sha256

from tests.unit.inference_transfer_experiment_fixtures import entry, experiment_request
from tests.unit.inference_transfer_fixtures import sha


def hashed[T: FrozenModel](model: type[T], hash_field: str, **values: Any) -> T:
    def json_value(value: Any) -> Any:
        if isinstance(value, FrozenModel):
            return value.model_dump(mode="json")
        if isinstance(value, dict):
            return {key: json_value(child) for key, child in value.items()}
        if isinstance(value, (list, tuple)):
            return [json_value(child) for child in value]
        return value

    body = {
        name: json_value(field.default)
        for name, field in model.model_fields.items()
        if not field.is_required() and name != hash_field
    }
    body.update({name: json_value(value) for name, value in values.items()})
    return model.model_validate(body | {hash_field: content_sha256(body)})


def snapshot_records(
    *, missing_seed: str | None = None
) -> tuple[InferenceTransferSnapshotRecord, ...]:
    records = []
    for seed in ("a", "b", "c"):
        body = entry(seed).model_dump(mode="json")
        solution = body["profile"]["source_basis"]["solution_evidence"]
        solution["base_analysis_run_id"] = "analysisrun_" + seed * 32
        solution.pop("pointer_sha256")
        solution["pointer_sha256"] = content_sha256(solution)
        profile = body["profile"]
        profile["extraction"]["extractor_version"] = "accepted-solution-comparison/1.0"
        profile.pop("profile_sha256")
        profile["profile_sha256"] = content_sha256(profile)
        staged = StagedExperimentEntry.model_validate(body)
        source = staged.profile.source_basis.source
        missing = seed == missing_seed
        index = InferenceTransferSnapshotIndexEntry(
            base_analysis_run_id=solution["base_analysis_run_id"],
            source_item_id=source.item_id,
            source_item_revision_id=source.item_revision_id,
            source_value_sha256=content_sha256(source.model_dump(mode="json")),
            profile=None
            if missing
            else InferenceTransferProfilePointer.from_profile(staged.profile),
            solution_evidence_pointer_sha256=None if missing else solution["pointer_sha256"],
        )
        records.append(
            InferenceTransferSnapshotRecord(
                index_entry=index, source=source, staged_entry=None if missing else staged
            )
        )
    return tuple(records)


def snapshot_v3_record() -> InferenceTransferSnapshotRecord:
    """Full synthetic page chain with a deliberately core-V2 profile basis."""
    original = snapshot_records()[0]
    assert original.staged_entry is not None
    staged_body = original.staged_entry.model_dump(mode="json")
    core_source = staged_body["profile"]["source_basis"]["source"]
    core_source["artifact_member"].update(
        materialized_path="source/item-content.json", logical_name="item-content.json"
    )
    staged_body["profile"].pop("profile_sha256")
    staged_body["profile"]["profile_sha256"] = content_sha256(staged_body["profile"])
    staged_body["content"]["original_source"] = core_source["artifact_member"]
    staged = StagedExperimentEntry.model_validate(staged_body)

    def pointer(member: str, schema: str, media: str = "application/json") -> dict[str, str]:
        return {
            "artifact_id": "artifact_" + "f" * 32,
            "artifact_revision_id": "rev_" + "f" * 32,
            "member_path": member,
            "sha256": sha("f"),
            "schema_ref": "eom://schemas/legacy-assessment/" + schema + "/1.0",
            "media_type": media,
        }

    source = ApprovedPastExamItemKnowledgeSourceV3.model_validate(
        core_source
        | {
            "extraction_acceptance_id": "itemacceptance_" + "f" * 32,
            "extraction_acceptance_sha256": sha("f"),
            "extraction_acceptance_artifact": pointer(
                "acceptance.json", "legacy-item-extraction-acceptance"
            ),
            "extraction_result_id": "itemextractresult_" + "f" * 32,
            "extraction_result_sha256": sha("f"),
            "extraction_result_artifact": pointer("result.json", "legacy-item-extraction-result"),
            "item_proposal_id": "itemproposal_" + "f" * 32,
            "item_number": 1,
            "bundle": {
                "assessment_source_bundle_id": "assessbundle_" + "f" * 32,
                "assessment_source_bundle_revision_id": "assessbundlerev_" + "f" * 32,
                "bundle_manifest_sha256": sha("f"),
            },
            "layout_observation": {
                "assessment_layout_observation_id": "assessmentlayout_" + "f" * 32,
                "artifact": pointer("layout.json", "assessment-layout-observation"),
                "workspace_relative_path": "source/layout-observation.json",
                "observation_sha256": sha("f"),
            },
            "page_inputs": [
                {
                    "page_input_id": "assessmentpage_" + "f" * 32,
                    "source_role": "PROBLEM_DOCUMENT",
                    "physical_page": 1,
                    "source": pointer("sources/problem.pdf", "pdf-source", "application/pdf"),
                    "image": pointer("pages/problem-000001.png", "page-image", "image/png"),
                    "workspace_relative_path": "source/pages/assessmentpage_" + "f" * 32 + ".png",
                    "width_px": 1200,
                    "height_px": 1800,
                }
            ],
            "page_image_count": 1,
        }
    )
    return InferenceTransferSnapshotRecord(
        index_entry=original.index_entry.model_copy(
            update={
                "profile": InferenceTransferProfilePointer.from_profile(staged.profile),
                "source_value_sha256": content_sha256(source.model_dump(mode="json")),
            }
        ),
        source=source,
        staged_entry=staged,
    )


def snapshot_prepare(**values: Any) -> InferenceTransferSnapshotPrepareRequest:
    experiment = experiment_request()
    return hashed(
        InferenceTransferSnapshotPrepareRequest,
        "prepare_sha256",
        **(
            {
                "graph_snapshot": experiment.scope.graph_snapshot,
                "access_policy_revision_id": experiment.scope.policy_revision_id,
                "access_policy_sha256": experiment.scope.policy_sha256,
                "population_scope": "OCCURRENCE_BACKED_PAST_EXAM",
                "source_classes": ("PAST_EXAM",),
                "recipe": experiment.recipe,
                "max_sources": 1024,
                "query_item_revision_ids": ("itemrev_" + "a" * 32,),
                "chunk_budget": InferenceTransferSnapshotChunkBudget(
                    max_entries=64, max_encoded_bytes=3 * 1024**2
                ),
            }
            | values
        ),
    )


def snapshot_header(
    records: tuple[InferenceTransferSnapshotRecord, ...] | None = None,
    *,
    prepare: InferenceTransferSnapshotPrepareRequest | None = None,
    **values: Any,
) -> InferenceTransferSnapshotHeader:
    records = snapshot_records() if records is None else records
    index = tuple(record.index_entry for record in records)
    profiles = tuple(row.profile for row in index if row.profile is not None)
    return hashed(
        InferenceTransferSnapshotHeader,
        "header_sha256",
        **(
            {
                "prepare": prepare or snapshot_prepare(),
                "actor_id": "synthetic-operator",
                "source_count": len(records),
                "profile_count": len(profiles),
                "missing_report_count": len(records) - len(profiles),
                "population_sha256": population_sha256(tuple(record.source for record in records)),
                "eligible_profile_set_sha256": profile_set_sha256(profiles),
                "index_sha256": snapshot_index_sha256(index),
            }
            | values
        ),
    )


def snapshot_prepare_result(
    records: tuple[InferenceTransferSnapshotRecord, ...] | None = None,
    *,
    header: InferenceTransferSnapshotHeader | None = None,
) -> InferenceTransferSnapshotPrepareResult:
    records = snapshot_records() if records is None else records
    return hashed(
        InferenceTransferSnapshotPrepareResult,
        "result_sha256",
        header=header or snapshot_header(records),
        index=tuple(record.index_entry for record in records),
    )


def snapshot_read_request(
    prepared: InferenceTransferSnapshotPrepareResult | None = None,
    **values: Any,
) -> InferenceTransferSnapshotReadRequest:
    prepared = prepared or snapshot_prepare_result()
    return hashed(
        InferenceTransferSnapshotReadRequest,
        "read_sha256",
        **({"header": prepared.header, "selected_index_entries": prepared.index} | values),
    )


def snapshot_read_result(
    records: tuple[InferenceTransferSnapshotRecord, ...] | None = None,
    *,
    request: InferenceTransferSnapshotReadRequest | None = None,
    **values: Any,
) -> InferenceTransferSnapshotReadResult:
    records = snapshot_records() if records is None else records
    request = request or snapshot_read_request(snapshot_prepare_result(records))
    query = records[0].index_entry.profile
    baseline: tuple[SuppliedGraphBaseline, ...] = ()
    if query is not None and request.header.prepare.query_item_revision_ids:
        baseline = (
            hashed(
                SuppliedGraphBaseline,
                "result_sha256",
                query=query,
                command_sha256=content_sha256("synthetic official command"),
                ordered_candidates=tuple(
                    record.index_entry.profile
                    for record in records[1:]
                    if record.index_entry.profile is not None
                ),
            ),
        )
    return hashed(
        InferenceTransferSnapshotReadResult,
        "result_sha256",
        **(
            {
                "header_sha256": request.header.header_sha256,
                "read_sha256": request.read_sha256,
                "records": records,
                "baselines": baseline,
                "limitations": ("Synthetic values are not authorized source data.",),
            }
            | values
        ),
    )
