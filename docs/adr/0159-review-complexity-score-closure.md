# ADR 0159: Review complexity-score closure

## Status

Accepted for implementation.

## Decision

Review escalation is application-owned.  The worker declares a bounded structural score and the
application recomputes it from the exact authoring Artifact before routing.  A live variation review
counted one visual but omitted the independent point for non-empty statements, so the application
correctly rejected score 1 where the typed draft required 2.

Content Pack 1.20.11 makes the existing six-indicator algorithm executable in the prompt, including
an exact example.  Released contracts and Packs remain immutable.  The application continues to
derive and compare the score rather than trusting or repairing worker output.

The access pattern is six O(1) bounded field/length checks on one pinned authoring result.  There is
no new persistence, index, transaction, retry, or worker communication boundary.  A prompt-only
successor is preferable to weakening validation or silently overwriting the reviewer's declaration.
