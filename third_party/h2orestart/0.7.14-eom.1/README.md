# H2Orestart 0.7.14 EOM compatibility revision 1

EOM uses the upstream H2Orestart `v0.7.14` source at commit
`99b3969b2429d69f974699507001665ceca62041` from
<https://github.com/ebandal/H2Orestart>. Upstream and this derivative are distributed under
GPL-3.0; the upstream `COPYING` SHA-256 is
`2fcbc59fd6474f7451a53b73bb38648034eeb71fcd3613330b0ffd6296d94784`.

`ConvGraphics-crop-compatibility.patch` changes only the picture-crop derivative path. Raster
bytes are decoded directly with ImageIO instead of being round-tripped through LibreOffice's
`GraphicProvider.storeGraphic` and a temporary PNG. If an unsupported vector or malformed crop
cannot produce a safe derivative, the importer retains the XGraphic that LibreOffice already
decoded. It does not edit the uploaded HWP/HWPX source.

The reviewed OXT declares version `0.7.14.1` and has SHA-256
`2b3ead8f1c782ba47cdc800262e99196850b525347843f0bd9b76e8431a7de96`. The generated OXT is a
runtime artifact and is deliberately not stored in Git. Build it from the pinned upstream source
and official `v0.7.14` OXT, apply the patch, compile the three `ConvGraphics` class files for Java 8,
replace them in `H2Orestart.jar`, set the extension version, and use a fixed UTC ZIP timestamp. The
version substitution preserves the upstream `description.xml` CRLF bytes. The installer accepts
only the exact reviewed digest.

The upstream Java file is predominantly CRLF. Apply the repository patch with
`git apply --ignore-space-change --ignore-whitespace` to the exact pinned tree; compilation of that
clean patched tree must produce `soffice/ConvGraphics.class` SHA-256
`d51d4debc0904fdb23de31f9cf42286f148555eda3e7549bbd1ad77ce06a6bf0` before packaging.

The compatibility revision was checked against an HWP fixture, an ordinary image-bearing HWPX,
and a 25-image HWPX. EOM still treats every Office upload as untrusted and validates the derived PDF
before committing an intake Artifact Revision.
