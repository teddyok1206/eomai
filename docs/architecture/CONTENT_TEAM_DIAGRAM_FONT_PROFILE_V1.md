# Content-team diagram font profile V1

## Decision

EOM's generated science diagrams use one pinned, system-installed font profile instead of an
ambient desktop font search or a Python convenience package. The reviewed content-team source
defines `SM JGothic Std` for compact Korean diagram labels and `Century Old Style` for Latin,
numeric, and axis labels. `Noto Sans CJK KR` is the pinned Korean missing-glyph fallback and
`DejaVu Serif` is the fixed system font for Greek and mathematical labels. This profile applies to
deterministic SVG output and to the authoritative SVG overlay used by the local-hybrid image route.

The current renderer is `/usr/bin/rsvg-convert`; it does not import Matplotlib. Installing
`koreanize-matplotlib` would therefore not change production output and would add an unused Python
dependency.

1. **Responsibility and boundary.** The image worker returns only bounded SVG data. Catalog owns
   font allowlisting, SVG sanitation, rasterization, and Artifact commit. The installer owns the
   one-time system materialization of reviewed font bytes. Workers cannot install or dereference
   fonts and never write to NAS.
2. **Canonical source.** The authorized content-team font files are source evidence, not a runtime
   dependency. Runtime uses root-owned files beneath `/usr/local/share/fonts/eom`; each expected
   SHA-256 is pinned in source. Git contains no font binary. Historical EOMIS files are read-only
   and are never modified.
3. **Entity and revision model.** `eom-content-team-diagram-fonts/1.0` is an immutable renderer
   dependency profile. Generated SVG/PNG Artifact Revisions record the primary Korean-font hash and
   the canonical font-manifest hash separately from the renderer binary hash and drawing hash.
4. **Pointers and resolution.** Before rasterization, Catalog verifies every known font path is a
   regular non-symlink, root-owned, mode `0644`, readable, and byte-equal to its pinned SHA-256.
   Fontconfig must resolve each reviewed family to the exact installed path during deployment.
5. **Primary access patterns.** Font identity is a four-entry immutable tuple scanned once per
   metadata change and cached by filesystem identity. SVG family membership is a constant-time set
   lookup. Hangul classification is one bounded pass over each text label.
6. **Structures and indexes.** A tuple preserves profile order for canonical manifest hashing; a
   `frozenset` performs family membership checks. No database table or index is added because fonts
   are immutable renderer dependencies, not domain entities.
7. **Scale and complexity.** The profile has four fixed files. Readiness hashing is O(total font
   bytes) only after metadata changes; label validation is O(label characters). Normal rendering
   adds no database query and no large in-memory copy.
8. **Transaction and concurrency.** Installation copies only three reviewed files to fixed targets,
   then refreshes the system font cache. A workflow pins the resulting font manifest in its output
   Artifact provenance. Installation is completed before Catalog reload; no partial profile is
   accepted by readiness.
9. **Dependency direction.** Content Pack instructions name reviewed font families; Catalog's
   infrastructure adapter validates and renders them. Workflow/domain contracts do not import
   fontconfig, subprocess, or filesystem code.
10. **Failure, retry, and idempotency.** Unknown family, Korean text in a non-Korean family, missing
    explicit family, unsafe font metadata, hash drift, or wrong fontconfig resolution fails before
    Artifact registration. Re-running the installer with the same bytes is idempotent. There is no
    automatic fallback to an ambient font.
11. **Simpler alternative.** Keeping `Droid Sans Fallback` avoids installation but does not match
    the reviewed content-team style and can produce poor Korean glyph/layout results. Adding
    Matplotlib localization does not affect the actual SVG renderer. An explicit pinned profile is
    the smallest change that fixes the production boundary without adding a parallel graphics
    stack.

## Profile

| Role | Family | Runtime file | SHA-256 |
|---|---|---|---|
| Korean diagram label | `SM JGothic Std` | `SMJGothicStd-Regular.otf` | `9200e1e4…adea1` |
| Korean glyph fallback | `Noto Sans CJK KR` | `NotoSansCJKkr-Regular.otf` | `6bcb2a07…992a` |
| Latin/numeric label | `Century Old Style` | `CenturyOldStyle-Regular.otf` | `7f942040…e338` |
| Latin italic label | `Century Old Style` | `CenturyOldStyle-Italic.otf` | `44b00cbd…809` |
| Greek/math label | `DejaVu Serif` | system `DejaVuSerif.ttf` | `8f2c103b…c7ab` |
| Historical SVG compatibility | `Droid Sans Fallback` | Ubuntu system font | `acb6440a…77b8` |

Mixed Korean/Latin labels use the exact `SM JGothic Std, Noto Sans CJK KR` family stack so all
common content-team glyphs resolve from the primary face and uncommon Korean glyphs remain pinned.
The sanitizer accepts only the reviewed family values above and only `normal` or `italic` style.
`Droid Sans Fallback` is accepted solely so already-pinned historical workflows remain renderable;
new Content Pack instructions never select it.
Every text node must either declare a reviewed family or inherit one from a validated parent group.

## Deployment and rollback

Install authorized source bytes through
`scripts/catalog/install_content_team_svg_fonts.sh --source-dir <reviewed-directory>`, validate the
with `--korean-fallback-source <reviewed-noto-file>`, validate the existing librsvg boundary,
deploy Catalog, then activate the immutable companion Content Pack
release. Rollback restores the prior Content Pack pointer and prior Catalog release. Historical
Artifact Revisions retain their original renderer/font provenance; font binaries are not deleted as
part of pointer rollback.
