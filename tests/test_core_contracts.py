from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from astra.context.file_terms import _tokens, file_terms
from astra.context.graph_query import GraphQuery, _light_stem
from astra.core.lifecycle import Lifecycle, Phase
from astra.models.graph_node import GraphNode, NodeType as GraphNodeType, node_type_from_ir
from astra.models.task_analysis import TaskType
from astra.scanner.checkpoint_engine import CheckpointEngine
from astra.scanner.language_detector import LanguageDetector
from astra.context.strategy_engine import StrategyEngine


def test_language_detector_handles_case_unknown_and_supported_filter():
    detector = LanguageDetector()
    assert detector.detect("src/MAIN.PY") == "python"
    assert detector.is_source("src/MAIN.PY")
    assert detector.is_code("src/main.py")
    assert not detector.is_code("README.md")
    assert not detector.is_source("unknown.extension")
    assert detector.is_parseable("main.py")
    assert detector.is_parseable("main.py", {"python"})
    assert not detector.is_parseable("main.py", {"rust"})
    assert not detector.is_parseable("unknown.extension", {"python"})


def test_lifecycle_transitions_and_stats_are_isolated():
    lifecycle = Lifecycle()
    assert lifecycle.phase is Phase.DISCOVERY
    lifecycle.advance()
    assert lifecycle.phase is Phase.CLASSIFICATION
    lifecycle.advance("reading")
    assert lifecycle.phase is Phase.READING
    lifecycle.advance()
    assert lifecycle.phase is Phase.PARSING
    lifecycle.advance(Phase.COMPLETE.value)
    lifecycle.advance()
    assert lifecycle.phase is Phase.COMPLETE
    lifecycle.record("files_read", 3)
    lifecycle.record("not-a-counter", 50)
    stats = lifecycle.stats
    assert stats["files_read"] == 3
    assert "not-a-counter" not in stats
    stats["files_read"] = 99
    assert lifecycle.stats["files_read"] == 3
    with pytest.raises(ValueError):
        lifecycle.advance("not-a-phase")


def test_strategy_engine_has_task_specific_strategies_and_fallback():
    engine = StrategyEngine()
    cases = {
        TaskType.BUG_FIX: 25,
        TaskType.FEATURE_ADDITION: 30,
        TaskType.REFACTOR: 40,
        TaskType.DEBUG_TRACE: 35,
        TaskType.OPTIMIZATION: 20,
        TaskType.ARCHITECTURE_REVIEW: 50,
        TaskType.ANALYSIS: 35,
    }
    for task_type, expected_nodes in cases.items():
        strategy = engine.get_strategy(task_type)()
        assert strategy["max_nodes"] == expected_nodes
        assert strategy["node_priority"]
    assert engine.get_strategy("unknown")()["max_nodes"] == 35


def test_graph_node_ir_mapping_and_safe_fallback():
    assert node_type_from_ir(SimpleNamespace(name="FUNCTION")) is GraphNodeType.FUNCTION
    assert node_type_from_ir(SimpleNamespace(name="CLASS")) is GraphNodeType.CLASS
    assert node_type_from_ir(1) is GraphNodeType.FILE
    assert node_type_from_ir(12) is GraphNodeType.CONFIG
    assert node_type_from_ir(999) is GraphNodeType.FILE
    assert node_type_from_ir("unexpected") is GraphNodeType.FILE
    node = GraphNode(id="x", label="x.py")
    assert node.node_type is GraphNodeType.FILE
    assert node.properties == {}


def test_file_terms_split_identifiers_filter_stopwords_and_bound_reads(tmp_path):
    assert {"parse", "file"} <= _tokens("def parseFile(): pass")
    assert {"parse", "file"} <= _tokens("parse_file")
    assert "import" not in _tokens("import os")
    assert _tokens("a an the") == set()

    source = tmp_path / "context_selector.py"
    source.write_text("def choose_context(): pass\n" + "hiddenkeyword " * 100, encoding="utf-8")
    terms = file_terms(str(source), max_bytes=30)
    assert "context" in terms
    assert "selector" in terms
    assert "choose" in terms
    assert "hiddenkeyword" not in terms

    missing = file_terms(str(tmp_path / "does-not-exist.py"))
    assert "exist" in missing


