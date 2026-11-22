from __future__ import annotations

import os
import subprocess

import pytest

from astra.runtime import repo_lock


class _Completed:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_windows_process_probe_distinguishes_running_and_missing(monkeypatch):
    monkeypatch.setattr(
        repo_lock.subprocess,
        "run",
        lambda *args, **kwargs: _Completed(stdout="python.exe 1234 Console 1 10 K"),
    )
    assert repo_lock._process_exists_windows(1234)

    monkeypatch.setattr(
        repo_lock.subprocess,
        "run",
        lambda *args, **kwargs: _Completed(
            stdout="INFO: No tasks are running which match the specified criteria."
        ),
    )
    assert not repo_lock._process_exists_windows(1234)


def test_windows_process_probe_fails_safe_on_empty_or_command_error(monkeypatch):
    monkeypatch.setattr(
        repo_lock.subprocess, "run", lambda *args, **kwargs: _Completed()
    )
    assert repo_lock._process_exists_windows(1234)

    def unavailable(*args, **kwargs):
        raise OSError("tasklist unavailable")

    monkeypatch.setattr(repo_lock.subprocess, "run", unavailable)
    assert repo_lock._process_exists_windows(1234)


@pytest.mark.skipif(os.name == "nt", reason="POSIX pid probing is not used on Windows")
def test_stale_posix_lock_is_removed_before_acquiring(tmp_path, monkeypatch):
    target = tmp_path / "repo.db"
    lock_path = tmp_path / "repo.db.lock"
    lock_path.write_text("987654321", encoding="ascii")

    def process_missing(pid, signal):
        raise ProcessLookupError

    monkeypatch.setattr(repo_lock.os, "kill", process_missing)
    with repo_lock.file_lock(str(target), timeout=0.2):
        assert lock_path.exists()
    assert not lock_path.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX pid probing is not used on Windows")
def test_permission_denied_means_lock_owner_is_still_live(tmp_path, monkeypatch):
    lock_path = tmp_path / "repo.db.lock"
    lock_path.write_text("987654321", encoding="ascii")

    def permission_denied(pid, signal):
        raise PermissionError

    monkeypatch.setattr(repo_lock.os, "kill", permission_denied)
    assert not repo_lock._is_stale(lock_path)
