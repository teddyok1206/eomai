# EOM Port Registry

| Port | Bind | Owner | Status |
| --- | --- | --- | --- |
| 22 | Host interfaces | SSH | Existing, unchanged |
| 5432 | `127.0.0.1` | PostgreSQL | Existing, unchanged |
| 8000 | Existing service bind | Legacy uvicorn service | Existing, unchanged |
| 8765 | `127.0.0.1` | EOM Application API | Assigned |
| 8780 | `127.0.0.1` | EOM Observability Console | Assigned |

Application API must not bind to 8000 or 8780 and must not bind 8765 to `0.0.0.0` or `[::]`.
Observability Console must not bind to 8000 or 8765 and must not bind 8780 to `0.0.0.0` or `[::]`.
No firewall, router forwarding, or TLS policy is changed by either service installation.
