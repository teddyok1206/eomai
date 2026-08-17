# HWPX Content-Team Reference Preparation

The POC reference starts from the existing Hancom-saved content-team `문항템플릿.hwpx`. Do not
create a blank document and do not edit the EOMIS copy. Stage the source HWPX and deterministic
reference PNG into a local builder workspace, then run the file-only profile transformer.

```bash
/srv/eom/conda/envs/eom-hwpx/bin/eom-hwpx \
  prepare-content-team-reference \
  --input <STAGED_CONTENT_TEAM_TEMPLATE.hwpx> \
  --reference-image <STAGED_REFERENCE.png> \
  --output <FRESH_WORKSPACE>/eom_hwpx_reference_v1.hwpx
```

The transformer recognizes the fixed observed profile and fails closed if it changes. It preserves:

- the `1x1` problem container;
- page size, margins, paragraph/character styles, border/fill definitions, and namespaces;
- the `3x3` ㄱ/ㄴ/ㄷ `<보기>` table;
- the bottom `9x4` management and solution table.

It deterministically performs only the following profile-bound changes:

- converts the template's `2x2` picture layout example into the POC's unmerged `2x3` data table;
- embeds the deterministic reference PNG as one inline centered picture;
- retains one observed Hancom equation object and replaces its source with `EOM_EQ_PLACEHOLDER`;
- replaces editing-compliance example text with strict EOM markers and placeholder metadata;
- emits five independent ㄱ/ㄴ/ㄷ combination-choice paragraphs;
- removes the separate `5x2` generic-choice table used by items without ㄱ/ㄴ/ㄷ statements;
- redacts creator/last-save metadata and refreshes preview text.

The command does not access PostgreSQL, NAS, EOMIS, worker homes, Docker, Codex, or the network. The
caller supplies files already staged in its workspace. The generated candidate must pass package
analysis, structural validation, binding compilation, and marker uniqueness before the orchestrator
imports it into immutable artifact storage.

This Linux preparation does not establish Hancom compatibility. Exact Windows and Hancom versions,
open/edit/save/reopen behavior, visual layout, stale preview replacement, and re-saved semantic
comparison remain the later manual compatibility gate.
