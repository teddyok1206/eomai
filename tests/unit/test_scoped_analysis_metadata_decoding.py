"""Current synthetic DB values plus root-scoped decoding; no database/auth/NAS."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service import pinned_artifact_resolution as pinned
from eom_catalog_service import solution_evidence_resolution as solution
from eom_catalog_service.artifacts import CatalogModelValueDecoder
from eom_identifiers import content_sha256
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, ConfigDict

from tests.unit.test_past_exam_solution_analysis_contracts import NOW, _solution_resolution_records
from tests.unit.test_scoped_artifact_model_decoding import context_case


class FrozenValue(BaseModel):
    model_config = ConfigDict(frozen=True)
    value: int


def decode_value(_schema: str, raw: bytes) -> FrozenValue:
    return FrozenValue.model_validate_json(raw)


def test_complete_current_value_schema_and_decoder_define_interpretation(tmp_path):
    reader, _, _ = context_case(tmp_path)
    assert isinstance(reader, CatalogModelValueDecoder)
    decoder = Mock(side_effect=decode_value)
    first = reader.decode_model_value("value/1", {"value": 1}, decoder=decoder)
    assert reader.decode_model_value("value/1", {"value": 1}, decoder=decoder) is first
    assert decoder.call_count == 1
    assert reader.decode_model_value("value/1", {"value": 2}, decoder=decoder).value == 2
    assert reader.decode_model_value("value/2", {"value": 1}, decoder=decoder) is not first
    other = Mock(side_effect=decode_value)
    assert reader.decode_model_value("value/1", {"value": 1}, decoder=other) is not first
    assert (decoder.call_count, other.call_count) == (3, 1)


@pytest.mark.parametrize("fault", ["root", "thread"])
def test_value_hit_requires_original_live_root_and_thread(tmp_path, monkeypatch, fault):
    reader, _, session = context_case(tmp_path)
    reader.decode_model_value("value/1", {"value": 1}, decoder=decode_value)
    if fault == "root":
        session.root.is_active = False
    else:
        monkeypatch.setattr(pinned, "get_ident", lambda: -1)
    with pytest.raises(pinned.PinnedArtifactResolutionError, match="transaction"):
        reader.decode_model_value("value/1", {"value": 1}, decoder=decode_value)


@pytest.mark.parametrize("limit", ["bytes", "entries"])
def test_values_and_artifact_models_share_existing_retention_bounds(tmp_path, limit):
    reader, pointer, _ = context_case(tmp_path)
    if limit == "entries":
        reader.MAX_DECODED_MEMBERS = 1
    else:
        reader.MAX_DECODED_BYTES = 11
    member_decoder = Mock(side_effect=decode_value)
    value_decoder = Mock(side_effect=decode_value)
    reader.read_model_member(pointer, expected_bytes=11, decoder=member_decoder)
    reader.decode_model_value("value/1", {"value": 2}, decoder=value_decoder)
    assert len(reader._decoded) == 1 and reader._decoded_bytes == 11
    reader.read_model_member(pointer, expected_bytes=11, decoder=member_decoder)
    assert member_decoder.call_count == 2
    assert len(reader._decoded) == 1 and reader._decoded_bytes == 11


def solution_case(tmp_path):
    reader, _, _ = context_case(tmp_path)
    *row, report = _solution_resolution_records()
    artifacts = SimpleNamespace(
        decode_model_value=reader.decode_model_value,
        read_member=lambda **_: report,
    )
    return reader, artifacts, row


def test_one_solution_envelope_reuses_three_models_and_both_historical_hashes(
    tmp_path, monkeypatch
):
    reader, artifacts, row = solution_case(tmp_path)
    decode = Mock(wraps=solution._decode_solution_metadata)
    monkeypatch.setattr(solution, "_decode_solution_metadata", decode)
    first = solution._resolve_row(artifacts, tuple(row))
    for _phase in range(3):
        assert solution._resolve_row(artifacts, tuple(row)) == first
    assert decode.call_count == 1 and len(reader._decoded) == 1
    entry = next(iter(reader._decoded.values()))
    assert pinned._deeply_immutable(entry.value)
    assert entry.value.accepted_artifact_sha256 == row[1].content_hash
    assert entry.value.receipt_artifact_sha256 == row[3].content_hash


@pytest.mark.parametrize("field", ["request", "accepted", "receipt"])
def test_changed_current_json_cannot_inherit_an_earlier_valid_interpretation(tmp_path, field):
    reader, artifacts, row = solution_case(tmp_path)
    solution._resolve_row(artifacts, tuple(row))
    if field == "request":
        row[0].canonical_request = deepcopy(row[0].canonical_request)
        row[0].canonical_request["request_sha256"] = "sha256:" + "0" * 64
    else:
        record = row[1 if field == "accepted" else 3]
        record.result = deepcopy(record.result)
        record.result["schema_version"] = "foreign/1.0"
    with pytest.raises((solution.SolutionEvidenceResolutionError, JsonSchemaValidationError)):
        solution._resolve_row(artifacts, tuple(row))
    assert len(reader._decoded) == 1


@pytest.mark.parametrize("fault", ["run_state", "accepted_approval", "proposal_approval", "hash"])
def test_cached_metadata_never_caches_current_lifecycle_or_descriptor(tmp_path, fault):
    _reader, artifacts, row = solution_case(tmp_path)
    solution._resolve_row(artifacts, tuple(row))
    if fault == "run_state":
        row[0].state = "REJECTED"
    elif fault == "accepted_approval":
        row[2].approved = False
    elif fault == "proposal_approval":
        row[3].approved = False
    else:
        row[1].content_hash = "sha256:" + "0" * 64
    with pytest.raises(solution.SolutionEvidenceResolutionError, match="chain differs"):
        solution._resolve_row(artifacts, tuple(row))


def test_545_distinct_solution_envelopes_fit_with_1090_other_entries_and_decode_once(tmp_path):
    """Occupancy/count evidence, not actual Item/report memory or live latency."""
    reader, _, _ = context_case(tmp_path)
    for index in range(1090):
        reader.decode_model_value(
            "synthetic-item-report-occupancy/1", {"value": index}, decoder=decode_value
        )
    *row, _ = _solution_resolution_records()
    values = []
    for index in range(545):
        accepted = deepcopy(row[1].result)
        accepted["accepted_at"] = (
            (NOW + timedelta(seconds=index)).isoformat().replace("+00:00", "Z")
        )
        accepted["result_sha256"] = content_sha256(
            {key: value for key, value in accepted.items() if key != "result_sha256"}
        )
        values.append(
            {"request": row[0].canonical_request, "accepted": accepted, "receipt": row[3].result}
        )
    calls = 0

    def decoder(schema, raw):
        nonlocal calls
        calls += 1
        return solution._decode_solution_metadata(schema, raw)

    signatures = []
    for _phase in range(4):
        signatures.append(
            tuple(
                reader.decode_model_value(
                    solution._SOLUTION_METADATA_SCHEMA, value, decoder=decoder
                ).accepted_artifact_sha256
                for value in values
            )
        )
    assert calls == 545 and signatures.count(signatures[0]) == 4
    assert len(reader._decoded) == 1635 <= reader.MAX_DECODED_MEMBERS
    assert reader._decoded_bytes < reader.MAX_DECODED_BYTES
