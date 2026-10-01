from __future__ import annotations

from scripts.contracts.audit_wire_contracts import audit


def test_wire_contract_identity_reference_and_mirror_audit() -> None:
    result = audit()

    assert result["canonical_schema_count"] >= 680
    assert result["reference_count"] >= 4600
    assert result["mirror_count"] >= 60
