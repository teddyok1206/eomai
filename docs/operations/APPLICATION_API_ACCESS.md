# Application API Access

Application API V0 listens only on `127.0.0.1:8765` and exposes `/api/v1`. Use an SSH tunnel from a
client machine:

```bash
ssh -N -L 8765:127.0.0.1:8765 eom@SERVER
```

The client base URL is `http://127.0.0.1:8765/api/v1/`. It depends only on the exported OpenAPI 3.1
contract, stable schemas, Problem Details error codes, opaque cursors, resource ETags, permissions,
and idempotency keys. It must not infer database tables, NAS paths, Python modules, or worker state.

Send the access token only as `Authorization: Bearer ...`. Send a refresh token only in the JSON
body of `/auth/refresh`. Never put either token in a URL, query parameter, log, crash report, or
shell history. Login and refresh responses use `Cache-Control: no-store` and return raw token values
once. A client must replace both locally stored tokens after every successful refresh.

All domain and Operator mutations require an `Idempotency-Key` of 16 to 128 non-space ASCII
characters. Mutable operations also require the last returned strong ETag in `If-Match`. A 409
idempotency conflict requires a new command decision, while 412 means the resource must be read
again. A 403 `AUTH_REAUTHENTICATION_REQUIRED` requires a new password login; refresh never renews
authentication freshness.

Direct LAN or public HTTP binding is prohibited. Passwords and bearer tokens must not cross a LAN
without TLS. Any future non-loopback exposure requires a separate TLS reverse-proxy design, host and
origin allowlists, and an ADR. Wildcard CORS remains disabled.
