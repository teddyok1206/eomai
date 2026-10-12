"""Small synthetic proof metadata; no public archive/model/runtime is materialized here."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import os
import stat
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
from eom_catalog_contracts.embedding_installed_runtime_proof import (
    EmbeddingInstalledRuntimeProof,
    EmbeddingInstalledRuntimeProofPointer,
    EmbeddingRuntimeProfile,
    embedding_numeric_library_versions,
    installed_runtime_proof_bytes,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes

from tests.unit.inference_transfer_embedding_fixtures import seal


def runtime_proof(
    profile: EmbeddingRuntimeProfile = "CPU_INDEX_FP32",
) -> EmbeddingInstalledRuntimeProof:
    cuda = profile == "CUDA_INDEX_FP32"
    capture: dict[str, Any] = {
        "source": "OWNER_GPU_CAPTURE_LINUX_PROC/1.0"
        if cuda
        else "LINUX_CPUINFO_VENDOR_FAMILY_MODEL_STEPPING/1.0",
        "numeric_device": {
            "kind": "CUDA" if cuda else "CPU",
            "platform": "LINUX_X86_64",
            "hardware_model": "NVIDIA GeForce RTX 5080"
            if cuda
            else "GenuineIntel family 6 model 143 stepping 8",
            "compute_capability": [12, 0] if cuda else None,
            "driver_version": "580.126.09" if cuda else None,
        },
    }
    if cuda:
        capture.update(
            gpu_uuid="GPU-11111111-2222-3333-4444-555555555555",
            pci_bus_id="0000:01:00.0",
            device_minor=0,
            boot_id="11111111-2222-3333-4444-555555555555",
        )
    body: dict[str, Any] = {
        "schema_version": "embedding-installed-runtime-proof/1.0",
        "proof_id": "embeddingruntimeproof_" + "1" * 32,
        "proof_revision_id": "embeddingruntimeproofrev_" + "2" * 32,
        "profile": profile,
        "python_version": "3.12.13",
        "torch_build_cuda_version": "12.8" if cuda else None,
        "device_capture": capture,
        "numeric_libraries": [
            {
                "name": name,
                "version": version,
                "archive": {
                    "wheel_filename": f"{name.replace('-', '_')}-{version}-py3-none-any.whl",
                    "sha256": content_sha256(name),
                    "size_bytes": 100,
                },
                "installed_record": {"sha256": content_sha256({"record": name}), "size_bytes": 100},
                "requested": False,
                "direct_url": None,
                "console_scripts": [],
            }
            for name, version in embedding_numeric_library_versions(profile)
        ],
    }
    return EmbeddingInstalledRuntimeProof.model_validate(seal(body, "proof_sha256"))


def proof_pointer(proof: EmbeddingInstalledRuntimeProof) -> EmbeddingInstalledRuntimeProofPointer:
    return EmbeddingInstalledRuntimeProofPointer(
        proof_id=proof.proof_id,
        proof_revision_id=proof.proof_revision_id,
        profile=proof.profile,
        proof_sha256=proof.proof_sha256,
        proof_raw_sha256=sha256_bytes(installed_runtime_proof_bytes(proof)),
    )


@dataclass(frozen=True)
class StagedSyntheticRuntime:
    proof: EmbeddingInstalledRuntimeProof
    prefix: Path
    archives: dict[str, Path]
    dist_infos: dict[str, Path]
    proof_path: Path
    archive_root: Path
    proc_root: Path


def _write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(0o600)


def synthetic_record(members: dict[str, bytes], record_name: str) -> bytes:
    rows = []
    for name, raw in sorted(members.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")
        rows.append((name, "sha256=" + digest, str(len(raw))))
    rows.append((record_name, "", ""))
    result = io.StringIO(newline="")
    csv.writer(result, lineterminator="\n").writerows(rows)
    return result.getvalue().encode()


def synthetic_wheel(members: dict[str, bytes]) -> bytes:
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, raw in sorted(members.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 12, 0, 0, 0))
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, raw)
    return result.getvalue()


def staged_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: EmbeddingRuntimeProfile = "CPU_INDEX_FP32",
    *,
    with_generated: bool = False,
) -> StagedSyntheticRuntime:
    import eom_catalog_service.embedding_installed_runtime_observer as observer

    prefix = tmp_path / "prefix"
    archives_root, proofs_root, proc_root = (
        tmp_path / name for name in ("archives", "proofs", "proc")
    )
    proof_body = runtime_proof(profile).model_dump(mode="json")
    archives: dict[str, Path] = {}
    dist_infos: dict[str, Path] = {}
    for library in proof_body["numeric_libraries"]:
        name, version = library["name"], library["version"]
        namespace = name.replace("-", "_")
        dist = namespace + "-" + version + ".dist-info"
        dist_infos[name] = prefix / "lib/python3.12/site-packages" / dist
        members = {
            namespace + "/__init__.py": b"# synthetic package; never imported\n",
            dist
            + "/METADATA": f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\n".encode(),
            dist + "/WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n",
        }
        if name == "torch":
            cuda = "'12.8'" if profile == "CUDA_INDEX_FP32" else "None"
            members["torch/version.py"] = f"__version__ = {version!r}\ncuda = {cuda}\n".encode()
        if with_generated and name == "numpy":
            members[dist + "/entry_points.txt"] = (
                b"[console_scripts]\nsynthetic-numeric=numpy.fake:main\n"
            )
        record_name = dist + "/RECORD"
        wheel = synthetic_wheel(members | {record_name: synthetic_record(members, record_name)})
        archive_sha = sha256_bytes(wheel)
        archive = archives_root / archive_sha[7:] / library["archive"]["wheel_filename"]
        archives[name] = archive
        _write(archive, wheel)
        installed = dict(members)
        installed[dist + "/INSTALLER"] = b"pip\n"
        if with_generated and name == "numpy":
            installed[dist + "/REQUESTED"] = b""
            url_raw = canonical_json_bytes(
                {"url": archive.as_uri(), "archive_info": {"hashes": {"sha256": archive_sha[7:]}}}
            )
            installed[dist + "/direct_url.json"] = url_raw
            library["requested"] = True
            library["direct_url"] = {"sha256": sha256_bytes(url_raw), "size_bytes": len(url_raw)}
            wrapper = (
                f"#!{prefix / 'bin/python3.12'}\nimport sys\nfrom numpy.fake import main\n"
                "if __name__ == '__main__':\n    if sys.argv[0].endswith('.exe'):\n"
                "        sys.argv[0] = sys.argv[0][:-4]\n    sys.exit(main())\n"
            ).encode()
            installed["../../../bin/synthetic-numeric"] = wrapper
            library["console_scripts"] = [
                {
                    "name": "synthetic-numeric",
                    "sha256": sha256_bytes(wrapper),
                    "size_bytes": len(wrapper),
                }
            ]
        record_raw = synthetic_record(installed, record_name)
        installed[record_name] = record_raw
        for member, raw in installed.items():
            target = Path(os.path.normpath(prefix / "lib/python3.12/site-packages" / member))
            _write(target, raw)
        library["archive"]["sha256"] = archive_sha
        library["archive"]["size_bytes"] = len(wheel)
        library["installed_record"] = {
            "sha256": sha256_bytes(record_raw),
            "size_bytes": len(record_raw),
        }
    proof = EmbeddingInstalledRuntimeProof.model_validate(seal(proof_body, "proof_sha256"))
    proof_path = proofs_root / proof.proof_id / proof.proof_revision_id / "proof.json"
    _write(proof_path, installed_runtime_proof_bytes(proof))
    _write(prefix / "bin/python3.12", b"synthetic executable identity only; never executed")
    _write(
        proc_root / "cpuinfo",
        b"processor : 0\nvendor_id : GenuineIntel\ncpu family : 6\nmodel : 143\nstepping : 8\n\n"
        b"processor : 1\nvendor_id : GenuineIntel\ncpu family : 6\nmodel : 143\nstepping : 8\n",
    )
    _write(
        proc_root / "driver/nvidia/version",
        b"NVRM version: NVIDIA UNIX Open Kernel Module for x86_64 580.126.09 synthetic\n",
    )
    _write(
        proc_root / "driver/nvidia/gpus/0000:01:00.0/information",
        b"Model: NVIDIA GeForce RTX 5080\nGPU UUID: GPU-11111111-2222-3333-4444-555555555555\n"
        b"Bus Location: 0000:01:00.0\nDevice Minor: 0\n",
    )
    _write(proc_root / "sys/kernel/random/boot_id", b"11111111-2222-3333-4444-555555555555\n")
    for path in (tmp_path, *tmp_path.rglob("*")):
        if path.is_dir():
            path.chmod(0o700)
    monkeypatch.setattr(observer, "_OWNER_UID", os.geteuid())
    monkeypatch.setattr(observer, "_PROFILE_PREFIXES", MappingProxyType({profile: prefix}))
    monkeypatch.setattr(observer, "_PROOF_ROOT", proofs_root)
    monkeypatch.setattr(observer, "_ARCHIVE_ROOT", archives_root)
    monkeypatch.setattr(observer, "_PROC_ROOT", proc_root)
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.setattr(sys, "executable", str(prefix / "bin/python3.12"))
    return StagedSyntheticRuntime(
        proof, prefix, archives, dist_infos, proof_path, archives_root, proc_root
    )
