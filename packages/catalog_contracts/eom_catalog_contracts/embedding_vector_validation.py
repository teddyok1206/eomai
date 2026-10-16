"""Read-only row validation without changing the frozen native codec implementation."""

from __future__ import annotations

from eom_catalog_contracts.embedding_vector_binary import _require_shape, _require_unit_vector


def validate_unit_vector(vector: tuple[float, ...], dimension: int) -> None:
    """Delegate inside this package; never normalize or allocate serialized vector bytes."""
    _require_shape(dimension, 1)
    _require_unit_vector(vector, dimension)
