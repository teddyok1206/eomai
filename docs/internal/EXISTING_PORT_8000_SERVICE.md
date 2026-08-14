# Existing Port 8000 Service

Observed at: `2026-08-14T04:24Z`

This service is unrelated to the new EOM platform. It was inspected read-only and was not stopped, restarted, signaled, or modified.

## Summary

| Item | Value |
| --- | --- |
| Listening address | `0.0.0.0:8000` |
| Process | `uvicorn` |
| PID | `3241999` |
| Owner | `eom` |
| Parent PID | `717206` |
| Start time | `Sat Jun 6 08:21:17 2026 UTC` |
| Executable | `/home/eom/miniconda3/envs/eom_ai_server/bin/python3.11` |
| Working directory | `/home/eom/linux_server_bundle` |
| Command line | `/home/eom/miniconda3/envs/eom_ai_server/bin/python /home/eom/miniconda3/envs/eom_ai_server/bin/uvicorn app.server:app --host 0.0.0.0 --port 8000` |
| cgroup | `user.slice/user-1000.slice/user@1000.service/tmux-spawn-...scope` |
| systemd ownership | user manager scope, not a new EOM system service |
| UFW 8000 | `8000/tcp ALLOW IN Anywhere`, including IPv6 rule |

## Boundary Decision

New EOM does not use port 8000. The reserved new EOM API address is:

```text
127.0.0.1:8765
```

No process environment, `.env`, credentials, tokens, or private files were read.
