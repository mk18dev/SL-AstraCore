"""Filesystem path policy for operations scoped to a repository."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath, PureWindowsPath


class UnsafeRepositoryPath(ValueError):
    """A requested file path escapes or is ambiguous outside its repository."""


_WINDOWS_RESERVED = {
    "aux", "con", "nul", "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


def resolve_repo_file(root: str | Path, relative_path: str) -> Path:
    """Resolve a repository-relative file and reject path escape attempts.

    Both POSIX and Windows path syntax are considered regardless of the host OS.
    Resolving symlinks before the containment check prevents a link inside the
    repository from redirecting a read or write to an external file.
    """
    if not isinstance(relative_path, str):
        raise UnsafeRepositoryPath("file path must be a string")

    raw = relative_path.strip()
    if not raw:
        raise UnsafeRepositoryPath("file path cannot be empty")
    if "\x00" in raw:
        raise UnsafeRepositoryPath("file path contains a NUL byte")

    windows = PureWindowsPath(raw)
    if windows.is_absolute() or windows.drive:
        raise UnsafeRepositoryPath("absolute paths are not allowed")

    normalized = raw.replace("\\", "/")
    if normalized in {".", "./"}:
        raise UnsafeRepositoryPath("a file path must identify a file inside the repository")
    if normalized.startswith("/") or ":" in normalized:
        raise UnsafeRepositoryPath("absolute paths and alternate data streams are not allowed")

    parts = PurePosixPath(normalized).parts
    if not parts or any(part == ".." for part in parts):
        raise UnsafeRepositoryPath("parent-directory traversal is not allowed")

    for part in parts:
        if part.endswith((" ", ".")):
            raise UnsafeRepositoryPath("path components cannot end with a space or dot")
        device_name = part.split(".", 1)[0].casefold()
        if device_name in _WINDOWS_RESERVED:
            raise UnsafeRepositoryPath("reserved device names are not allowed")

    # The caller supplies the trusted repository root (registered by the
    # dashboard or selected explicitly by the local CLI). Avoid probing an
    # arbitrary caller-controlled root here; actual file reads/writes below
    # fail closed when the selected repository or file does not exist.
    repository = os.path.realpath(os.fspath(root))

    # Normalize before checking containment. Checking a separator-terminated
    # root prefix avoids accepting siblings such as /workspace/project-backup
    # when the registered root is /workspace/project.
    repository_prefix = repository if repository.endswith(os.sep) else repository + os.sep
    normalized_candidate = os.path.normpath(os.path.join(repository, normalized))
    if normalized_candidate != repository and not normalized_candidate.startswith(repository_prefix):
        raise UnsafeRepositoryPath("path resolves outside the repository")

    # Resolve symlinks after lexical normalization, then repeat the boundary
    # check so an in-repository link cannot redirect the operation elsewhere.
    candidate = os.path.realpath(normalized_candidate)
    if candidate != repository and not candidate.startswith(repository_prefix):
        raise UnsafeRepositoryPath("path resolves outside the repository")

    if candidate == repository:
        raise UnsafeRepositoryPath("a file path must identify a file inside the repository")

    return Path(candidate)
