"""A distinct material purpose shares, rather than adds to, the four-process host."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from eom_identifiers import content_sha256
from eom_workflow.control_plane import WorkerCapacityPolicyV6, WorkerCapacityPolicyV7
from eom_workflow.control_schemas import validate_control_contract
from jsonschema.exceptions import ValidationError as SchemaValidationError

from tests.unit.test_creative_report_capacity import eligible
from tests.unit.test_creative_report_capacity import slots as slots
from tests.unit.test_office_report_capacity import capacity_value as office_capacity


def capacity_value():
    value = office_capacity()
    value.update(schema_version="worker-capacity-policy/1.6", purpose="UPLOADED_MATERIAL_LEARNING")
    value["content_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "content_sha256"}
    )
    return value


def test_uploaded_purpose_keeps_host_ceiling_and_does_not_relax_old_office_policy(slots):
    value = capacity_value()
    validate_control_contract("worker-capacity-policy-v7", value)
    parsed = WorkerCapacityPolicyV7.model_validate(value)
    assert parsed.max_active_codex == parsed.max_active_knowledge_analysis == 4
    row = SimpleNamespace(**value, canonical_document=value)
    assert eligible(slots, row) == ("04", "05", "06")
    assert eligible(slots, row, pool="other") == ("05", "06")
    with pytest.raises(ValueError):
        WorkerCapacityPolicyV6.model_validate(value)
    assert (
        WorkerCapacityPolicyV6.model_validate(office_capacity()).purpose
        == "OFFICE_CREATIVE_REPORT_BACKFILL"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_active_codex", 5),
        ("max_active_knowledge_analysis", 1),
        ("max_active_gpu", 2),
        ("purpose", "OFFICE_CREATIVE_REPORT_BACKFILL"),
    ],
)
def test_material_capacity_cannot_broaden_host_or_starve_shared_knowledge(field, value):
    document = deepcopy(capacity_value())
    document[field] = value
    document["content_sha256"] = content_sha256(
        {key: item for key, item in document.items() if key != "content_sha256"}
    )
    with pytest.raises(SchemaValidationError):
        validate_control_contract("worker-capacity-policy-v7", document)
