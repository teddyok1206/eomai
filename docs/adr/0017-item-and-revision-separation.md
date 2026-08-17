# ADR 0017: Separate Item Identity from Revisions

Status: Accepted

An Item is a stable logical identity. Its content is an immutable numbered revision. Workflows,
usage, and provenance pin a revision; only navigational queries may follow the current pointer.
Corrections append a revision and supersede the old pointer. This prevents history from changing
when current content advances.
