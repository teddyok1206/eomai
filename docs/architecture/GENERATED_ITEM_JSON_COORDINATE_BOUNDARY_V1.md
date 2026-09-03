# Generated-item JSON and coordinate boundary V1

Status: implemented

## Responsibility and canonical source

The generated-item Content Pack owns authoring-time presentation instructions. Canonical science
values remain in the item stem, table, equation, and solution; `image_brief.x_values/y_values` are
bounded drawing coordinates, not a second copy of the physical data. The role-result JSON Schema
and Pydantic model remain the validation authorities.

## Access pattern and representation

Authoring performs one ordered pass over at most eight graph points. When a physical magnitude is
outside `[-1000, 1000]`, it stores proportionally scaled integer coordinates and carries the exact
multiplier and unit in the axis label. This is O(n) time and O(n) output space with stable order.
JSON text uses the standard escaped representation of literal backslashes so parsing cannot turn
LaTeX commands into control characters.

## Versioning, failure, and replay

`generated-knowledge-item@1.9.0` is an immutable successor to 1.8.0. It changes only the authoring
profile version and prompt instructions; workflow/result protocol versions are unchanged. Existing
workflows stay pinned to their prior release. Invalid coordinates or control characters continue
to fail closed, and failed workflows are never silently replayed.
