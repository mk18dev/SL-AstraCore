"""Re-indexing must not leave the graph describing code that no longer exists.

Node deletion cascaded, but edges between two *surviving* nodes were only ever
upserted, never pruned: remove an import from a file and the graph kept reporting
that dependency indefinitely, which then skewed impact analysis and every
context pack built from it.
"""

import os

import pytest

from astra.runtime.orchestrator import RuntimeOrchestrator
from astra.storage.backend import StorageProvider


def _edges(db_path):
    storage = StorageProvider(backend="duckdb", db_path=db_path).create()
    storage.connect()
    try:
        return {
            (e.from_node.replace("\\", "/").rsplit("/", 1)[-1],
             e.to_node.replace("\\", "/").rsplit("/", 1)[-1],
             e.type.name)
            for e in storage.get_all_edges()
        }
    finally:
        storage.close()


@pytest.fixture
def indexed(tmp_path):
    (tmp_path / "a.py").write_text("from b import h\n\ndef f():\n    return h()\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def h():\n    return 1\n", encoding="utf-8")
    orch = RuntimeOrchestrator()
    orch.register_repo(str(tmp_path))
    record = orch.index_repo(str(tmp_path))
    return tmp_path, orch, record


def test_import_edge_exists_before_the_edit(indexed):
    repo, _orch, record = indexed
    assert ("a.py", "b.py", "IMPORTS") in _edges(record.db_path)


def test_removed_import_edge_is_deleted(indexed):
    repo, orch, record = indexed
    (repo / "a.py").write_text("def f():\n    return 0\n", encoding="utf-8")
    orch.index_repo(str(repo))
    assert ("a.py", "b.py", "IMPORTS") not in _edges(record.db_path), (
        "the graph still reports an import that was deleted from the source"
    )


def test_re_adding_the_import_restores_the_edge(indexed):
    repo, orch, record = indexed
    (repo / "a.py").write_text("def f():\n    return 0\n", encoding="utf-8")
    orch.index_repo(str(repo))
    assert ("a.py", "b.py", "IMPORTS") not in _edges(record.db_path)

    (repo / "a.py").write_text("from b import h\n\ndef f():\n    return h()\n", encoding="utf-8")
    orch.index_repo(str(repo))
    assert ("a.py", "b.py", "IMPORTS") in _edges(record.db_path), "re-adding an import must restore it"


def test_symbol_nodes_follow_their_source(indexed):
    """A function that moves down gets a fresh node at its new line, not a stale one."""
    repo, orch, record = indexed
    # Three comment/blank lines push `def f` from line 3 to line 6.
    (repo / "a.py").write_text("# a comment\n\n\nfrom b import h\n\ndef f():\n    return h()\n", encoding="utf-8")
    orch.index_repo(str(repo))
    symbols = {n for n in _edges(record.db_path) if "symbol:" in n[0]}
    assert ("a.py::symbol:f:6", "a.py", "BELONGS_TO") in symbols
    assert ("a.py::symbol:f:3", "a.py", "BELONGS_TO") not in symbols, (
        "the old node at the previous line number survived the edit"
    )


def test_deleting_a_file_cascades_to_its_edges(indexed):
    repo, orch, record = indexed
    (repo / "b.py").unlink()
    orch.index_repo(str(repo))
    edges = _edges(record.db_path)
    assert not any(to == "b.py" for _f, to, _t in edges), f"edges to a deleted file survived: {edges}"



def test_incremental_manifest_survives_runtime_restart(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "b.py").write_text("def helper():\n    return 2\n", encoding="utf-8")
    metadata_db = tmp_path / "state" / "runtime.db"

    first_runtime = RuntimeOrchestrator(metadata_db_path=str(metadata_db))
    first_runtime.register_repo(str(repo))
    first_record = first_runtime.index_repo(str(repo))
    assert first_record.status.value == "active"

    restarted_runtime = RuntimeOrchestrator(metadata_db_path=str(metadata_db))
    restarted_runtime.register_repo(str(repo))
    restarted_record = restarted_runtime.index_repo(str(repo))

    assert restarted_record.status.value == "active"
    assert "incremental: 0 of 2 files changed" in restarted_record.warnings


def test_incremental_hash_detects_same_size_edit_with_preserved_mtime(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "main.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    runtime = RuntimeOrchestrator(metadata_db_path=str(tmp_path / "state" / "runtime.db"))
    runtime.register_repo(str(repo))
    first_record = runtime.index_repo(str(repo))
    assert first_record.status.value == "active"

    original_stat = source.stat()
    source.write_text("VALUE = 2\n", encoding="utf-8")
    os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

    updated_record = runtime.index_repo(str(repo))
    assert updated_record.status.value == "active"
    assert "incremental: 1 of 1 files changed" in updated_record.warnings
