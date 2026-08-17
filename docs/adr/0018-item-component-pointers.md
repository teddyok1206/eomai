# ADR 0018: Store Item Components as Artifact Pointers

Status: Accepted

Item components store logical artifact ID, artifact revision ID, SHA-256, schema reference, media
type, role, and ordinal. Binary and full Item payloads are not copied into PostgreSQL. Resolution
validates existence, ownership, approval, schema, media type, lifecycle, and hash. Missing, stale,
or mismatched pointers fail explicitly.
