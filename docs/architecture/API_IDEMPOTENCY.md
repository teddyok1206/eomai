# Application API Idempotency

Every non-authentication mutation requires `Idempotency-Key`. The raw key is validated at the HTTP
boundary and never logged or persisted. The database key is an HMAC-SHA-256 of the supplied key.
The request digest is canonical JSON over method, operation ID, validated path parameters, the
validated body, and Operator ID. Sensitive input is represented by a keyed digest before request
canonicalization.

```mermaid
sequenceDiagram
  participant Client
  participant API
  participant DB
  participant App as Application Service
  Client->>API: mutation + Idempotency-Key
  API->>DB: INSERT PROCESSING claim with lease
  alt new claim
    API->>App: typed command
    App->>DB: commit domain state or command
    API->>DB: store bounded result and mark COMPLETED
    API-->>Client: result
  else same request completed
    DB-->>API: stored result
    API-->>Client: replay result
  else different request
    API-->>Client: 409 API_IDEMPOTENCY_CONFLICT
  else live lease
    API-->>Client: 409 + Retry-After
  end
```

The compound unique index `(operator_id, endpoint_key, idempotency_key_hash)` is the concurrent
claim invariant. Lookup is O(log n); the response is capped at 64 KiB and retained for one day.
Token and password-changing endpoints never use this cache. Workflow execution duration does not
extend the API lease: the record is completed when the durable workflow command is registered.
