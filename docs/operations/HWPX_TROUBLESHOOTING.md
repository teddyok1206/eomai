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

The initial verification below was **source-only, before the live release**. The repository non-live HWPX gate
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

### Live Release And Fresh Delivery — 2026-10-09 18:12 UTC

The compatible Builder/Contracts and platform-owned Manager/Contracts release is installed from
`fe54e5aa1c0cc9f3a473c1f9cd91d50139728231`. The release used a clean, pinned worktree;
no unrelated model-selection source, API code, Pack activation or migration was deployed. API build
identity remains `2bf5dd75b1356384f5748d4c396c0af4926816ee`, with migration `20261008_0049`.
Component provenance is recorded separately under
`/var/lib/eom-hwpx/deployments/fe54e5aa1c0cc9f3a473c1f9cd91d50139728231.component-set.json`.
Installed wheel RECORD/source verification passed, the eight prior runtime consumers restarted
successfully, and HWPX capability is `READY`. The final focused source gate passed **252 tests**;
**1 privileged ownership test** remained explicitly opt-in and skipped.

A normal authenticated application command created
`hwpxbuild_253ff021c7fa4e9f8cb67b0a4021b4ae` for the unchanged
`itemrev_08794726c0bf4c62b1226e4c96b8be84`. Build and independent Manager validation passed.
Its committed output is `artifact_134f6a70a2aa40e58eee20a47d522148` /
`rev_642837bb1b9048169bfb5ad182c4e66f`, with SHA-256
`99b1e27c5eb745251d6b2ce3385cde7273c7661a36df8852a8c445d814fea2c8`.
The API latest-build resolver and the actual HTTPS Studio BFF both return this new build;
authenticated downloads match the committed SHA. The package contains the original PNG, an
internal embedded image relationship, full clipping rectangle `(0, 0, 22400, 14000)`, unchanged
display size `12600 × 7875`, and 12 native equations. No external image filesystem path is used.

The Item, source Artifact Revision/hash, PNG, pending human approval and historical build are
unchanged. This delivery neither regenerates nor approves the Item. No model/GPU generation ran.
`MANUAL_HANCOM_RENDER_REVIEW=NOT_RECORDED` remains: download the new build and open it in Hancom
for the visual check; the previous downloaded file is intentionally not rewritten.

### User-Confirmed Visibility Failure And Repair Goal — 2026-10-09 18:29 UTC

The user reported that the fresh delivery above still has no visible image. The HWPX uploaded to
the repository's ignored `staging/` has the same SHA-256 as that committed/downloaded output;
the result is not a stale download. The six-hour repair target ends **2026-10-10 00:29:44 UTC**.
The previous structural PASS remains historical evidence, not proof of Hancom rendering.

The remaining compatibility defect is the single-item image manifest's spelling:
`../BinData/content-team-visual-0.png`, while the actual ZIP member is
`BinData/content-team-visual-0.png`. EOM's import resolver accepts both root-qualified and
OPF-relative references. However, the official Hancom model's
[GetZipImageFilePath](https://github.com/hancom-io/hwpx-owpml-model/blob/main/OWPML/Document.cpp)
returns the manifest href, and its [ZIP lookup](https://github.com/hancom-io/hwpx-owpml-model/blob/main/OWPML/Zip/SDZip.cpp)
compares that string with member names without applying the OPF-relative correction. The existing
whole-exam emitter and Kordoc image emitter already use literal package-root member names.

Bounded plan and ownership:

1. Reproduce the exact downloaded file in the installed independent Office renderer and compare
   a diagnostic variant changing only that relationship. Keep these local files as diagnostics,
   not official output or altered accepted history.
2. Make the single-item Builder emit its existing image member name verbatim. Independent Manager
   acceptance must reject renderer-owned binary relationships that need path normalization or
   omit the embedded flag. Preserve historical/import-reader compatibility; do not globally
   remove support for OPF-relative input packages.
3. Add positive and negative regressions for single, paired, mixed and whole-exam images, retaining
   the PNG SHA, source pins, ordinal/labels, equations and table semantics. Check additional layout
   findings independently; do not change content/geometry based only on a hypothesis.
4. Install a reviewed HWPX-only compatible release from a clean pinned worktree, with quiescence
   checks and the exact prior component wheels retained for rollback. No API logic, migration,
   worker prompt, model selection or image generation changes are in this repair.
5. Submit one new supported build for the same Item Revision, verify committed/API/HTTPS download
   hashes and latest-build identity, independently render the actual new downloaded bytes, and
   request the user's Hancom visual confirmation before claiming complete visibility.

The operation is an indexed build lookup plus ordered bounded ZIP-member traversal, O(n) in
package size with a manifest map/set for lookup. No persistent schema, queue, revision or wire
contract is added. Builder owns emission, Manager owns new-output acceptance, and the existing
application/Orchestrator owns registration and immutable commit. Retry uses the same submitted
idempotency key; a new render has a new build identity. Old Item/PNG/approval/build evidence is
preserved. The simpler ZIP-membership-only check was insufficient because it normalized a
relationship the target Hancom reader uses literally.

Pre-release evidence: the original uploaded HWPX reproduced an image-lookup failure in the
installed H2Orestart/LibreOffice toolchain (its binary lookup received no ZIP entry). A local
diagnostic changing **only** the image manifest href produced a one-page PDF with a visibly
rendered picture. The conversion reused the existing bounded converter inside a rootless,
network-disabled filesystem namespace; no source upload, DB mutation or NAS registration occurred.
The full focused HWPX suite passed **268 tests**, with **1 privileged opt-in skip**. Twelve malformed
generated-image relationships that previously passed are now rejected. Separate mixed-cell sizing
findings were recorded as layout risk, not silently included in this missing-image repair; the
href-only diagnostic displays the picture without altering its shape or container geometry.

The final pre-release gate passed **286 HWPX tests**, with **1 privileged opt-in skip**; focused
acceptance passed 68 tests. The 34 new acceptance cases also cover generated picture references
whose namespace or field spelling only appears correct after local-name/case normalization.
New-output acceptance requires exact native `hc:img` / `binaryItemIDRef` and `opf:item` /
`id`, `href`, `media-type`, `isEmbeded` names. Independent review verified these guards without
changing the generic import resolver or the registered historical-download read path. Formatter,
linter and the changed production/new-test type-check gates passed.
