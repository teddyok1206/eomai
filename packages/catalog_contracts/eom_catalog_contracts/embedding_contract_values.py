"""Raw embedding value validation below index and QUERY contracts; no IO or authority."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


def raw_similarity_contract_value(value: object) -> Any:
    """Preserve raw nested scalars/extras before schema validation or Pydantic coercion."""
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
            if len(item) > 1024:
                raise ValueError("similarity contract array bound exceeded")
            return [read(child, depth + 1) for child in item]
        if isinstance(item, datetime):
            return item.isoformat().replace("+00:00", "Z")
        return item

    return read(value, 0)
