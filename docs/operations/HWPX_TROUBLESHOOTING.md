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

## Wheel Or Sandbox Failed

Run `scripts/hwpx/deploy_builder.sh --verify`. Both imports must resolve below the eom-hwpx
environment's `site-packages`; `direct_url.json` must not declare editable mode and no editable
finder may exist. Run `eomctl hwpx doctor` to confirm migration `20260815_0003`, the locked user,
reference paths, artifact root, security capabilities, and transient execution. Use the release
record under `/var/lib/eom-hwpx/deployments/` for rollback; do not add a repository `PYTHONPATH`.

## Structural Or Semantic Failure

Structural checks identify a bounded part and evidence hash without returning full XML. Semantic
comparison reports `EXACT_MATCH`, CRLF-only `NORMALIZED_MATCH`, `MISMATCH`, or `NOT_EXTRACTABLE` per
field. Do not trim arbitrary spaces to conceal a mismatch.

## Hancom Repair Dialog

Record the exact Hancom version and sanitized dialog classification, mark manual open failed, and
retain generated and re-saved files as distinct immutable revisions. Compare entry order,
`version.xml`, namespaces, manifest/spine, Preview changes, equation structure, and ZIP metadata.
Do not mark Linux structural success as Hancom compatibility.

## Embedded PNG Present But Invisible — 2026-10-09

The latest investigated build `hwpxbuild_0b76fa3a3bab4faca5cbb24dd92b1ee0` contains the same
PNG bytes as its authenticated Preview image. Its package-internal relationship is correct;
the zero-area `imgClip` rectangle `(0, 0, 0, 0)` is the identified visibility defect. Hancom's
[HWPML 3.0 revision 1.2 specification, table 122](https://cdn.hancom.com/link/docs/%ED%95%9C%EA%B8%80%EB%AC%B8%EC%84%9C%ED%8C%8C%EC%9D%BC%ED%98%95%EC%8B%9D3.0_HWPML_revision1.2.pdf)
defines this as the remaining image rectangle, not four crop margins. Both Builder picture
writers now use the full original shape-coordinate extent, and independent Manager acceptance
rejects zero-area or inconsistent clipping/display geometry. PNG bytes, original dimensions,
display size, scaling, Item content, tables and panel labels are unchanged.

This is a **source candidate, not a verified live deployment**. The repository non-live HWPX gate
passed **217 tests**; **1 privileged ownership test** was skipped because its opt-in was not set.
A local diagnostic re-render of the exact authenticated Item content and PNG, using the reviewed
handoff archive/profile with explicitly synthetic fixture identities, passed Manager acceptance.
It is **not an official build or delivery acceptance**. Source and embedded PNG both retain
SHA-256 `9084dfbe3358b3ad9189aef3be650e7528b840e7785b054bb58f6045aaf45d73`.
`MANUAL_HANCOM_RENDER_REVIEW=NOT_RECORDED`; Linux package checks are not a substitute for opening
the corrected delivery in Hancom.

Do not rewrite an existing accepted file, change its recorded hash/status, regenerate the Item,
or alter image approval to repair delivery geometry. After the compatible Builder/Manager release
is deployed, submit a new supported delivery build for the same immutable Item Revision, with a
new delivery identity. Preserve the previous build and its evidence as historical bytes.