def test_checkpoint_engine_v2_persistence_and_incremental_operations(tmp_path):
    path = tmp_path / "state" / "checkpoint.json"
    engine = CheckpointEngine(str(path), every=2)
    first = SimpleNamespace(
        rel_path="src\\main.py",
        id="file:src/main.py",
        hash_value="hash-a",
        hash_algorithm="sha256",
        size_bytes=12,
        modified_at="2026-01-01T00:00:00Z",
    )
    second = SimpleNamespace(
        rel_path="src/other.py",
        id="file:src/other.py",
        hash_value="hash-b",
        hash_algorithm="sha256",
        size_bytes=20,
        modified_at="2026-01-01T00:00:00Z",
    )
    engine.mark_file(first, 1)
    assert not path.exists()
    engine.mark_file(second, 2)
    assert path.exists()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["version"] == 2
    assert "src/main.py" in saved["files"]

    loaded = CheckpointEngine(str(path))
    state = loaded.load_state()
    assert set(state) == {"src/main.py", "src/other.py"}
    assert loaded.is_unchanged(first)
    changed = SimpleNamespace(
        rel_path="src/main.py",
        hash_value="different",
        hash_algorithm="sha256",
        size_bytes=12,
    )
    assert not loaded.is_unchanged(changed)
    assert loaded.deleted_paths(["src/main.py"]) == ["src/other.py"]
    loaded.retain_only(["src/main.py"])
    assert loaded.load() == {"src/main.py"}


def test_checkpoint_engine_reads_legacy_v1_and_normalizes_paths(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({"seen": ["src\\main.py", "README.md"]}), encoding="utf-8")
    engine = CheckpointEngine(str(path))
    assert engine.load() == {"src/main.py", "README.md"}
    assert engine.load_state()["src/main.py"] == {"rel_path": "src/main.py"}


def test_checkpoint_engine_without_path_is_a_noop():
    engine = CheckpointEngine()
    engine.mark("main.py", 1)
    engine.mark_file(SimpleNamespace(rel_path="main.py"), 1)
    engine.save()
    assert engine.load() == set()
    assert engine.deleted_paths([]) == []


def _graph_fixture(tmp_path):
    source = tmp_path / "alpha.py"
    source.write_text("resolve imports", encoding="utf-8")
    nodes = [
        GraphNode(
            id="file:alpha.py",
            label="src/alpha.py",
            node_type=GraphNodeType.FILE,
            properties={"source_terms": {"resolve", "imports"}, "file_path": str(source)},
        ),
        GraphNode(
            id="file:beta.py",
            label="src/beta.py",
            node_type=GraphNodeType.FILE,
            properties={"source_terms": {"billing"}},
        ),
        GraphNode(id="concept:auth", label="authentication", node_type=GraphNodeType.VAULT_CONCEPT),
        GraphNode(id="function:resolve", label="resolve_imports", node_type=GraphNodeType.FUNCTION),
    ]
    edges = [
        SimpleNamespace(from_node="file:alpha.py", to_node="file:beta.py", type=SimpleNamespace(value="imports")),
        SimpleNamespace(from_node="file:alpha.py", to_node="concept:auth", type=SimpleNamespace(value="related")),
        SimpleNamespace(from_node="file:beta.py", to_node="function:resolve", type=SimpleNamespace(value="calls")),
    ]
    conflicts = SimpleNamespace(conflicts=[
        SimpleNamespace(id="conflict:one", source_a="alpha.py", source_b="other.py")
    ])
    patterns = SimpleNamespace(patterns=[
        SimpleNamespace(id="pattern:one", affects=["file:alpha.py"])
    ])
    kg = SimpleNamespace(
        nodes=nodes,
        edges=edges,
        node_index={node.id: node for node in nodes},
        entry_points=["file:alpha.py"],
        conflicts=conflicts,
        patterns=patterns,
    )
    return kg


def test_graph_query_indexes_search_path_and_traversal(tmp_path):
    kg = _graph_fixture(tmp_path)
    query = GraphQuery(kg)
    assert set(query.find_by_keyword("resolve")) == {"file:alpha.py", "function:resolve"}
    assert query.find_by_path("./src/alpha.py") == ["file:alpha.py"]
    assert set(query.neighbors("file:alpha.py", max_depth=1)) == {
        "file:beta.py", "concept:auth"
    }
    assert query.downstream("file:alpha.py", max_depth=2)
    assert query.upstream("function:resolve", max_depth=2)
    assert query.get_node("file:alpha.py") is kg.nodes[0]
    assert query.find_entry_points() == ["file:alpha.py"]


def test_graph_query_related_concepts_conflicts_patterns_and_stemming(tmp_path):
    query = GraphQuery(_graph_fixture(tmp_path))
    assert query.related_vault_concepts("file:alpha.py") == ["concept:auth"]
    assert query.find_conflicts_for(["file:alpha.py"]) == ["conflict:one"]
    assert query.find_patterns_for(["file:alpha.py"]) == ["pattern:one"]
    assert _light_stem("indexing") == "index"
    assert _light_stem("running") == "run"
    assert _light_stem("categories") == "category"
    assert _light_stem("classes") == "class"
    assert _light_stem("a") == ""
