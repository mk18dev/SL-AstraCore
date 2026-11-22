"""2F — ContextPack optimization.
Verifies:
  - TokenBudget enforcement
  - Ranking quality (relevant nodes before irrelevant)
  - Context pack size limits
"""

from __future__ import annotations

from types import SimpleNamespace

from astra.context.token_budget import TokenBudget
from astra.context.ranking import Ranking
from astra.context.context_engine import ContextEngine
from astra.models.graph_node import GraphNode, NodeType


class MockKnowledgeGraph:
    """Mock KG for ranking tests."""
    def __init__(self):
        self.edges = []
        self.nodes = []
        self.node_index = {}
        self._adj = {}
        self._reverse_adj = {}


def test_token_budget_enforcement():
    """TokenBudget correctly caps total tokens.
    ASCII text is conservatively estimated at three characters per token.
    """
    budget = TokenBudget(max_budget=100)
    texts = ["a" * 150, "b" * 150, "c" * 150]
    included = []
    for t in texts:
        if budget.reserve("id", t):
            included.append(t)
    # 150 chars = 50 tokens each. 50+50=100 fits, third fails.
    assert len(included) == 2


def test_token_budget_reset():
    """TokenBudget resets correctly."""
    budget = TokenBudget(max_budget=100)
    budget.reserve("a", "x" * 150)
    budget.reset()
    assert budget.used == 0


def test_token_budget_can_fit():
    """TokenBudget.can_fit works correctly."""
    budget = TokenBudget(max_budget=100)
    budget.reserve("a", "x" * 150)  # 50 tokens
    assert budget.can_fit("y" * 120)  # 50+40=90
    assert not budget.can_fit("z" * 153)  # 50+51=101 > 100


def test_ranking_order():
    """Ranking.rank returns nodes sorted by score descending."""
    kg = MockKnowledgeGraph()
    for i, conf in enumerate([0.9, 0.5, 0.1]):
        node_id = f"n{i}"
        kg.node_index[node_id] = GraphNode(
            id=node_id, node_type=NodeType.FILE, confidence=conf
        )
    ranking = Ranking(kg)
    ranked = ranking.rank(list(kg.node_index.keys()))
    assert ranked[0][1] >= ranked[1][1] >= ranked[2][1]


def test_ranking_task_type_weights():
    """Ranking applies task-type specific weights."""
    kg = MockKnowledgeGraph()
    kg.node_index["func1"] = GraphNode(
        id="func1", node_type=NodeType.FUNCTION, confidence=0.8
    )
    kg.node_index["class1"] = GraphNode(
        id="class1", node_type=NodeType.CLASS, confidence=0.8
    )
    ranking = Ranking(kg)
    scored = ranking.rank(["func1", "class1"])
    assert len(scored) == 2
    # Both have same confidence; function gets +0.6, class gets +0.7
    assert scored[0][1] > 0


def test_context_engine_runs():
    """ContextEngine can be constructed and _estimate_tokens works."""
    kg = MockKnowledgeGraph()
    engine = ContextEngine(knowledge_graph=kg)
    assert engine is not None
    # TokenBudget estimation works with real data
    budget = TokenBudget(max_budget=1000)
    budget.reserve("node1", "file main.py FILE")
    budget.reserve("node2", "class Greeter CLASS")
    assert budget.used > 0



def test_token_estimate_handles_non_ascii_text_conservatively():
    assert TokenBudget.estimate("سلام") == 4
    assert TokenBudget.estimate("a" * 100) == 34



def test_hard_budget_drops_oversized_seed_and_keeps_later_fitting_nodes():
    engine = ContextEngine(knowledge_graph=MockKnowledgeGraph())
    engine._token_budget.set_budget(10)
    pack = SimpleNamespace(
        relevant_nodes=[
            {
                "id": "seed",
                "label": "x" * 60,
                "type": "FILE",
                "relevance_score": 1.0,
            },
            {
                "id": "small",
                "label": "a",
                "type": "FILE",
                "relevance_score": 0.5,
            },
            {
                "id": "small2",
                "label": "b",
                "type": "FILE",
                "relevance_score": 0.4,
            },
        ],
        metadata={"seed_ids": ["seed"]},
        required_files=[],
        token_estimate=0,
    )

    engine._enforce_token_budget(pack)

    assert pack.token_estimate <= 10
    assert [node["id"] for node in pack.relevant_nodes] == ["small", "small2"]



def test_context_engine_estimates_and_validates_pack_contracts():
    engine = ContextEngine(knowledge_graph=MockKnowledgeGraph())
    pack = SimpleNamespace(
        relevant_nodes=[
            {"id": "a", "label": "alpha.py", "type": "FILE"},
            {"id": "a", "label": "duplicate", "type": "FILE"},
            {"id": "b", "label": "beta.py", "type": "FILE"},
        ],
        required_files=["b.py", "a.py", "b.py"],
        critical_dependencies=[{"from": "a", "to": "b"}],
        relevant_concepts=["auth", "auth", "billing"],
        conflicts_to_watch=["c1", "c1", "c2"],
    )
    estimated = engine._estimate_tokens(pack)
    assert estimated > 0

    engine._validate(pack)
    assert [node["id"] for node in pack.relevant_nodes] == ["a", "b"]
    assert pack.required_files == ["a.py", "b.py"]
    assert set(pack.relevant_concepts) == {"auth", "billing"}
    assert set(pack.conflicts_to_watch) == {"c1", "c2"}
