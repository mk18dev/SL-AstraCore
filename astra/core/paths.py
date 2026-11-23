"""Filesystem path policy for operations scoped to a repository."""

from __future__ import annotations

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

    repository = Path(root).resolve()
    if not repository.is_dir():
        raise UnsafeRepositoryPath("repository root is not an existing directory")

    candidate = repository.joinpath(*parts).resolve()
    try:
        candidate.relative_to(repository)
    except ValueError:
        raise UnsafeRepositoryPath("path resolves outside the repository") from None

    if candidate == repository:
        raise UnsafeRepositoryPath("a file path must identify a file inside the repository")

    return candidate
