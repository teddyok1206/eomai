# ADR 0014: Manual Content Intake

## Status

Accepted

## Decision

EOM accepts content-team files through a manual, artifact-backed intake boundary. Content leads do
not use Git. ChatGPT analysis is an optional manual external input and has no server-side API or
automatic trust. Raw files, analysis proposals, and canonical Content Pack source remain separate.

All source evidence is hashed and committed immutably. Deterministic validation and an explicit
human decision precede canonical pack generation. Workers receive neither the raw intake directory
nor the analysis conversation.

## Consequences

V0 supports heterogeneous files without pretending to understand every document format. It adds a
manual handoff but preserves provenance, prevents unreviewed content from reaching prompts, and
keeps content-team workflow independent from engineering Git history.
