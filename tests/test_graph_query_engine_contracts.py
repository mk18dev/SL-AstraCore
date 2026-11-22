from __future__ import annotations

from astra.graph.query_engine import GraphQueryEngine
from astra.ir.models import EdgeType, IREdge, IRNode, NodeType


class MemoryGraphStorage:
    def __init__(self):
        self.nodes = {
            "file:a.py": IRNode(
                id="file:a.py", type=NodeType.FILE, name="a.py", source="parser",
                metadata={"language": "python"},
            ),
            "file:b.py": IRNode(
                id="file:b.py", type=NodeType.FILE, name="b.py", source="parser",
                metadata={"language": "python"},
            ),
            "symbol:run": IRNode(
                id="symbol:run", type=NodeType.FUNCTION, name="run", source="parser",
                metadata={"language": "python"},
            ),
            "file:orphan.rs": IRNode(
                id="file:orphan.rs", type=NodeType.FILE, name="orphan.rs", source="parser",
                metadata={"language": "rust"},
            ),
        }
        self.edges = [
            IREdge(from_node="file:a.py", to_node="file:b.py", type=EdgeType.IMPORTS),
            IREdge(from_node="file:b.py", to_node="symbol:run", type=EdgeType.IMPORTS),
            IREdge(from_node="symbol:run", to_node="file:a.py", type=EdgeType.BELONGS_TO),
        ]

    def get_node(self, node_id):
        return self.nodes.get(node_id)

    def search_nodes_by_name(self, name):
        return [node for node in self.nodes.values() if name.lower() in node.name.lower()]

    def get_nodes_by_type(self, node_type):
        return [node for node in self.nodes.values() if node.type == node_type]

    def get_nodes_by_source(self, source):
        return [node for node in self.nodes.values() if node.source == source]

    def get_edges(self, from_node=None, to_node=None, edge_type=None):
        return [
            edge for edge in self.edges
            if (from_node is None or edge.from_node == from_node)
            and (to_node is None or edge.to_node == to_node)
            and (edge_type is None or edge.type == edge_type)
        ]

    def get_all_nodes(self):
        return list(self.nodes.values())

    def get_all_edges(self):
        return list(self.edges)

    def node_count(self):
        return len(self.nodes)

    def edge_count(self):
        return len(self.edges)


def test_graph_query_engine_file_symbol_and_dependency_queries():
    storage = MemoryGraphStorage()
    engine = GraphQueryEngine(storage)
    assert engine.find_file("a.py") is storage.nodes["file:a.py"]
    assert engine.find_named_symbol("run").count == 1
    assert engine.find_named_symbol("run", NodeType.FILE).count == 0
    assert engine.find_by_type(NodeType.FILE).count == 3
    assert engine.find_by_source("parser").count == 4
    assert {node.id for node in engine.find_dependents("file:b.py").nodes} == {"file:a.py"}
    assert {node.id for node in engine.find_imports("file:a.py").nodes} == {"file:b.py"}
    assert engine.find_all_edges_for("file:b.py").count == 2


def test_graph_query_engine_bfs_paths_and_induced_subgraph():
    storage = MemoryGraphStorage()
    engine = GraphQueryEngine(storage)
    bfs = engine.bfs("file:a.py", max_depth=2)
    assert {node.id for node in bfs.nodes} == {
        "file:a.py", "file:b.py", "symbol:run"
    }
    assert engine.shortest_path("file:a.py", "file:a.py") == ["file:a.py"]
    assert engine.shortest_path("file:a.py", "symbol:run") == [
        "file:a.py", "file:b.py", "symbol:run"
    ]
    assert engine.shortest_path("file:a.py", "file:orphan.rs") is None

    subgraph = engine.extract_subgraph(["file:a.py", "file:b.py"])
    assert {node.id for node in subgraph.nodes} == {"file:a.py", "file:b.py"}
    assert subgraph.count == 2
    assert len(subgraph.edges) == 1


def test_graph_query_engine_impact_and_aggregations():
    storage = MemoryGraphStorage()
    engine = GraphQueryEngine(storage)
    impact = engine.impact_analysis("file:a.py", depth=2)
    assert {node.id for node in impact.nodes} == {"symbol:run", "file:b.py"}
    assert impact.count == 2
    assert engine.node_count() == 4
    assert engine.edge_count() == 3
    assert engine.edge_type_summary() == {"IMPORTS": 2, "BELONGS_TO": 1}
    assert engine.language_summary() == {"python": 3, "rust": 1}
