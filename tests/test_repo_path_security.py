"""Repository path confinement, including foreign-platform path syntax."""

import pytest

from astra.core.paths import UnsafeRepositoryPath, resolve_repo_file


@pytest.mark.parametrize(
    "candidate",
    [
        "../outside.py",
        "subdir/../../outside.py",
        "/tmp/outside.py",
        r"..\outside.py",
        r"C:\outside.py",
        r"\\server\share\outside.py",
        "NUL",
        "folder/file.txt:stream",
    ],
)
def test_unsafe_paths_are_rejected(tmp_path, candidate):
    with pytest.raises(UnsafeRepositoryPath):
        resolve_repo_file(tmp_path, candidate)


def test_normal_repository_relative_path_is_resolved(tmp_path):
    target = tmp_path / "astra" / "agent.py"
    target.parent.mkdir()
    target.write_text("value = 1\n", encoding="utf-8")

    assert resolve_repo_file(tmp_path, "astra/agent.py") == target.resolve()


def test_backslash_separators_are_normalized(tmp_path):
    target = tmp_path / "astra" / "agent.py"
    target.parent.mkdir()
    target.write_text("value = 1\n", encoding="utf-8")

    assert resolve_repo_file(tmp_path, r"astra\agent.py") == target.resolve()


def test_symlink_cannot_escape_repository(tmp_path):
    repository = tmp_path / "repo"
    repository.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("SECRET = True\n", encoding="utf-8")
    link = repository / "linked.py"
    try:
        link.symlink_to(outside)
    except (NotImplementedError, OSError):
        pytest.skip("symlink creation is unavailable on this runner")

    with pytest.raises(UnsafeRepositoryPath, match="outside the repository"):
        resolve_repo_file(repository, "linked.py")


def test_path_must_name_a_file_inside_an_existing_repository(tmp_path):
    repository = tmp_path / "missing"
    with pytest.raises(UnsafeRepositoryPath, match="existing directory"):
        resolve_repo_file(repository, "file.py")

    repository.mkdir()
    with pytest.raises(UnsafeRepositoryPath, match="identify a file"):
        resolve_repo_file(repository, ".")
