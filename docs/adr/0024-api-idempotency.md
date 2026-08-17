# ADR 0024: Database-Backed API Idempotency

Status: Accepted

Mutation claims use a PostgreSQL compound unique key and an expiring lease. Raw client keys are
replaced by HMAC-SHA-256 and requests by canonical SHA-256. A completed bounded command result is
replayed only when the request digest matches. Different requests conflict and active claims return
`Retry-After`.

An in-memory map cannot survive restart or coordinate concurrent API transactions. Holding a claim
until an asynchronous workflow finishes would conflate HTTP delivery with workflow execution, so a
claim completes when command registration is durable.
