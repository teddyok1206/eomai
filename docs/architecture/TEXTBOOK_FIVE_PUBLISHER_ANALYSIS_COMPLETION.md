# Five-publisher textbook analysis completion record

Status: `PRE_CANONICAL_REVIEW_ONLY`

Date: 2026-08-25 UTC

## 1. Scope and meaning of completion

This record closes the local, pre-canonical page analysis pass for Integrated Science volumes I and
II from MiraeN, Dong-A, Visang, Jihaksa, and Chunjae. Science Inquiry Experiment is intentionally
excluded.

Completion at this boundary means that every physical PDF page has a pinned Markdown evidence
member, every applicable EOM middle-unit key has a proposed page range, the bundle manifests and
all member hashes validate, and every low-text exception has been reviewed. It does **not** mean
that the proposed mappings have been accepted into the Education Graph, that copyright and usage
rights have been approved, or that fine-grained claims, figures, tables, equations, and
cross-publisher equivalence have been extracted. Those are later Knowledge Analysis and canonical
registration boundaries.

## 2. Canonical-source boundary

The ten PDFs remain protected local intake sources. Their source manifest is unchanged at:

`sha256:f2ce238925f43cb96ac8faeda59ad4ebd180d0f439b860734fdc77d0736f6853`

The intake directory remains mode `0700`; each source PDF remains a regular, non-symlink file at
mode `0400`. This pass did not move, rename, modify, or register those files. The review bundles do
not contain PDF or raster copies. A Markdown page member is temporary materialization tied to the
source SHA, physical page number, extractor provenance, and its own content hash.

| Publisher | Volume | Pages | Source SHA-256 |
| --- | --- | ---: | --- |
| MiraeN | I | 184 | `5ce1f1f1cc94030e9236cb3c15bb85ffc29c16c7b938811e4c1cb71e2ee3b866` |
| MiraeN | II | 182 | `bfbf8000702441bc7763acd1d026d597e02c848f04722304450f8f3e7d9b2197` |
| Dong-A | I | 180 | `f5f3196cd0a3267bc70ae5aa62bc4b19a365cd1cca5a7eb6b355f0132f4a90ca` |
| Dong-A | II | 168 | `22f61335cff2e0161a51056926b2fdf9c9bff50c6d4dc0af0842efa2f6c4fca8` |
| Visang | I | 174 | `e00f67973f5368e6949b5c49dcfd9ceef7198fd343d50899a7267762315dbff0` |
| Visang | II | 164 | `033bcfa21605d85adaeca8631e0c5eacb21368a5ccd8afb978f946e6a0f1e144` |
| Jihaksa | I | 180 | `74b1fb5088e1aa40c339ee76eb35957ee7189acd4bd595c4433cfaae1693d866` |
| Jihaksa | II | 170 | `de4e2d036de08c6421d6b84cd8ee5ce49ac68cc16807779f95075df9f4a4ee9e` |
| Chunjae | I | 152 | `ffa840e8867a2b7cc86bfd8c334d7fbf16a3a3083042783a235a9d9db70d1c30` |
| Chunjae | II | 148 | `e71c9733963c7aa6e1d3b11d44747a004792a6474a8d01eef5b16ce77ac5ab76` |

## 3. Extraction and bundle evidence

MiraeN uses its usable embedded text layer. Dong-A I, Visang, and Jihaksa use page-selective OCR
fallback. Dong-A II and Chunjae use full-page OCR because their PDFs are image-only. OCR uses only
the pinned local Poppler 26.02.0 and Tesseract 5.3.4 resources described in the bundle manifest; no
external model or service was called.

