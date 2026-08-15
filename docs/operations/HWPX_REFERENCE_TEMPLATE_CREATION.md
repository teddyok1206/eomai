# HWPX Reference Template Creation

The reference must be created on the laboratory Windows PC with the actual Hancom Office Hangul
application. Record the exact Windows and Hancom versions; do not write a guessed version.

## Prepare The Kit

Run `eomctl hwpx reference-kit create` or, before eomctl integration, run the isolated kit script.
The kit is written only to `/mnt/nas/eom/hwpx/poc-v0/reference-kit/v1/`. Both PNG files are
deterministic RGB 800x500 images with different SHA-256 values and no scientific meaning.

## Create The Document

1. Start a new one-section document and record the exact Hancom version.
2. Build one combined placeholder item and solution with the marker list from
   `reference-markers.txt`. Do not split a marker with formatting or a line break, attach other text,
   or use any marker twice.
3. Create a real 2x3 table and put the six table markers in their respective cells. Do not nest a
   table.
4. Insert `eom-placeholder-image-reference.png` as an embedded image, not a link. Do not resize or
   crop it after insertion.
5. Insert one equation with the Hangul equation editor. Prefer a stored source containing
   `EOM_EQ_PLACEHOLDER` with visual meaning `x+y=z`. If that string is not preserved by the installed
   version, place `{{EOM_EQUATION_ANCHOR}}` immediately adjacent to the only equation.
6. Do not add scripts, macros, OLE, external links, encryption, signatures, charts, tracked changes,
   document history, or additional sections.
7. Save as `eom_hwpx_reference_v1.hwpx` into
   `/mnt/nas/eom/hwpx/poc-v0/reference/inbox/`. Do not rename another format to `.hwpx`.
8. Record the Windows version, Hancom version, font warnings, and whether the equation marker or
   anchor was used in a separate sanitized operator note.

The importer treats this file as untrusted and read-only. It will reject unsafe package entries,
active content, missing or duplicate markers, ambiguous equation/image bindings, and unsupported
package structure. The original is never edited.

This tooling was developed by referring to Hancom's public HWP/OWPML format material; see
`docs/references/HWPX_FORMAT_REFERENCES.md`.
