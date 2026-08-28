"""Infrastructure doctor with explicit least-privilege warning semantics."""

from __future__ import annotations

import argparse
import grp
import json
import os
import pwd
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class CheckStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: CheckStatus
    code: str
    detail: str


class DoctorReport:
    def __init__(self) -> None:
        self.checks: list[DoctorCheck] = []

    def add(self, name: str, status: CheckStatus, code: str, detail: str) -> None:
        self.checks.append(DoctorCheck(name, status, code, detail))

    @property
    def passed(self) -> bool:
        return all(check.status is not CheckStatus.FAIL for check in self.checks)

    @property
    def has_warnings(self) -> bool:
        return any(check.status in {CheckStatus.WARN, CheckStatus.UNKNOWN} for check in self.checks)

    @property
    def result(self) -> str:
        if not self.passed:
            return "failed"
        if self.has_warnings:
            return "pass_with_warnings"
        return "passed"

    def as_json(self) -> str:
        return json.dumps(
            {
                "checks": [
                    {**asdict(check), "status": check.status.value} for check in self.checks
                ],
                "has_warnings": self.has_warnings,
                "passed": self.passed,
                "result": self.result,
            },
            sort_keys=True,
        )


class CommandExecutor(Protocol):
    def run(self, arguments: Sequence[str]) -> subprocess.CompletedProcess[str]: ...


class SubprocessExecutor:
    def run(self, arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            tuple(arguments),
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )


def classify_docker_visibility(
    *, success: bool, diagnostic: str, privileged: bool, daemon_active: bool
) -> DoctorCheck:
    if success:
        return DoctorCheck(
            "docker_visibility", CheckStatus.PASS, "DOCKER_VISIBLE", "Docker daemon is visible"
        )
    denied = any(
        marker in diagnostic.casefold()
        for marker in ("permission denied", "access denied", "operation not permitted")
    )
    if denied and not privileged and daemon_active:
        return DoctorCheck(
            "docker_visibility",
            CheckStatus.WARN,
            "EXPECTED_LEAST_PRIVILEGE_WARNING",
            "Docker socket is intentionally unavailable to the normal operator",
        )
    return DoctorCheck(
        "docker_visibility",
        CheckStatus.FAIL,
        "DOCKER_DAEMON_UNAVAILABLE",
        "Docker daemon access failed",
    )


def summarize_docker_and_database(docker: DoctorCheck, database_ok: bool) -> DoctorReport:
    report = DoctorReport()
    report.checks.append(docker)
    report.add(
        "postgres_application_connectivity",
        CheckStatus.PASS if database_ok else CheckStatus.FAIL,
        "POSTGRES_APPLICATION_CONNECTED" if database_ok else "POSTGRES_APPLICATION_UNAVAILABLE",
        "Application database connection succeeded"
        if database_ok
        else "Application database connection failed",
    )
    return report


