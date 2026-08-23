# Kordoc dependency record

EOM uses Kordoc only in the isolated HWPX renderer profile `kordoc-markdown-v1`.

- Upstream: `https://github.com/chrisryugj/kordoc`
- npm package: `kordoc`
- pinned version: `4.9.0`
- npm integrity: `sha512-MPgHDYjuePA1p0yei0Sx8obWdbrGYc5tzMWposRVa9P9fWZ8yW0sNVh0YjffPbmZdi7xHoQJn60iTLVG+SI2Iw==`
- license: MIT
- qualified runtime: Node.js 22.23.2
- install policy: `npm ci --omit=optional --ignore-scripts`
- runtime policy: `KORDOC_OFFLINE=1`, private network, fixed workspace root

The dependency is justified by its native HWPX equation generation, GFM/merged-table generation,
HWPX validation, and parse/round-trip support. Reimplementing those document structures would add a
large, format-specific maintenance and validation burden.

The installed npm distribution includes upstream `LICENSE`, `NOTICE`, and `THIRD_PARTY` material.
Release verification requires those files. Optional OCR, PDF rasterization, and browser components
are deliberately omitted because the EOM renderer accepts bounded Markdown and emits HWPX only.

Kordoc's package metadata accepts older Node versions, but Node 20 is end-of-life. EOM qualifies
and enforces the exact Node 22 LTS line used by the isolated Conda environment. The dependency is
resolved as `conda-forge::nodejs=22.23.2` because the configured defaults channel does not publish a
Node 22 build; no other environment package is moved to conda-forge by this decision.
