# Offline Kakao question PDF worker

This package owns only deterministic local PDF rendering. The Catalog application owns
authorization, student/source mapping, accepted question revisions, packet selection and
idempotency. The Orchestrator stages validated local inputs; accepted publication uses the
existing Catalog Artifact owner and Orchestrator commit boundary.
The worker imports neither Catalog, PostgreSQL, NAS, browser profiles nor network clients.

## Handoff and ownership

`eom-kakao-archive-contracts` owns JSON Schema 2020-12 and frozen Pydantic models. Its wheel
contains and verifies the schema bytes; no runtime source checkout is required. A command
pins the binding, packet revision, student, ordered question-subset hash, DRAFT/FINAL mode,
renderer release, layout policy, manifest member and font member. The exact command/task/attempt,
attempt number and monotonically increasing fence are echoed in the result. A member is a relative
local path plus SHA-256, size and MIME, not canonical identity.

The input manifest contains only selected questions and typed attachment occurrences. The
Orchestrator must first resolve canonical revisions, reauthorize source access and stage the
immutable manifest, original photos and approved font. Repeated photo occurrences may reuse
one member; different occurrences retain their order and independent identity.
`ordered_blocks` references the text/image payloads exactly once without copying their bytes;
text → image → text stays interleaved both visually and in the PDF content stream.

## Algorithm and bounded work

Ordered question traversal is linear. Member/decoded-image lookup uses a hash map. There are
four fixed layout candidates (11/10 pt, one/two columns within consecutive image runs), so measurement is bounded by
text and image size, not a search across arbitrary CSS. A4 portrait, 12 mm horizontal margins,
minimum 10 pt text and a 45 mm minimum photo short side are fixed by the layout-policy revision.
The latter is a geometry check, **not** proof that text inside a photo is readable.

Inputs are bounded to 200 questions, 20,000 codepoints/question, 30 photos/question, 64 MiB/member
and 256 MiB total staged members. Images are restricted to single-frame PNG/JPEG/WebP, at most
40 million pixels each and 64 million total distinct materialized pixels. Display derivatives
are bounded to 256 MiB. A local EXIF-oriented PNG derivative preserves the original source
bytes/hash; it is never a replacement source. Process memory/time/network/filesystem isolation
must additionally be imposed by the installed worker launcher.

Text is measured with the supplied embedded font, with codepoint ranges retained. Glyphs
without support are rejected; there is no silent fallback, OCR or text summarization. Photos
preserve occurrence order and aspect ratio without automatic cropping. An explicitly pinned
manual transform applies EXIF orientation, clockwise quarter-turn rotation, then a normalized
millionths crop. Floor/ceil pixel rounding, original hash, transform revision and derived display
PNG hash/size/dimensions are recorded; original bytes are never rewritten. Impossible one-page layouts,
missing FINAL photos and unaccepted FINAL photo quality yield `NEEDS_LAYOUT_REVIEW`, not a
clipped success. DRAFT can show an explicit missing-photo placeholder.

## Failure, persistence and execution boundary

There is no DB transaction or shared queue inside the renderer. Run one isolated process per
command with an owner-created empty output directory. Inputs are opened descriptor-relative,
without symlinks or hardlinks, and checked for size/hash/file identity. Outputs are exclusive
creates, never overwrites. Input/output directory trees must not overlap.

All layouts are checked before output writes. The actual PDF is reopened, embedded fonts and
page count checked, and page PNGs rasterized. Success returns only unique PDF/layout/PNG member
pointers. A partial write failure returns no publishable outputs; existing local files remain
for owner-controlled inspection/cleanup. Do not retry into that same nonempty directory.
Idempotent reuse, retry identity and final lifecycle/hash verification belong to the calling
application and Orchestrator, not this worker.

`KakaoPdfExecutor` stages and validates local results without importing this worker. Its explicit
`recover_finished` path requires current authorization/fence and owner proof the original process
is stopped; it never renders again or overwrites a previously copied file. The fixed systemd
template runs a private renderer UID with network disabled, read-only input, bounded resources
and sibling-attempt isolation. Unit setup/privileged tests are separate from local subprocess
tests. See `docs/architecture/KAKAO_PDF_EXECUTION_BOUNDARY.md`.

With the same command, staged font, engine and dependencies, fixtures assert identical PDF,
receipt and preview hashes. Random PDF document IDs are disabled. This is not a promise across
different renderer releases. Final human preview review and live source collection are separate
acceptance gates and are not claimed by synthetic renderer tests.

## Dependencies and verification

- PyMuPDF `>=1.26.7,<1.27`: existing EOM PDF engine; local behavior verified with `1.26.7`.
- Pillow `11.3.0`: existing image-provider pin, newly installed only for this worker, to validate
  image format/dimensions and apply EXIF orientation. The installed PyMuPDF `image_profile`
  adapter could not accept Python byte buffers, so it is not used for source validation.
- Pure contracts reuse the repository's Pydantic and JSON Schema pins.

Focused tests: `test_kakao_question_render.py`, `test_kakao_render_transforms.py`,
`test_kakao_pdf_execution.py`, `test_kakao_pdf_runtime.py` under `tests/unit`. They use anonymous generated images
and PyMuPDF's bundled Korean font staged as an explicitly hashed file. No private messages,
credentials, student photos, live accounts or model calls are required.

The simpler option—PDF generation directly in the API—was rejected because untrusted image
decode and long rendering must not share API process lifetime or authority. This is a small
adapter boundary, not a new worker framework.
