# H2Orestart 0.7.14 EOM compatibility revision 3

GPL-3.0-or-later derivative of the exact upstream v0.7.14 source, commit
`99b3969b2429d69f974699507001665ceca62041`. It retains revision2's equation and
revision1's picture-crop changes; those released bundles remain unchanged.

`ConvTable-choice-cell-compatibility.patch` changes only the cloned paragraph style
of a single simple paragraph in a cell whose complete text is one of ①–⑤.
If inherited left margin plus one font em cannot fit inside that cell, it reduces
the left margin to the available width. It preserves the cell/column geometry,
right margin, nonzero indentation, text, equations and source paragraph records.
Cells containing other controls, over three simple controls, or additional text are excluded.
The control bound prevents repeated text scans of large split-run paragraphs. HWP paragraph
margins have twice the resolution of cell/font units; the helper uses bounded
64-bit arithmetic and never increases a margin.

The exact upstream `source/soffice/ConvTable.java` SHA-256 is
`f02c6603f1b4e551e77601f2eb842546077cd156e1a26cbaa8d25d373478756d`.
The base revision2 OXT SHA-256 is
`50d8cf433f12270b5ee44fa974993bc36b5804ef550f0ce09b39266305b1b2cb`.
The output version is `0.7.14.3`, SHA-256
`1aaabf0114d6ec1cee130c9f5b01d756a321ba0525d0ea211cccec01acfeb99a`.

Build with the existing Conda interpreter using
`python -m scripts.catalog.build_h2orestart_choice_layout --base-bundle ...
--upstream-table-source ... --output-directory ...` from the repository root.
The existing Java compiler module targets Java8 and the prior deterministic ZIP
codec is reused; no dependency download or new dependency is introduced.
Install only the reviewed bundle through
`scripts/catalog/install_office_equation_converter.sh --choices-v3
--source-commit <exact-installed-source> <reviewed.oxt>`.
The predecessor profiles and bundles remain available; frozen learning inputs do
not inherit this change. No PDF rasterization or page-capture substitute is used.
