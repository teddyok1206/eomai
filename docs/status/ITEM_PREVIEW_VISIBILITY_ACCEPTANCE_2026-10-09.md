# Completed Item Preview visibility correction

Observed at `2026-10-09T04:19:45.334Z`; live HTTPS browser check PASS.

The user reported that a successfully loaded Item still displayed “문항 확인 중”
and was pushed below a large empty area. The existing controller already set
`preview-empty.hidden = true` after success, but `.document-empty { display: grid }`
overrode the browser's default hidden presentation. No API or Item state defect
was inferred from the visible loading message.

A single stylesheet rule now preserves the application's `[hidden]` state across
grid/flex components. The existing loading, failure, unsupported-format and
request-sequence behavior remains unchanged; no separate visibility state machine
or backend workaround was added.

## Evidence

- Actual authenticated HTTPS, same pinned Item Revision before/after:
  `itemrev_2fcbf436bc054b4181bc47ab5795f436`.
- Before: `hidden=true`, computed `display=grid`, empty-area height `700px`,
  Item content already visible. This reproduces the user report.
- After: `hidden=true`, computed `display=none`, empty-area height `0px`,
  Item content visible; zero browser page errors.
- Browser fixture executes the real controller functions and stylesheet:
  success, rapid A→B selection with out-of-order responses, failure, recovery,
  unsupported format, plus hidden/shown grid and flex components PASS.
- Full Web suite with the opt-in existing browser environment: **275 PASS**.
  Ruff/format/mypy on the changed Python test, JavaScript syntax and diff checks PASS.
  The pre-existing Starlette/httpx deprecation warning remains.
- Wheel inventory/RECORD, isolated Web runtime import, non-editable installed
  simulation, service-identity metadata and post-restart smoke PASS.

## Operating scope

Only Web was installed/restarted. Installed source:
`fef818987c87766144c1347a32424d28efaa8faa`.
Wheel SHA: `1a3148bc775439163ab79693ac74f7e5b2f8f8c2fc44b37604848ede74133b79`.
Served stylesheet SHA:
`0e17dabca24cdc57c771d7cfe42d0fdda3b4e249e50e44cdc56f1b6eec698fc8`.
The prior Web `6c765820d21f91dd1ef277219a894f25ddabac57` wheel remains available
for rollback (SHA `08ccb15fa085571f9c15866fa0f3461d5d5dbbc23e82661323ad8089c6df1703`).

API/Catalog/chat runtime, active policies, DB schema, Items, HWPX and historical
receipts were not changed. Browser validation submitted zero model turns and zero
HWPX builds; its other POSTs were login and the existing read-only explorer query.
Earlier diagnostic counters incorrectly labeled these generic POSTs as product
mutations; the final check classifies them by operation, not HTTP method alone.

The separate CHAT-RAG-2 goal remains active and is not marked live-complete by
this presentation fix. Its design is recorded in
[the textbook RAG integration note](../architecture/GENERAL_CHAT_TEXTBOOK_RAG_DESIGN.md).
