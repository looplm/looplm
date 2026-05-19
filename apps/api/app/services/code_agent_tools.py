"""Filesystem tools for the Code Agent, sandboxed to a repository root.

These are exposed as Pydantic AI tools so the agent can explore a codebase
without unrestricted filesystem access. Every operation resolves paths under
`RepoContext.repo_root` and refuses anything that escapes the sandbox.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai import RunContext

_READ_DEFAULT_LIMIT = 500
_READ_MAX_LIMIT = 2000
_GLOB_MAX_RESULTS = 200
_GREP_MAX_RESULTS = 200
_GREP_MAX_FILES = 2000
_BINARY_SNIFF_BYTES = 2048
_SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", "dist", "build", ".next"}


@dataclass
class RepoContext:
    """Context object passed to every tool. `repo_root` is the sandbox root."""

    repo_root: Path | None


class SandboxError(ValueError):
    """Raised when a tool call tries to escape the sandbox or is misconfigured."""


def _resolved_root(ctx: RunContext[RepoContext]) -> Path:
    root = ctx.deps.repo_root if ctx.deps else None
    if not root:
        raise SandboxError("No repository path configured for this analysis.")
    return root.resolve()


def _resolve_in_sandbox(root: Path, user_path: str) -> Path:
    """Resolve `user_path` under `root` and reject paths that escape it."""
    candidate = (root / user_path) if not Path(user_path).is_absolute() else Path(user_path)
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise SandboxError(f"Path is outside the repository sandbox: {user_path}")
    return resolved


def _looks_binary(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            chunk = fh.read(_BINARY_SNIFF_BYTES)
        return b"\x00" in chunk
    except OSError:
        return True


def _iter_repo_files(root: Path):
    """Yield files under `root`, skipping common noise directories."""
    for path in root.rglob("*"):
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_file():
            yield path


async def read_file(
    ctx: RunContext[RepoContext],
    path: str,
    offset: int = 0,
    limit: int = _READ_DEFAULT_LIMIT,
) -> str:
    """Read a text file from the repository.

    Args:
        path: Path relative to the repository root (or absolute inside it).
        offset: Zero-based line number to start at.
        limit: Maximum number of lines to return (capped at 2000).
    """
    root = _resolved_root(ctx)
    target = _resolve_in_sandbox(root, path)
    if not target.exists():
        return f"Error: file not found: {path}"
    if not target.is_file():
        return f"Error: not a file: {path}"
    if _looks_binary(target):
        return f"Error: binary file, cannot read as text: {path}"

    limit = max(1, min(limit, _READ_MAX_LIMIT))
    offset = max(0, offset)
    lines_out: list[str] = []
    with target.open("r", encoding="utf-8", errors="replace") as fh:
        for idx, line in enumerate(fh):
            if idx < offset:
                continue
            if len(lines_out) >= limit:
                lines_out.append(
                    f"... (truncated, file has more lines beyond {offset + limit})"
                )
                break
            lines_out.append(f"{idx + 1:>6}\t{line.rstrip()}")
    if not lines_out:
        return f"(empty file or offset past end: {path})"
    return "\n".join(lines_out)


async def glob_files(ctx: RunContext[RepoContext], pattern: str) -> str:
    """Find files in the repository matching a glob pattern.

    Args:
        pattern: Glob pattern, e.g. `**/*.py`, `src/**/*.ts`, `*.md`.
    """
    root = _resolved_root(ctx)
    matches: list[str] = []
    # `Path.glob` interprets `**` only when used as a path component; use rglob for
    # patterns containing `**/`.
    if pattern.startswith("**/"):
        suffix = pattern[3:]
        iterator = (p for p in root.rglob(suffix) if p.is_file())
    elif "**" in pattern:
        iterator = (p for p in root.glob(pattern) if p.is_file())
    else:
        iterator = (p for p in root.glob(pattern) if p.is_file())

    for path in iterator:
        rel = path.relative_to(root)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        matches.append(str(rel))
        if len(matches) >= _GLOB_MAX_RESULTS:
            matches.append(f"... (truncated at {_GLOB_MAX_RESULTS} matches)")
            break

    if not matches:
        return f"(no files matched: {pattern})"
    return "\n".join(matches)


async def grep_files(
    ctx: RunContext[RepoContext],
    pattern: str,
    path_glob: str | None = None,
) -> str:
    """Search file contents for a regex pattern.

    Args:
        pattern: Regular expression to search for.
        path_glob: Optional glob limiting which files to search (e.g. `**/*.py`).
                   Defaults to all text files in the repo.
    """
    root = _resolved_root(ctx)
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return f"Error: invalid regex {pattern!r}: {exc}"

    if path_glob:
        files = (p for p in root.rglob(path_glob.removeprefix("**/")) if p.is_file())
    else:
        files = _iter_repo_files(root)

    matches: list[str] = []
    files_scanned = 0
    for path in files:
        rel = path.relative_to(root)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        if path_glob and not fnmatch.fnmatch(str(rel), path_glob):
            continue
        files_scanned += 1
        if files_scanned > _GREP_MAX_FILES:
            matches.append(f"... (stopped after scanning {_GREP_MAX_FILES} files)")
            break
        if _looks_binary(path):
            continue
        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                for lineno, line in enumerate(fh, start=1):
                    if regex.search(line):
                        snippet = line.rstrip()[:240]
                        matches.append(f"{rel}:{lineno}:{snippet}")
                        if len(matches) >= _GREP_MAX_RESULTS:
                            matches.append(
                                f"... (truncated at {_GREP_MAX_RESULTS} matches)"
                            )
                            break
        except OSError:
            continue
        if len(matches) >= _GREP_MAX_RESULTS:
            break

    if not matches:
        return f"(no matches for pattern: {pattern})"
    return "\n".join(matches)
