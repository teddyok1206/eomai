# Legacy Excel Migration Plan

Excel import is deferred. A future adapter will treat each workbook as an immutable Intake source
artifact, record workbook and sheet hashes, and produce a reviewable mapping proposal. It will not
write Item tables directly.

The sequence will be: workbook Intake, deterministic row projection, validation report, human
decision, Content Pack/profile resolution, Item Registration commands, and reconciliation export.
Row identity must be based on declared legacy keys plus source revision, never sheet position
alone. Formula execution, macros, links, and embedded objects remain disabled. Duplicate legacy
IDs and ambiguous current revisions require manual decisions.

The adapter will checkpoint by source-file revision and row key, use batch queries instead of
N+1 lookups, and publish counts and hashes. Production migration needs a separate ADR, test data,
query-plan evidence, and rollback runbook.