| Publisher | Vol. | Bundle ID | Manifest SHA-256 | Extracted chars | Empty | Warnings | Mappings |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| MiraeN | I | `textbookbundle_f1f457dbed74e2021dc6c40b23f8189c` | `2fa51ad15c20caea918376db88d0079f8e1d95dc8490023486c622faf8fac176` | 659,944 | 0 | 0 | 17 |
| MiraeN | II | `textbookbundle_5b7144eebbca6ee65adbff75cd49ef6c` | `d56c3f7d6e16e866aa869da19e84f1999ebe4b171214f3cd9191c5baf68b702a` | 494,629 | 0 | 1 | 18 |
| Dong-A | I | `textbookbundle_4efd4b970b76cc50895e6553078c0dc4` | `b73b586bd8782197441aa0dfec54b2cf8d5dae3ef68dadfacd5788aa68a23f03` | 220,392 | 1 | 1 | 17 |
| Dong-A | II | `textbookbundle_87722c45eb995c9195cf48158c090928` | `ed507267e28b29c977fb057daf38acfdc2fee55381d5f474d237163d3da31e7f` | 168,543 | 5 | 0 | 18 |
| Visang | I | `textbookbundle_13c3c9c979f9ef64e0b8df5ef2d5db7b` | `cf5820022ed20649522683c630e4d4857a5af6a6eedb1765cbdeed7f5dd75e48` | 172,669 | 6 | 0 | 17 |
| Visang | II | `textbookbundle_28c9a22a65f734cdc7a074eb09dfdf4b` | `0fca3ad02a541170fd1801b28033041bf9d0446c1628345b221f8f577dd5472f` | 153,928 | 4 | 0 | 18 |
| Jihaksa | I | `textbookbundle_9e01a1a4a97e6bb6f534193fd0a93b56` | `5c3458b4c93b560294d7b13075f8552c73918a53e4899ab2cca741d91213f6a1` | 430,895 | 3 | 0 | 17 |
| Jihaksa | II | `textbookbundle_b3d87a39a644a923f2ebc899c8d12042` | `1e631088bdf4a29375a6cfadb4f1b97a8295ba794a68df1c00a39ddced1e7d58` | 442,263 | 0 | 0 | 18 |
| Chunjae | I | `textbookbundle_6a0540731edfa668ef5cd28d42148c02` | `076bacf0e07a6fb365a7e0d4e7e439ecae8f00989aa52d6e409cfff86eb51d3d` | 106,893 | 3 | 0 | 17 |
| Chunjae | II | `textbookbundle_042b7e824acf788d61a179c4f0dcd671` | `ccf2f09bdee7d49de6a74755f7150c9ace5be73967c84c424023822014db8ed8` | 111,870 | 2 | 0 | 18 |

The combined evidence covers 1,702 physical pages, 2,962,026 extracted characters, and 175
publisher-volume-to-EOM-unit mappings. Each publisher covers the exact same 35 EOM middle-unit keys:
17 in volume I and 18 in volume II. All mappings remain `PROPOSED`; overlapping publisher sections
are represented as overlapping ranges rather than forced into invented one-to-one boundaries.

## 4. Reviewed exceptions

The 24 empty extraction members were visually checked. They are covers, illustrated unit-opening
pages, section dividers, photo-only pages, blank worksheets, or truly blank source pages. No page
containing ordinary instructional prose remained unrepresented. The two warning pages were also
reviewed: MiraeN II contains formula-oriented source text and Dong-A I page 154 is a normal
assessment/activity page. Each warning is a single replacement character from the embedded PDF
text layer, not a missing page.

## 5. Validation result

The ten bundles pass:

- JSON Schema 2020-12 and Pydantic manifest validation;
- manifest self-hash and every Markdown/index member hash;
- exact source SHA, byte size, page count, regular-file and non-symlink checks;
- contiguous one-member-per-physical-page coverage;
- evidence-anchor resolution for every proposed curriculum mapping;
- exact five-publisher coverage of the fixed 35-unit EOM outline;
- protected output modes (`0500` directories and `0400` members);
- absence of PDF and raster payloads from both review bundles and Git.

The bundle locations are review evidence in protected temporary storage, not durable identity and
not canonical storage. They must not be used by production retrieval until rights review succeeds
and the orchestrator registers the source and reviewed bundle as immutable Artifact Revisions.

## 6. Next controlled boundary

The next step is not more ad hoc OCR. It is a rights-and-provenance decision followed by canonical
Artifact registration. After registration, Knowledge Analysis may consume pinned page anchors to
produce fine-grained concept, claim, figure, table, equation, curriculum, item, and publisher
relations. Accepted graph snapshots must reference immutable Artifact Revisions and must never use
these temporary filesystem paths as identity.
