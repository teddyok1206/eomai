"""Shared systemd isolation properties for untrusted PDF parsing workloads."""

from __future__ import annotations

PDF_RENDER_SANDBOX = (
    "NoNewPrivileges=yes",
    "PrivateTmp=yes",
    "PrivateNetwork=yes",
    "PrivateDevices=yes",
    "ProtectSystem=strict",
    "ProtectHome=yes",
    "ProtectKernelTunables=yes",
    "ProtectKernelModules=yes",
    "ProtectKernelLogs=yes",
    "ProtectControlGroups=yes",
    "RestrictSUIDSGID=yes",
    "LockPersonality=yes",
    "RestrictRealtime=yes",
    "CapabilityBoundingSet=",
    "AmbientCapabilities=",
    "RestrictAddressFamilies=AF_UNIX",
    "MemoryMax=1G",
    "TasksMax=32",
    "RuntimeMaxSec=45",
    "TimeoutStopSec=5",
    "UMask=0077",
    "InaccessiblePaths=/mnt/nas /home/eom/EOM /home/eom/EOMIS /etc/eom "
    "/root/.codex /srv/eom/worker-homes /var/run/docker.sock",
)
