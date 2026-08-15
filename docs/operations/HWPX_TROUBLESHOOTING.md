# HWPX Troubleshooting

## Reference Pending

`HWPX_REFERENCE_MISSING` or `REFERENCE_TEMPLATE=PENDING_MANUAL_ACTION` is expected until the fixed
reference inbox contains `eom_hwpx_reference_v1.hwpx`. Generate the kit and follow the creation
guide. Do not search other NAS folders or substitute an arbitrary document.

## Reference Rejected

Run `eom-hwpx inspect-package` into a local bounded report. Resolve unsafe ZIP names, active
content, encryption, external links, missing or duplicate markers, ambiguous image/equation
objects, and broken manifest/spine references in the Windows source document. Never weaken a
security limit merely to accept a reference; record evidence and change limits through review.

## Rendering Failed

Inspect the machine error code in `result.json`. The builder never treats stdout as its result.
Recreate a fresh workspace; do not reuse extracted content. Confirm the template and binding hashes
match, output PNG is exact RGB/RGBA 800-by-500 and matches its declared hash, and equation source is
inside the POC grammar.

## Structural Or Semantic Failure

Structural checks identify a bounded part and evidence hash without returning full XML. Semantic
comparison reports `EXACT_MATCH`, CRLF-only `NORMALIZED_MATCH`, `MISMATCH`, or `NOT_EXTRACTABLE` per
field. Do not trim arbitrary spaces to conceal a mismatch.

## Hancom Repair Dialog

Record the exact Hancom version and sanitized dialog classification, mark manual open failed, and
retain generated and re-saved files as distinct immutable revisions. Compare entry order,
`version.xml`, namespaces, manifest/spine, Preview changes, equation structure, and ZIP metadata.
Do not mark Linux structural success as Hancom compatibility.
