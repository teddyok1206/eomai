"""Raw embedding value validation below index and QUERY contracts; no IO or authority."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


def raw_similarity_contract_value(value: object) -> Any:
    """Preserve raw nested scalars/extras before schema validation or Pydantic coercion."""
    return _raw_embedding_contract_value(value, maximum_array_length=1024, scalar_policy="PRESERVE")


def raw_public_solution_contract_value(value: object) -> Any:
    """Successor public metadata may contain16,384 sources, never unbounded arrays.

    This is not runtime admission. Closed root schemas retain their independent
    limits/byte budgets, and the historical raw parser stays at1,024 exactly.
    """
    return _raw_embedding_contract_value(
        value, maximum_array_length=16384, scalar_policy="INTEGER_METADATA"
    )


def _raw_embedding_contract_value(
    value: object,
    *,
    maximum_array_length: int,
    scalar_policy: Literal["PRESERVE", "INTEGER_METADATA"],
) -> Any:
    nodes = 0

    def read(item: object, depth: int) -> Any:
        nonlocal nodes
        nodes += 1
        # The existing bounded 1,024-binding index can exceed the much smaller context shape.
        # Each root contract still enforces its own canonical byte budget after raw revalidation.
        if depth > 32 or nodes > 8 * 1024 * 1024:
            raise ValueError("similarity contract nesting/node bound exceeded")
        if isinstance(item, BaseModel):
            fields = type(item).model_fields
            if item.__pydantic_extra__ or set(item.__dict__) - set(fields):
                raise ValueError("copied/constructed contract contains undeclared fields")
            if not set(fields).issubset(item.__dict__):
                raise ValueError("constructed contract lacks a declared field")
            return {name: read(item.__dict__[name], depth + 1) for name in fields}
        if isinstance(item, dict):
            if len(item) > 1024 or any(not isinstance(name, str) for name in item):
                raise ValueError("similarity contract object keys/size are invalid")
            return {name: read(child, depth + 1) for name, child in item.items()}
        if isinstance(item, tuple | list):
            if len(item) > maximum_array_length:
                raise ValueError("similarity contract array bound exceeded")
            return [read(child, depth + 1) for child in item]
        if isinstance(item, datetime):
            return item.isoformat().replace("+00:00", "Z")
        if (
            scalar_policy == "INTEGER_METADATA"
            and item is not None
            and not isinstance(item, str | int | bool)
        ):
            raise ValueError("public solution metadata must preserve integer-only raw scalars")
        return item

    return read(value, 0)
