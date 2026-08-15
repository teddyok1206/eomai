"""Bounded, metadata-only Git context collection."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

MAX_STAT_LINES = 10
MAX_STAT_LINE_LENGTH = 300


class GitContextError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitContext:
    repository: str
    branch: str
    head_commit: str
    working_tree_clean: bool
    changed_file_count: int
    diff_stat: tuple[str, ...]


def _git(repository: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitContextError("unable to read bounded Git metadata") from exc
    return completed.stdout.strip()


def collect_git_context(repository: Path) -> GitContext:
    root = Path(_git(repository, "rev-parse", "--show-toplevel")).resolve()
    branch = _git(root, "branch", "--show-current") or "detached"
    head = _git(root, "rev-parse", "HEAD")
    status_lines = tuple(
        line
        for line in _git(root, "status", "--porcelain=v1", "--untracked-files=normal").splitlines()
        if line
    )
    unstaged = _bounded_stat(_git(root, "diff", "--stat", f"--stat-count={MAX_STAT_LINES}"))
    staged = _bounded_stat(
        _git(root, "diff", "--cached", "--stat", f"--stat-count={MAX_STAT_LINES}")
    )
    combined = tuple(dict.fromkeys((*staged, *unstaged)))[:MAX_STAT_LINES]
    return GitContext(
        repository=str(root),
        branch=branch,
        head_commit=head,
        working_tree_clean=not status_lines,
        changed_file_count=len(status_lines),
        diff_stat=combined,
    )


def _bounded_stat(value: str) -> tuple[str, ...]:
    return tuple(
        line[:MAX_STAT_LINE_LENGTH] for line in value.splitlines()[:MAX_STAT_LINES] if line
    )
