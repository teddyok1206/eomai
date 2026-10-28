"""Cohort identity is immutable; a cursor cannot authorize or complete work."""

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts.creative_learning_cohort import CreativeLearningCohort
from eom_identifiers import content_sha256
from jsonschema import ValidationError as SchemaError

from tests.unit.test_creative_registered_report import proposal


def cohort_value():
    resolved, lineage = proposal()
    target = {
        "source_id": lineage.source_id,
        "source_revision_id": lineage.source_revision_id,
        "external_number": lineage.external_number,
        "observation_sha256": lineage.observation_sha256,
        "selected_edition": resolved.work.source.selected_edition,
    }
    targets = [
        target,
        *[
            {
                **target,
                "source_id": "extitem_" + f"{index + 10:032x}",
                "source_revision_id": "extitemrev_" + f"{index + 20:032x}",
                "external_number": str(int(lineage.external_number) + index),
            }
            for index in (1, 2)
        ],
    ]
    targets.sort(key=lambda value: value["external_number"])
    pin = {
        "preset_id": "execpreset_" + "b" * 32,
        "preset_revision_id": "execpresetrev_" + "c" * 32,
        "sha256": "sha256:" + "d" * 64,
    }
    value = {
        "schema_version": "creative-learning-cohort/1.0",
        "cohort_id": "creativecohort_" + "e" * 32,
        "import_id": lineage.import_id,
        "requested_by_operator_id": lineage.requested_by_operator_id,
        "source_commit": "f" * 40,
        "created_at": "2026-10-28T00:00:00Z",
        "targets": targets,
        "target_set_sha256": content_sha256(targets),
        "seed_external_number": lineage.external_number,
        "seed_selection": resolved.selection.model_dump(mode="json"),
        "extraction_preset": pin,
        "analysis_preset": pin,
        "capacity_policy_revision_id": "capacityrev_" + "a" * 32,
        "workflow_definition_sha256": "sha256:" + "b" * 64,
        "content_pack_release_id": "packrel_" + "c" * 32,
        "risk_policy_revision_id": "analysisriskrev_" + "d" * 32,
        "risk_policy_sha256": "sha256:" + "e" * 64,
        "access_policy_revision_id": "accessrev_" + "f" * 32,
        "access_policy_sha256": "sha256:" + "a" * 64,
        "registration_policy": "PRESERVE_SOURCE_WITH_REVIEW_WARNINGS_V1",
    }
    return {**value, "cohort_sha256": content_sha256(value)}


def rehash(value):
    value["target_set_sha256"] = content_sha256(value["targets"])
    value["cohort_sha256"] = content_sha256(
        {key: entry for key, entry in value.items() if key != "cohort_sha256"}
    )


def test_cohort_contract_mirror_and_stable_immutable_roundtrip():
    parsed = CreativeLearningCohort.model_validate(cohort_value())
    assert CreativeLearningCohort.model_validate_json(parsed.model_dump_json()) == parsed
    root = Path(__file__).resolve().parents[2]
    name = "external-item/creative-learning-cohort-v1.schema.json"
    assert (root / "schemas" / name).read_bytes() == (
        root / "packages/catalog_contracts/eom_catalog_contracts/resources" / name
    ).read_bytes()
    with pytest.raises(ValueError):
        parsed.requested_by_operator_id = "operator_" + "0" * 32


@pytest.mark.parametrize(
    "mutation", ["owner", "target", "policy", "seed", "duplicate", "reordered"]
)
def test_cohort_rejects_changed_pins_or_ambiguous_target_set(mutation):
    value = deepcopy(cohort_value())
    if mutation == "owner":
        value["requested_by_operator_id"] = "operator_" + "0" * 32
    elif mutation == "target":
        value["targets"][0]["source_revision_id"] = "extitemrev_" + "0" * 32
    elif mutation == "policy":
        value["risk_policy_sha256"] = "sha256:" + "0" * 64
    elif mutation == "seed":
        value["seed_external_number"] = "00000"
        rehash(value)
    elif mutation == "duplicate":
        value["targets"][1] = value["targets"][0]
        rehash(value)
    else:
        value["targets"].reverse()
        rehash(value)
    with pytest.raises((ValueError, SchemaError)):
        CreativeLearningCohort.model_validate(value)
