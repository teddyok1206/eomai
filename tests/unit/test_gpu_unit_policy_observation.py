"""Closed-family effective-policy parsing with no actual systemctl invocation."""

import subprocess
from types import SimpleNamespace

import pytest
from eom_catalog_service import gpu_unit_policy_observation as policy
from eom_identifiers import sha256_bytes

from tests.unit.test_image_gpu_unit_observation import UNIT as IMAGE_UNIT
from tests.unit.test_image_gpu_unit_observation import policy as image_policy

CUDA_UNIT = "eom-embedding-benchmark-cuda@" + "1" * 32 + ".service"
CUDA_BUDGET_UNIT = "eom-embedding-benchmark-cuda-budget600@" + "1" * 32 + ".service"


@pytest.mark.parametrize(
    "account,unit",
    (
        ("eom-image", IMAGE_UNIT),
        ("eom-embedding-cuda", CUDA_UNIT),
        ("eom-embedding-cuda", CUDA_BUDGET_UNIT),
    ),
)
@pytest.mark.parametrize(
    "fault",
    (
        None,
        "user",
        "group",
        "extra",
        "duplicate",
        "device",
        "duplicate_device",
        "nonzero",
        "oversize",
        "oserror",
        "timeout",
    ),
)
def test_exact_family_device_allowlist_and_bounded_read_fail_closed(
    monkeypatch, account, unit, fault
):
    raw = image_policy().replace(b"eom-image", account.encode())
    if fault == "user":
        raw = raw.replace(b"User=" + account.encode(), b"User=root")
    elif fault == "group":
        raw = raw.replace(b"Group=" + account.encode(), b"Group=eom")
    elif fault == "extra":
        raw += b"Unreviewed=yes\n"
    elif fault == "duplicate":
        raw += b"Restart=no\n"
    elif fault == "device":
        raw = raw.replace(b"/dev/nvidia0 rw", b"/dev/nvidia0 rwm")
    elif fault == "duplicate_device":
        raw += b"DeviceAllow=/dev/nvidia0 rw\n"
    elif fault == "oversize":
        raw += b"x" * 16385
    calls = []

    def read(arguments, **kwargs):
        calls.append(arguments)
        assert arguments[:3] == ("/usr/bin/systemctl", "show", unit)
        assert kwargs["timeout"] == 10 and kwargs["capture_output"] and not kwargs["check"]
        assert kwargs["env"] == {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}
        if fault == "oserror":
            raise OSError("synthetic unavailable")
        if fault == "timeout":
            raise subprocess.TimeoutExpired(arguments, 10)
        return SimpleNamespace(returncode=1 if fault == "nonzero" else 0, stdout=raw, stderr=b"")

    monkeypatch.setattr(
        policy, "subprocess", SimpleNamespace(run=read, TimeoutExpired=subprocess.TimeoutExpired)
    )
    if fault is None:
        assert policy.observe_gpu_unit_policy(unit, worker_account=account) == sha256_bytes(raw)
    else:
        with pytest.raises(ValueError, match="GPU_UNIT_POLICY_"):
            policy.observe_gpu_unit_policy(unit, worker_account=account)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "unit,account",
    (
        (IMAGE_UNIT, "eom-embedding-cuda"),
        (CUDA_UNIT, "eom-image"),
        ("--all", "eom-image"),
        ("other.service", "eom-embedding-cuda"),
        (CUDA_UNIT, "root"),
        (CUDA_BUDGET_UNIT, "eom-image"),
        ("eom-embedding-benchmark-cpu-budget600@" + "a" * 32 + ".service", "eom-embedding-cuda"),
        ("eom-embedding-benchmark-cuda-budget601@" + "a" * 32 + ".service", "eom-embedding-cuda"),
        ("eom-embedding-benchmark-cuda-budget600@" + "A" * 32 + ".service", "eom-embedding-cuda"),
        (None, "eom-embedding-cuda"),
    ),
)
def test_arbitrary_or_cross_family_unit_is_refused_before_process_execution(
    monkeypatch, unit, account
):
    monkeypatch.setattr(
        policy,
        "subprocess",
        SimpleNamespace(run=lambda *_a, **_kw: pytest.fail("untrusted unit executed")),
    )
    with pytest.raises(ValueError):
        policy.observe_gpu_unit_policy(unit, worker_account=account)
