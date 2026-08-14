# Infrastructure Baseline

Source audit: `/home/eom/EOMIS/eom-infra-audit/EOM_SERVER_NAS_AUDIT.json` and Markdown report, read only. Raw audit files were not copied into this repository.

Audit completed at: `2026-08-13T18:01:11Z`

This baseline is a point-in-time summary. Docker, PostgreSQL, runtime directories, users, and NAS paths may differ after the bootstrap recorded in `INFRA_BOOTSTRAP_REPORT.md`.

## Server

| Item | Value |
| --- | --- |
| OS | Ubuntu 24.04.4 LTS |
| Kernel | 6.8.0-106-generic |
| Architecture | x86_64 |
| CPU | AMD Ryzen 7 7800X3D, 8 physical cores, 16 logical threads |
| RAM | about 30.47 GiB total, about 27.88 GiB available at audit time |
| Swap | 8 GiB |
| Local storage | NVMe SSD, ext4, about 584 GiB available at audit time |
| GPU | NVIDIA GeForce RTX 5080, about 15.92 GiB VRAM |
| NVIDIA driver | 580.126.09 |
| NVIDIA Container Toolkit | Not installed at audit time and intentionally not installed in bootstrap |

## Network And NAS

| Item | Value |
| --- | --- |
| Primary interface | enp6s0 |
| Server private IP | 172.30.1.61 |
| Link | 1 Gbps full duplex, MTU 1500 |
| NAS mount | `/mnt/nas` |
| NAS source | `//172.30.1.30/AI_Linux` |
| NAS protocol | CIFS/SMB 3.0 |
| NAS capacity | more than 19 TiB available at audit time |
| NAS suitability | artifact and backup storage |
| NAS PostgreSQL suitability | not suitable for PostgreSQL primary data |

## Tooling

| Item | Value |
| --- | --- |
| Conda | `/home/eom/miniconda3/condabin/conda`, conda 26.1.1 |
| Existing Conda envs | base, `EOMIS`, `eom_ai_server` |
| Codex | `/usr/local/bin/codex`, codex-cli 0.145.0 at audit time |
| Root Codex | `/root/.codex` existed and root was logged in |
| Docker | not installed at audit time |
| PostgreSQL | not installed at audit time |
| Existing network service | uvicorn on `0.0.0.0:8000`, unrelated to new EOM |

## New EOM Paths

| Purpose | Path |
| --- | --- |
| Repository | `/home/eom/EOM` |
| Runtime | `/srv/eom` |
| System configuration | `/etc/eom` |
| Short-term logs | `/var/log/eom` |
| NAS persistent root | `/mnt/nas/eom` |
| Reserved EOM API | `127.0.0.1:8765` |
