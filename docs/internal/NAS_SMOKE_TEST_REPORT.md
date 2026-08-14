# NAS Smoke Test Report

Performed at: `2026-08-14T04:24:04Z`

## Mount

| Item | Value |
| --- | --- |
| Mount root | `/mnt/nas` |
| EOM NAS root | `/mnt/nas/eom` |
| Source | `//172.30.1.30/AI_Linux` |
| Filesystem | CIFS |
| Protocol | SMB/CIFS 3.0 |
| Options summary | `rw`, `vers=3.0`, `cache=strict`, `soft`, `rsize=4194304`, `wsize=4194304`, `retrans=1`, `actimeo=1` |
| Test user | `eom` |
| Test path | `/mnt/nas/eom/_infra-test/20260814T042404Z-751895` |
| Cleanup | completed; no test directory left under `_infra-test` |

## Results

| Check | Result |
| --- | --- |
| Directory create | PASS |
| Small file write | PASS |
| Read | PASS |
| SHA-256 compare | PASS |
| Rename in same directory | PASS |
| Advisory lock | PASS |
| Sequential write | PASS, 64 MiB at about 106.51 MiB/s |
| Sequential read | PASS, 64 MiB at about 106.42 MiB/s |
| Test file cleanup | PASS |

## Worker NAS Permission

Workers `eom-cdx-01` through `eom-cdx-05` cannot write `/mnt/nas`, `/mnt/nas/eom`, `/mnt/nas/eom/artifacts`, or `/mnt/nas/eom/backups/postgresql` according to permission checks.

Workers may be able to traverse or read directory metadata exposed by the CIFS mount mode. Runtime systemd worker units therefore include:

```ini
InaccessiblePaths=/mnt/nas
```

## Additional Tests Still Needed

- sustained throughput beyond smoke-test size
- two-client concurrent write behavior
- NAS outage and reconnect behavior
- snapshot restore
- long-running worker timeout behavior during NAS stalls
