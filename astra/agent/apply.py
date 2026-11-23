"""Apply reviewed edits with repository confinement and rollback on failure."""

from __future__ import annotations

import contextlib
import hashlib
import os
import stat
import tempfile
from pathlib import Path

from astra.agent.loop import EditReview, ProposedEdit
from astra.core.paths import UnsafeRepositoryPath, resolve_repo_file


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class ApplyError(RuntimeError):
    """The edit is unsafe, stale, invalid, or could not be committed."""


def _read_source(path: Path) -> str:
    from astra.patch.analyzer import read_source

    return read_source(str(path))


def _write_temp_file(target: Path, content: str, mode: int, purpose: str) -> Path:
    fd, temporary = tempfile.mkstemp(
        prefix=f".astra-{purpose}-",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        # Keep staged source/backup copies private. Existing group/world
        # permissions are deliberately not propagated to temporary files.
        os.chmod(temporary, stat.S_IMODE(mode) & 0o700)
        return Path(temporary)
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(fd)
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def _atomic_replace(
    target: Path,
    content: str,
    *,
    expected_fingerprint: str | None = None,
) -> None:
    mode = stat.S_IMODE(target.stat().st_mode)
    staged = _write_temp_file(target, content, mode, "stage")
    try:
        if expected_fingerprint is not None:
            current = _read_source(target)
            if _fingerprint(current) != expected_fingerprint:
                raise ApplyError(
                    f"{target.name}: the file changed before the write; review it again"
                )
        os.replace(staged, target)
    finally:
        with contextlib.suppress(OSError):
            staged.unlink()


def apply_edit(
    edit: ProposedEdit,
    root: str,
    *,
    expected_fingerprint: str | None = None,
) -> str:
    """Atomically write one reviewed edit, refusing unsafe or stale paths."""
    try:
        path = resolve_repo_file(root, edit.path)
    except UnsafeRepositoryPath as exc:
        raise ApplyError(f"{edit.path}: unsafe repository path ({exc})") from exc

    try:
        source = _read_source(path)
    except OSError as exc:
        raise ApplyError(f"{edit.path}: could not be read ({exc})") from exc

    if expected_fingerprint and _fingerprint(source) != expected_fingerprint:
        raise ApplyError(
            f"{edit.path}: the file changed since it was reviewed; review it again"
        )

    updated = edit.apply_to(source)
    if updated == source:
        raise ApplyError(f"{edit.path}: the edit changes nothing")

    try:
        _atomic_replace(
            path,
            updated,
            expected_fingerprint=expected_fingerprint or _fingerprint(source),
        )
    except ApplyError:
        raise
    except OSError as exc:
        raise ApplyError(f"{edit.path}: could not be written ({exc})") from exc

    return _fingerprint(updated)


def apply_review(
    reviewed: EditReview,
    root: str,
    *,
    fingerprints: dict[str, str] | None = None,
) -> list[str]:
    """Preflight all edits, stage replacements, and roll back on rename failure.

    Files are replaced atomically one by one. If a later replacement fails,
    already replaced files are restored from staged backups. This handles
    ordinary partial-apply failures; a process or machine crash during the
    rename sequence cannot provide a true cross-file filesystem transaction.
    """
    if not reviewed.applies_cleanly:
        raise ApplyError(f"the review was not clean: {reviewed.warnings}")

    prepared: dict[str, dict] = {}
    applied_paths: list[str] = []

    # Preflight every edit before creating or replacing any target.
    for edit in reviewed.edits:
        try:
            target = resolve_repo_file(root, edit.path)
        except UnsafeRepositoryPath as exc:
            raise ApplyError(f"{edit.path}: unsafe repository path ({exc})") from exc

        key = os.path.normcase(os.path.abspath(target))
        item = prepared.get(key)
        if item is None:
            try:
                original = _read_source(target)
                mode = stat.S_IMODE(target.stat().st_mode)
            except OSError as exc:
                raise ApplyError(f"{edit.path}: could not be read ({exc})") from exc
            item = {
                "target": target,
                "original": original,
                "updated": original,
                "mode": mode,
                "stage": None,
                "backup": None,
            }
            prepared[key] = item

        if fingerprints is not None:
            if edit.path not in fingerprints:
                raise ApplyError(f"{edit.path}: proposal is missing its review fingerprint")
            if _fingerprint(item["original"]) != fingerprints[edit.path]:
                raise ApplyError(
                    f"{edit.path}: the file changed since it was reviewed; review it again"
                )

        updated = edit.apply_to(item["updated"])
        if updated == item["updated"]:
            raise ApplyError(f"{edit.path}: the edit changes nothing")
        item["updated"] = updated
        applied_paths.append(edit.path)

    if not prepared:
        return []

    # Prepare every replacement and rollback copy before the first write.
    try:
        for item in prepared.values():
            target = item["target"]
            item["stage"] = _write_temp_file(
                target, item["updated"], item["mode"], "stage"
            )
            item["backup"] = _write_temp_file(
                target, item["original"], item["mode"], "backup"
            )
    except OSError as exc:
        for item in prepared.values():
            for key in ("stage", "backup"):
                temporary = item[key]
                if temporary is not None:
                    with contextlib.suppress(OSError):
                        temporary.unlink()
        raise ApplyError(f"could not stage the reviewed changes ({exc})") from exc

    committed: list[dict] = []
    preserved_backups: set[Path] = set()
    try:
        for item in prepared.values():
            target = item["target"]
            if _fingerprint(_read_source(target)) != _fingerprint(item["original"]):
                raise ApplyError(
                    f"{target.name}: the file changed during apply; no further edits were written"
                )
            os.replace(item["stage"], target)
            item["stage"] = None
            committed.append(item)
    except (OSError, ApplyError) as exc:
        rollback_errors: list[str] = []
        for item in reversed(committed):
            backup = item["backup"]
            try:
                os.replace(backup, item["target"])
                item["backup"] = None
            except OSError as rollback_exc:
                preserved_backups.add(backup)
                rollback_errors.append(
                    f"{item['target'].name}: {rollback_exc} (backup preserved at {backup})"
                )

        if rollback_errors:
            raise ApplyError(
                f"apply failed ({exc}); rollback was incomplete: {'; '.join(rollback_errors)}"
            ) from exc
        if isinstance(exc, ApplyError):
            raise
        raise ApplyError(f"apply failed and earlier files were restored ({exc})") from exc
    finally:
        for item in prepared.values():
            for key in ("stage", "backup"):
                temporary = item[key]
                if temporary is None or temporary in preserved_backups:
                    continue
                with contextlib.suppress(OSError):
                    temporary.unlink()

    return applied_paths


def fingerprint_files(reviewed: EditReview, root: str) -> dict[str, str]:
    """Capture source fingerprints for a review, keyed by its original paths."""
    out: dict[str, str] = {}
    for edit in reviewed.edits:
        try:
            path = resolve_repo_file(root, edit.path)
            out[edit.path] = _fingerprint(_read_source(path))
        except (OSError, UnsafeRepositoryPath):
            continue
    return out


if __name__ == "__main__":
    import shutil
    import tempfile

    directory = tempfile.mkdtemp()
    target = Path(directory, "billing.py")
    target.write_text("def charge(a):\n    return a - 1\n", encoding="utf-8")
    edit = ProposedEdit(
        path="billing.py", old_text="return a - 1", new_text="return a", reason="off by one"
    )
    reviewed = EditReview(edits=(edit,), diffs=())
    assert apply_review(reviewed, directory) == ["billing.py"]
    assert "return a" in target.read_text(encoding="utf-8")
    try:
        apply_review(reviewed, directory)
        raise AssertionError("re-applying should have failed")
    except ApplyError:
        pass
    shutil.rmtree(directory, ignore_errors=True)
    print("ok")
