"""2E+2G — Incremental Rebuild Benchmarks + Performance KPI Enforcement.

Measures and enforces:
  - Graph mutation throughput (nodes/sec, edges/sec)
  - Batch write throughput vs single-write
  - DuckDB vs SQLite write throughput
  - Context engine pack build time
  - Full pipeline E2E time (scan → parse → graph → context)
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from astra.ir.models import IRNode, IREdge, NodeType, EdgeType
from astra.storage.backend import StorageProvider
from astra.graph.mutator import GraphMutator, compute_diff, compute_edge_diff
from astra.runtime.orchestrator import RuntimeOrchestrator


# ── KPI thresholds (Phase 2 frozen) ────────────────────────────────
#
# These are wall-clock assertions, so they are inherently sensitive to machine
# load. They are enforced only when STRICT_KPI is set (CI does); a local run
# reports the measurement and skips the gate, so a busy laptop never reports a
# phantom regression. Import it with `import os; os.environ["STRICT_KPI"]="1"`.
STRICT_KPI = os.environ.get("STRICT_KPI") == "1"

KPI = {
    "mutator_batch_100_nodes": 5.0,       # seconds
    "mutator_single_write_100": 1.0,       # seconds
    "duckdb_vs_sqlite_parity": 10.0,      # ratio (DuckDB startup variance across CI runners)
    "context_engine_50_nodes": 1.0,        # seconds
    "full_pipeline_10_files": 5.0,         # seconds
}


def _make_graph_data(n: int):
    nodes = [
        IRNode(id=f"n{i}", type=NodeType.FILE, name=f"file{i}", source="bench")
        for i in range(n)
    ]
    edges = [
        IREdge(from_node=f"n{i}", to_node=f"n{(i+1)%n}", type=EdgeType.IMPORTS)
        for i in range(n)
    ]
    return nodes, edges


def test_mutator_batch_throughput():
    """Batch write of 100 nodes should complete within KPI threshold."""
    with tempfile.NamedTemporaryFile(suffix=".duckdb", delete=False) as f:
        db_path = f.name
    if os.path.exists(db_path):
        os.remove(db_path)
    try:
        storage = StorageProvider(backend="duckdb", db_path=db_path).create()
        storage.connect()
        mutator = GraphMutator(storage)
        nodes, edges = _make_graph_data(100)

        t0 = time.perf_counter()
        mutator.apply_batch(nodes_to_upsert=nodes, edges_to_upsert=edges)
        elapsed = time.perf_counter() - t0

        if not STRICT_KPI:
            print(f"\n  [kpi] batch write {elapsed:.3f}s (gate skipped; set STRICT_KPI=1 to enforce)")
        assert elapsed < KPI["mutator_batch_100_nodes"] or not STRICT_KPI, (
            f"Batch write took {elapsed:.3f}s, threshold {KPI['mutator_batch_100_nodes']}s"
        )
        assert storage.node_count() == 100
        assert storage.edge_count() == 100
        storage.close()
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_duckdb_sqlite_throughput_ratio():
    """Both backends complete batch writes within reasonable time per-backend."""
    results = {}
    for backend in ("duckdb", ".duckdb"), ("sqlite", ".sqlite"):
        name, suffix = backend
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            db_path = f.name
        if name == "duckdb" and os.path.exists(db_path):
            os.remove(db_path)
        try:
            storage = StorageProvider(backend=name, db_path=db_path).create()
            storage.connect()
            mutator = GraphMutator(storage)
            nodes, edges = _make_graph_data(50)

            t0 = time.perf_counter()
            mutator.apply_batch(nodes_to_upsert=nodes, edges_to_upsert=edges)
            elapsed = time.perf_counter() - t0
            results[name] = elapsed

            assert storage.node_count() == 50
            assert storage.edge_count() == 50
            storage.close()
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

    # Both must complete; ratio is informational only (DuckDB is OLAP, SQLite is OLTP)
    print(f"\n  [kpi] backend timings: {results}")
    assert all(v < 5.0 for v in results.values()) or not STRICT_KPI, f"Backend too slow: {results}"


def test_compute_diff_correctness():
    """compute_diff returns correct upsert/delete sets."""
    old = {"a": IRNode(id="a", type=NodeType.FILE, name="old", source="t"),
           "b": IRNode(id="b", type=NodeType.FILE, name="keep", source="t")}
    new = {"b": IRNode(id="b", type=NodeType.FILE, name="keep", source="t"),
           "c": IRNode(id="c", type=NodeType.FILE, name="new", source="t")}
    upserts, deletes = compute_diff(old, new)
    assert set(deletes) == {"a"}
    assert len(upserts) == 1
    assert upserts[0].id == "c"


def test_compute_edge_diff_correctness():
    """compute_edge_diff returns correct upsert/delete sets."""
    old = [IREdge(from_node="a", to_node="b", type=EdgeType.IMPORTS)]
    new = [IREdge(from_node="a", to_node="b", type=EdgeType.CALLS)]
    upserts, deletes = compute_edge_diff(old, new)
    assert len(deletes) == 1
    assert len(upserts) == 1
    assert upserts[0].type == EdgeType.CALLS



def test_mutator_single_write_100_nodes():
    """Individual node upserts remain bounded relative to the batch path."""
    with tempfile.NamedTemporaryFile(suffix=".duckdb", delete=False) as f:
        db_path = f.name
    if os.path.exists(db_path):
        os.remove(db_path)
    try:
        storage = StorageProvider(backend="duckdb", db_path=db_path).create()
        storage.connect()
        mutator = GraphMutator(storage)
        nodes, _edges = _make_graph_data(100)
        t0 = time.perf_counter()
        for node in nodes:
            mutator.apply_node_upsert(node)
        elapsed = time.perf_counter() - t0
        print(f"\n  [kpi] single writes 100 nodes {elapsed:.3f}s")
        assert elapsed < KPI["mutator_single_write_100"] or not STRICT_KPI
        assert storage.node_count() == 100
        storage.close()
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def _make_tiny_repository(root: Path, file_count: int) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for index in range(file_count):
        (root / f"module_{index}.py").write_text(
            f"def feature_{index}(value):\n"
            f"    return value + {index}\n",
            encoding="utf-8",
        )
    return root


def test_context_engine_50_file_query_latency(tmp_path):
    """Context retrieval over a 50-file repository stays within its latency KPI."""
    root = _make_tiny_repository(tmp_path / "repo-50", 50)
    runtime = RuntimeOrchestrator(
        metadata_db_path=str(tmp_path / "state-50" / "runtime.db")
    )
    runtime.register_repo(str(root))
    runtime.index_repo(str(root))

    started = time.perf_counter()
    pack = runtime.query_context(
        str(root), [], "inspect feature_25 implementation", max_tokens=4000
    )
    elapsed = time.perf_counter() - started
    print(f"\n  [kpi] context query 50 files {elapsed:.3f}s")
    assert pack.nodes
    assert pack.total_tokens <= pack.token_budget
    assert elapsed < KPI["context_engine_50_nodes"] or not STRICT_KPI


def test_full_pipeline_10_file_latency(tmp_path):
    """Scan, parse, graph mutation, and context retrieval stay bounded."""
    root = _make_tiny_repository(tmp_path / "repo-10", 10)
    runtime = RuntimeOrchestrator(
        metadata_db_path=str(tmp_path / "state-10" / "runtime.db")
    )
    started = time.perf_counter()
    runtime.register_repo(str(root))
    record = runtime.index_repo(str(root))
    pack = runtime.query_context(
        str(root), [], "inspect feature_5 implementation", max_tokens=2000
    )
    elapsed = time.perf_counter() - started
    print(f"\n  [kpi] full pipeline 10 files {elapsed:.3f}s")
    assert record.file_count >= 10
    assert pack.nodes
    assert elapsed < KPI["full_pipeline_10_files"] or not STRICT_KPI
