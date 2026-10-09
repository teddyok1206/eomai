# Item Preview delimited math correction

Observed `2026-10-09T05:22:55Z`; actual authenticated HTTPS browser PASS.

The user confirmed the hidden loading-area fix and then reported broken `$…$`
math in Item Preview. Existing text-only DOM insertion did not parse delimited
LaTeX. This change is browser presentation only, not a canonical Item rewrite.

## Evidence

- Same existing pinned Item Revision before and after:
  `itemrev_2fcbf436bc054b4181bc47ab5795f436`.
- Both authorized Preview response digests:
  `8d8cc5d1e71920a67d1fd247c4273d94d6aa4f6648840678839bcbf996d9354f`
  (SHA-256 of the parsed response serialized by the diagnostic, not an Artifact hash).
- Before: 9 authored fields containing math delimiters, zero MathML expressions.
- After: same 9 fields, **43 MathML expressions**, zero fallback expressions,
  zero browser page errors, visible Item content, loading-area height `0px`.
- Full Web suite, including opt-in real Chromium: **278 PASS**. The focused
  13-test run overlaps this suite and is not added to its count.
- Actual controller fixtures cover paragraph/material/inquiry/table/choices/claims/
  explanation fields and explicit delimited equation blocks; existing bare Hancom
  script formatting is preserved. Fractions, roots, indices, powers, display math,
  ordinary/escaped dollars, malformed input, macro bounds/isolation and unsafe
  resource/HTML commands are covered independently of the live Item's contents.
- Ruff, format, mypy, module syntax, pinned vendor re-import check and diff checks PASS.
- Exact wheel inventory/RECORD, isolated target import, non-editable installation
  simulation and installed `eom-web` identity verification PASS (43 files).
- HTTPS live/ready: `LIVE` / `READY`; Web service active after restart.

## Release and impact

Web installed source: `926f3791677ddea13ef56204305127e2aa612241`.
Wheel SHA-256: `bca90348c2f09fd358ceadf17481152189013d749794040d37805f4aaf9d2289`.
Previous compatible Web source `fef818987c87766144c1347a32424d28efaa8faa`
and its rollback wheel remain available, verified SHA-256:
`1a3148bc775439163ab79693ac74f7e5b2f8f8c2fc44b37604848ede74133b79`.

Only Web was installed/restarted. No API/Catalog/chat runtime, DB migration,
canonical Item, approval, HWPX or historical receipt was changed. Actual browser
checks submitted zero model turns, HWPX builds or approvals. Login/logout and
authorized read queries were the only session/application interactions.

The first before-check diagnostic missed the already-completed initial Preview
response and timed out. Its read-only browser check was corrected to inspect the
selected immutable Preview; this was not a product retry or new generation.
Initial Node syntax invocation used CommonJS for ESM assets; corrected module
invocation PASS. Neither diagnostic issue was patched into production behavior.

Design, dependency rationale and safety limits:
[Item Preview math presentation](../architecture/ITEM_PREVIEW_MATH_PRESENTATION.md).
The independent textbook GraphRAG goal remains active; this fix does not claim its
native tool connection or operational acceptance is complete.