class InfrastructureDoctor:
    def __init__(self, *, privileged: bool, executor: CommandExecutor | None = None) -> None:
        self.privileged = privileged
        self.executor = executor or SubprocessExecutor()
        self.report = DoctorReport()

    def run(self) -> DoctorReport:
        if self.privileged and os.geteuid() != 0:
            self.report.add(
                "privileged_mode",
                CheckStatus.FAIL,
                "PRIVILEGED_MODE_REQUIRES_ROOT",
                "Privileged doctor must run as root",
            )
            return self.report
        self._docker()
        self._postgres()
        self._filesystem()
        self._workers()
        self._repository_and_ports()
        return self.report

    def _command_check(
        self, name: str, arguments: Sequence[str], pass_code: str, fail_code: str, detail: str
    ) -> bool:
        completed = self.executor.run(arguments)
        success = completed.returncode == 0
        self.report.add(
            name,
            CheckStatus.PASS if success else CheckStatus.FAIL,
            pass_code if success else fail_code,
            detail if success else f"{detail} failed",
        )
        return success

    def _docker(self) -> None:
        if shutil.which("docker") is None:
            self.report.add(
                "docker_binary",
                CheckStatus.FAIL,
                "DOCKER_BINARY_MISSING",
                "Docker executable is missing",
            )
            return
        self.report.add(
            "docker_binary", CheckStatus.PASS, "DOCKER_BINARY_PRESENT", "Docker executable exists"
        )
        self._command_check(
            "docker_compose",
            ("docker", "compose", "version"),
            "DOCKER_COMPOSE_PRESENT",
            "DOCKER_COMPOSE_MISSING",
            "Docker Compose plugin",
        )
        daemon_active = self.executor.run(("systemctl", "is-active", "docker")).returncode == 0
        self.report.add(
            "docker_daemon",
            CheckStatus.PASS if daemon_active else CheckStatus.FAIL,
            "DOCKER_DAEMON_ACTIVE" if daemon_active else "DOCKER_DAEMON_INACTIVE",
            "Docker daemon is active" if daemon_active else "Docker daemon is inactive",
        )
        info = self.executor.run(("docker", "info"))
        visibility = classify_docker_visibility(
            success=info.returncode == 0,
            diagnostic=info.stderr,
            privileged=self.privileged,
            daemon_active=daemon_active,
        )
        self.report.checks.append(visibility)
        if visibility.status is not CheckStatus.PASS:
            self.report.add(
                "postgres_container_health",
                CheckStatus.UNKNOWN,
                "DOCKER_DETAIL_UNAVAILABLE",
                "Container detail requires explicit privileged inspection",
            )
            return
        compose = self.executor.run(
            (
                "docker",
                "compose",
                "--env-file",
                "/etc/eom/secrets/postgres.env",
                "-f",
                "/home/eom/EOM/infra/compose/compose.yml",
                "ps",
                "eom-postgres",
            )
        )
        self.report.add(
            "compose_project",
            CheckStatus.PASS if compose.returncode == 0 else CheckStatus.FAIL,
            "COMPOSE_PROJECT_REACHABLE"
            if compose.returncode == 0
            else "COMPOSE_PROJECT_UNREACHABLE",
            "PostgreSQL Compose project is reachable"
            if compose.returncode == 0
            else "PostgreSQL Compose project is unavailable",
        )
        health = self.executor.run(
            (
                "docker",
                "inspect",
                "-f",
                "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
                "eom-postgres",
            )
        )
        healthy = health.returncode == 0 and health.stdout.strip() == "healthy"
        self.report.add(
            "postgres_container_health",
            CheckStatus.PASS if healthy else CheckStatus.FAIL,
            "POSTGRES_CONTAINER_HEALTHY" if healthy else "POSTGRES_CONTAINER_UNHEALTHY",
            "PostgreSQL container is healthy" if healthy else "PostgreSQL container is not healthy",
        )

    def _postgres(self) -> None:
        connected = False
        try:
            from eom_orchestrator.database import build_engine
            from sqlalchemy import text

            engine = build_engine()
            try:
                with engine.connect() as connection:
                    connected = connection.execute(text("SELECT 1")).scalar_one() == 1
            finally:
                engine.dispose()
        except Exception:
            connected = False
        self.report.add(
            "postgres_application_connectivity",
            CheckStatus.PASS if connected else CheckStatus.FAIL,
            "POSTGRES_APPLICATION_CONNECTED" if connected else "POSTGRES_APPLICATION_UNAVAILABLE",
            "Application database connection succeeded"
            if connected
            else "Application database connection failed",
        )
        sockets = self.executor.run(("ss", "-lntH"))
        listeners = sockets.stdout.splitlines() if sockets.returncode == 0 else []
        loopback = any("127.0.0.1:5432" in line for line in listeners)
        wildcard = any("0.0.0.0:5432" in line or "[::]:5432" in line for line in listeners)
        self.report.add(
            "postgres_loopback_bind",
            CheckStatus.PASS if loopback else CheckStatus.FAIL,
            "POSTGRES_LOOPBACK_BOUND" if loopback else "POSTGRES_LOOPBACK_MISSING",
            "PostgreSQL loopback listener is present"
            if loopback
            else "Loopback listener is absent",
        )
        self.report.add(
            "postgres_wildcard_bind",
            CheckStatus.FAIL if wildcard else CheckStatus.PASS,
            "POSTGRES_WILDCARD_EXPOSED" if wildcard else "POSTGRES_NOT_WILDCARD_EXPOSED",
            "PostgreSQL wildcard listener is present"
            if wildcard
            else "PostgreSQL is not wildcard-bound",
        )

    def _filesystem(self) -> None:
        self._metadata("srv_eom_metadata", Path("/srv/eom"), "root:eom:711")
        self._metadata("secret_directory_metadata", Path("/etc/eom/secrets"), "root:eom:750")
        try:
            free_bytes = shutil.disk_usage("/srv/eom").free
        except OSError:
            free_bytes = 0
        enough = free_bytes > 50 * 1024**3
        self.report.add(
            "srv_eom_capacity",
            CheckStatus.PASS if enough else CheckStatus.WARN,
            "CAPACITY_SUFFICIENT" if enough else "CAPACITY_BELOW_50_GIB",
            "/srv/eom free capacity is sufficient"
            if enough
            else "/srv/eom free capacity is below 50 GiB",
        )
        mounted = self.executor.run(("findmnt", "-T", "/mnt/nas")).returncode == 0
        self.report.add(
            "nas_mount",
            CheckStatus.PASS if mounted else CheckStatus.FAIL,
            "NAS_MOUNTED" if mounted else "NAS_NOT_MOUNTED",
            "NAS mount is present" if mounted else "NAS mount is absent",
        )
        artifact_root = Path("/mnt/nas/eom/artifacts").is_dir()
        self.report.add(
            "nas_artifact_root",
            CheckStatus.PASS if artifact_root else CheckStatus.FAIL,
            "NAS_ARTIFACT_ROOT_PRESENT" if artifact_root else "NAS_ARTIFACT_ROOT_MISSING",
            "NAS artifact root exists" if artifact_root else "NAS artifact root is absent",
        )
        codex = Path("/usr/local/bin/codex").is_file()
        self.report.add(
            "codex_binary",
            CheckStatus.PASS if codex else CheckStatus.FAIL,
            "CODEX_PRESENT" if codex else "CODEX_MISSING",
            "Codex executable exists" if codex else "Codex executable is absent",
        )

    def _metadata(self, name: str, path: Path, expected: str) -> None:
        try:
            metadata = path.stat()
            actual = (
                f"{pwd.getpwuid(metadata.st_uid).pw_name}:"
                f"{grp.getgrgid(metadata.st_gid).gr_name}:{metadata.st_mode & 0o777:o}"
            )
        except (KeyError, OSError):
            actual = "unavailable"
        valid = actual == expected
        self.report.add(
            name,
            CheckStatus.PASS if valid else CheckStatus.FAIL,
            "FILESYSTEM_METADATA_VALID" if valid else "FILESYSTEM_METADATA_INVALID",
            f"{path} metadata is valid" if valid else f"{path} metadata is invalid",
        )

    def _workers(self) -> None:
        forbidden_groups = {"sudo", "docker", "eom"}
        for worker in (
            "eom-cdx-01",
            "eom-cdx-02",
            "eom-cdx-03",
            "eom-cdx-04",
            "eom-cdx-05",
            "eom-cdx-06",
        ):
            try:
                account = pwd.getpwnam(worker)
            except KeyError:
                self.report.add(
                    f"worker_{worker}",
                    CheckStatus.FAIL,
                    "WORKER_MISSING",
                    f"{worker} is absent",
                )
                continue
            group_names = {
                grp.getgrgid(group_id).gr_name
                for group_id in os.getgrouplist(worker, account.pw_gid)
            }
            unsafe_groups = group_names & forbidden_groups
            self.report.add(
                f"worker_{worker}_groups",
                CheckStatus.FAIL if unsafe_groups else CheckStatus.PASS,
                "WORKER_FORBIDDEN_GROUP" if unsafe_groups else "WORKER_GROUPS_RESTRICTED",
                f"{worker} has a forbidden group"
                if unsafe_groups
                else f"{worker} group membership is restricted",
            )
            for label, path in (
                ("home", Path("/srv/eom/worker-homes") / worker),
                ("workspace", Path("/srv/eom/workspaces") / worker),
            ):
                exists = path.is_dir()
                self.report.add(
                    f"worker_{worker}_{label}",
                    CheckStatus.PASS if exists else CheckStatus.FAIL,
                    "WORKER_PATH_PRESENT" if exists else "WORKER_PATH_MISSING",
                    f"{worker} {label} exists" if exists else f"{worker} {label} is absent",
                )
            if self.privileged:
                self._worker_access(worker, "docker_socket", "/var/run/docker.sock", "-r")
                self._worker_access(worker, "nas_write", "/mnt/nas/eom", "-w")
            else:
                self.report.add(
                    f"worker_{worker}_access",
                    CheckStatus.UNKNOWN,
                    "PRIVILEGED_WORKER_PROBE_DEFERRED",
                    "Worker filesystem impersonation requires explicit privileged doctor mode",
                )

    def _worker_access(self, worker: str, label: str, path: str, test_flag: str) -> None:
        result = self.executor.run(("runuser", "-u", worker, "--", "test", test_flag, path))
        denied = result.returncode != 0
        self.report.add(
            f"worker_{worker}_{label}",
            CheckStatus.PASS if denied else CheckStatus.FAIL,
            "WORKER_ACCESS_DENIED" if denied else "WORKER_ACCESS_ALLOWED",
            f"{worker} access is denied" if denied else f"{worker} has prohibited access",
        )

    def _repository_and_ports(self) -> None:
        repository = (
            self.executor.run(
                ("git", "-C", "/home/eom/EOM", "rev-parse", "--show-toplevel")
            ).returncode
            == 0
        )
        self.report.add(
            "repository",
            CheckStatus.PASS if repository else CheckStatus.FAIL,
            "REPOSITORY_PRESENT" if repository else "REPOSITORY_MISSING",
            "EOM repository is present" if repository else "EOM repository is absent",
        )
        sockets = self.executor.run(("ss", "-lntH"))
        listeners = sockets.stdout.splitlines() if sockets.returncode == 0 else []
        port_8000 = any(":8000" in line for line in listeners)
        port_8765 = any(":8765" in line for line in listeners)
        self.report.add(
            "port_8000",
            CheckStatus.PASS if port_8000 else CheckStatus.WARN,
            "PORT_8000_LISTENING" if port_8000 else "PORT_8000_NOT_LISTENING",
            "Existing port 8000 service is listening"
            if port_8000
            else "Existing port 8000 service is not listening",
        )
        self.report.add(
            "port_8765",
            CheckStatus.WARN if port_8765 else CheckStatus.PASS,
            "PORT_8765_IN_USE" if port_8765 else "PORT_8765_AVAILABLE",
            "Port 8765 is already in use" if port_8765 else "Port 8765 is available",
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--privileged", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    report = InfrastructureDoctor(privileged=arguments.privileged).run()
    if arguments.json:
        print(report.as_json())
    else:
        for check in report.checks:
            print(check.status.value, check.code, check.detail)
        print("RESULT", report.result)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
