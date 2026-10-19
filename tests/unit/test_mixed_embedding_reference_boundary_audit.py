"""Synthetic copied-value regression at the new mixed reference boundary."""

from __future__ import annotations

import pytest
from eom_catalog_contracts.mixed_embedding_index import validate_mixed_embedding_index_references

from tests.unit.mixed_embedding_fixtures import mixed_embedding_case


@pytest.mark.parametrize("target", ("pointer", "shard", "shard_space", "shard_row"))
def test_mixed_reference_validation_rejects_copied_undeclared_member_fields(target):
    _entry, _binding, shard, pointer, index = mixed_embedding_case()
    if target == "pointer":
        pointer = pointer.model_copy(update={"undeclared": "not-wire-data"})
    elif target == "shard":
        shard = shard.model_copy(update={"undeclared": "not-wire-data"})
    elif target == "shard_space":
        shard = shard.model_copy(
            update={"space": shard.space.model_copy(update={"undeclared": "not-wire-data"})}
        )
    else:
        shard = shard.model_copy(
            update={
                "rows": (
                    shard.rows[0].model_copy(update={"undeclared": "not-wire-data"}),
                    *shard.rows[1:],
                )
            }
        )
    with pytest.raises(ValueError):
        validate_mixed_embedding_index_references(index, ((pointer, shard),))
