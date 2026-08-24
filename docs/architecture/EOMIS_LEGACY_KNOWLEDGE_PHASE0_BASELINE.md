# EOMIS Legacy Knowledge Integration Phase 0 Baseline

Status: accepted read-only baseline for protocol implementation. No legacy source, EOMIS file,
production database row, NAS Artifact, worker job, or runtime service was changed.

Observed: 2026-08-24 UTC

Repository baseline: `508b2042c2bfea0afc07d667d93650f8738da5d7`

Parent plan:
[EOMIS Legacy Knowledge Integration Plan](EOMIS_LEGACY_KNOWLEDGE_INTEGRATION_PLAN.md)

## 1. Source and runtime baseline

| Boundary | Observed value |
| --- | --- |
| EOM repository | independent Git repository; clean at baseline |
| EOMIS repository | independent Git repository; pre-existing operator changes preserved |
| installed Application API source | `8c620003eeda7a1228a032052c0891d11fa8d6bc` |
| installed Application API package | `0.1.0`, built `2026-08-24T15:08:06Z` |
| source migration head | `20260824_0015` |
| Application API | active |
| Catalog application runner | active |
| Scientific Studio | active |

The source migration head is a repository observation, not a claim that a production migration was
executed during this baseline. No database URL or secret configuration was read into this document.

## 2. Safe aggregate inventory

The observed legacy item area contains 1,684 files and about 414 MB: 841 prior normalized JSON
files, 837 HWP files, and two small PDFs. Filename stems suggest 812 possible JSON/HWP relations,
but 29 JSON and 25 HWP files have no same-stem peer. A filename is not accepted as relation proof.

The observed knowledge workspace contains 660 JSON files, three mutable vector-index SQLite files,
and two PDFs. Its curriculum/textbook Markdown, JSON, chunks, concepts, registries, page
observations, page images, SQLite, and vector state are Codex-derived outputs.

The old EOM AI Server bundle contains four original-PDF candidates totaling about 486 MB. Two are
larger than the existing 100 MiB Content Intake member limit. Its `.env`, external-API code,
mutable index, prompts, and runtime caches are excluded and were not read as source data.

The approximately 28.5 GB EOMIS model/checkpoint area is outside the knowledge-ingestion boundary.

## 3. Source-of-truth rule

For textbook and reference-book corpora:

- only an independently verified original PDF may become a canonical source Artifact Revision;
- every adjacent Codex-produced JSON, Markdown, chunk, registry, page observation, page PNG,
  SQLite row, FTS record, vector point, and embedding is derived migration evidence;
- derived evidence may support comparison and evaluation, but cannot independently create a source
  anchor, graph fact, rights decision, or approved Item;
- a generated page image pins the original PDF revision, page, renderer/options, and its own hash;
- physical SQLite/Qdrant/FTS state is a rebuildable cache and is never imported as authority.

Separately inventoried original assessment HWP/HWPX/PDF files remain source candidates only after
provenance and rights review. This does not make the related normalized JSON authoritative.

## 4. Initial root and exclusion policy

Only these non-secret root aliases may enter the protocol:

- `EOMIS_LEGACY_SOURCE`;
- `EOM_AI_SERVER_LEGACY_SOURCE`.

Protected operator configuration will resolve each alias to an exact read-only root. Absolute host
paths never enter worker messages or public responses.

The initial scanner policy is fail-closed:

- scan only reviewed relative-prefix allowlists under one root alias;
- maximum 5,000 observations, 4 GiB of candidate bytes, 512 MiB per observed file, depth 16, and
  normalized path length 500;
- do not open excluded `.env`, credential/auth, Git metadata, model/checkpoint, cache/temp/lock,
  runtime DB/index, socket/device, or outside-allowlist entries as content;
- reject symlinks, path escapes, hard-linked intake candidates, control characters, non-NFC paths,
  and casefold collisions;
- hash every selectable original or derived-comparison file exactly once during a scan and rehash
  every selected original at Content Intake;
- classify textbook/reference-book non-PDF values as derived or excluded, never original;
- emit safe counts and stable codes only to logs or Slack.

The released policy identity and hash will be created with the Phase 2 scanner. This baseline
defines its immutable behavior but does not invent a runtime policy row or DB table.

## 5. Historical schema pins

Phase 1 must preserve these existing schema bytes:

| Contract | SHA-256 |
| --- | --- |
| Knowledge Analysis Request V2 | `bf77196f281dc8c2c22e850e576a9137acb7bc1fea3681400f8855dc1f63414f` |
| Knowledge Analysis Result V2 | `e017752dc52ca32cb18d5e671525d1415c76ce19df023ac33fd3a43e811c3d48` |
| Graph Snapshot Manifest V2 | `2fe24ad351ca7dcd10a9ba7909bf0fe0fe6fb2bf7715ca3dac02d1697cf60d09` |
| Evidence Bundle Manifest V2 | `a908f3dffd665292e5b171d799e8e1e95faa0ed5a4df3cfdc426c8f4f4bfcdaa` |

New legacy contracts are additive. No V1/V2 schema byte is reinterpreted.

## 6. Phase 0 exit

The baseline establishes separate repositories, original-versus-derived ownership, safe aggregate
scale, closed root aliases, exclusions, capacity bounds, historical hashes, and the no-mutation
boundary. It authorizes Phase 1 contract source and tests only. It does not authorize a scanner run,
Content Intake, worker execution, graph publication, migration, deployment, or legacy data import.
