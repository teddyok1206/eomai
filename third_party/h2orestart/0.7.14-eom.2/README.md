# H2Orestart 0.7.14 EOM compatibility revision 2

This GPL-3.0-or-later derivative retains the upstream `v0.7.14` commit
`99b3969b2429d69f974699507001665ceca62041` and EOM revision 1's picture-crop patch.
The upstream license and base provenance are in `../0.7.14-eom.1/README.md`.

`ConvEquation-style-compatibility.patch` routes the original equation translator through
`HancomEquationStyle.java` after the existing structural equation conversions. The helper preserves quotes/groups, scopes Hancom roman/italic
switches, and renders isolated operator glyphs as literals instead of incomplete StarMath
expressions. It does not rewrite the uploaded source, rasterize pages, or replace the upstream
equation engine. Script length, group depth and style nesting are bounded.

The exact base OXT SHA-256 is
`2b3ead8f1c782ba47cdc800262e99196850b525347843f0bd9b76e8431a7de96`.
The upstream `source/soffice/ConvEquation.java` SHA-256 is
`0235fe114fc98f05a4ea1c2d5196364c517f7ec0574e4fafaa203775454d06de`.
The output OXT declares version `0.7.14.2`, with SHA-256
`50d8cf433f12270b5ee44fa974993bc36b5804ef550f0ce09b39266305b1b2cb`.

`scripts/catalog/build_h2orestart_equations.py` requires these exact inputs. It compiles only
the two changed/new classes using the installed Java compiler module, UTF-8 and Java 8 source/
target compatibility, then deterministically rebuilds ZIP entries with a fixed UTC timestamp.
No package download, install, root mutation, or network access occurs during that build.
The Java compiler module is already present on the build host; no new runtime dependency is added.
The actual OXT/JAR/build manifest are runtime artifacts and must not be committed to Git.

Install the reviewed output with `scripts/catalog/install_office_equation_converter.sh
--source-commit <exact-installed-source-commit> <reviewed-output.oxt>` through
the existing protected release procedure, after staging the protected installed wheel prefix.
The new fixed unit/profile is independent of legacy
revision 1. Existing historical receipts and material-learning profiles keep revision 1; the new
DB preview generation and new Office review inputs explicitly choose revision 2.

This profile also rejects the observed StarMath OpenSymbol/error-color/error-glyph combination
before publication. That narrow guard is not a proof of arbitrary mathematical or layout fidelity.
Release and real-file evidence are tracked separately from source implementation.
