from __future__ import annotations

from pathlib import Path

import pytest

from scripts.contracts.audit_wire_contracts import SchemaDocument, audit, audit_references


def test_wire_contract_identity_reference_and_mirror_audit() -> None:
    result = audit()

    assert result["canonical_schema_count"] >= 680
    assert result["reference_count"] >= 4600
    assert result["mirror_count"] >= 900


def test_embedded_schema_ids_have_independent_fragment_scope() -> None:
    bundle = SchemaDocument(
        path=Path(__file__),
        value={
            "$id": "eom://test/bundle",
            "$defs": {
                "runtime": {
                    "$id": "eom://test/runtime",
                    "$defs": {"version": {"type": "string"}},
                    "properties": {"version": {"$ref": "#/$defs/version"}},
                }
            },
        },
    )
    consumer = SchemaDocument(
        path=Path(__file__),
        value={"$id": "eom://test/consumer", "$ref": "eom://test/runtime#/$defs/version"},
    )
    assert audit_references((bundle, consumer)) == 2


def test_embedded_duplicate_ids_are_rejected() -> None:
    document = SchemaDocument(
        path=Path(__file__),
        value={"$id": "eom://test/duplicate", "$defs": {"nested": {"$id": "eom://test/duplicate"}}},
    )
    with pytest.raises(ValueError, match="duplicate canonical"):
        audit_references((document,))
