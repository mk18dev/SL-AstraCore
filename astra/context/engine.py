"""Seeded, source-grounded context retrieval with a strict token budget."""

from __future__ import annotations

import re
from collections import deque
from pathlib import Path
from typing import Any

from astra.context.token_budget import MAX_BUDGET, TokenBudget
from astra.ir.models import (
    ContextEdgeRef,
    ContextNodeRef,
    IRContextPack,
    NodeType,
)


class ContextEngine:
    """Build a bounded, ranked context pack around explicit graph seed nodes."""

    _MAX_DEPTH = 2
    _MAX_NODES = 60
    _MAX_SNIPPET_LINES = 80

    def __init__(self, storage, repo_root: str | None = None):
        self.storage = storage
        self.repo_root = Path(repo_root).resolve() if repo_root else None

    @staticmethod
    def _truncate_to_tokens(text: str, token_limit: int) -> str:
        if token_limit <= 0:
            return ""
        if TokenBudget.estimate(text) <= token_limit:
            return text
        low, high = 0, len(text)
        while low < high:
            middle = (low + high + 1) // 2
            if TokenBudget.estimate(text[:middle]) <= token_limit:
                low = middle
            else:
                high = middle - 1
        return text[:low].rstrip()

    @staticmethod
    def _node_file_path(node: Any, node_id: str) -> str:
        metadata = getattr(node, "metadata", None) or {}
        path = getattr(node, "file_path", "") or metadata.get("file_path", "")
        if not path and node_id.startswith("file:"):
            path = node_id.removeprefix("file:")
        return str(path) if path else ""

    def _source_excerpt(
        self,
        node: Any,
        node_id: str,
        file_path: str,
        token_limit: int,
    ) -> str:
        if not file_path or token_limit <= 0:
            return ""
        source_file = Path(file_path)
        if not source_file.is_absolute() and self.repo_root:
            source_file = self.repo_root / source_file
        try:
            source_file = source_file.resolve()
            if self.repo_root is not None:
                source_file.relative_to(self.repo_root)
            lines = source_file.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
        except (OSError, ValueError):
            return ""
        if not lines:
            return ""

        metadata = getattr(node, "metadata", None) or {}
        start_line = int(metadata.get("line_start") or 0)
        if start_line > 0:
            end_line = min(
                int(metadata.get("line_end") or start_line),
                start_line + self._MAX_SNIPPET_LINES - 1,
            )
            body = lines[start_line - 1:end_line]
            header = (
                f"# {getattr(node, 'name', node_id)} — "
                f"{source_file.name}:{start_line}-{end_line}"
            )
            excerpt = "\n".join([header, *body])
        else:
            excerpt = "\n".join(lines[:self._MAX_SNIPPET_LINES])
        return self._truncate_to_tokens(excerpt, token_limit)

    @staticmethod
    def _edge_key(edge) -> tuple[str, str, str]:
        edge_type = getattr(edge.type, "name", str(edge.type))
        return edge.from_node, edge.to_node, edge_type

    def generate_context_pack(
        self,
        query_intent: str,
        seed_nodes: list[str],
        max_tokens: int | None = None,
    ) -> IRContextPack:
        """Expand seeds by at most two graph hops and rank within a hard budget."""
        effective_budget = (
            max_tokens if max_tokens and max_tokens > 0 else MAX_BUDGET
        )
        budget = TokenBudget(max_budget=effective_budget)
        seed_ids = list(dict.fromkeys(seed_nodes))
        queue = deque((node_id, 0) for node_id in seed_ids)
        discovered: dict[str, tuple[Any, int]] = {}
        edges: dict[tuple[str, str, str], Any] = {}

        while queue and len(discovered) < self._MAX_NODES:
            node_id, depth = queue.popleft()
            if node_id in discovered:
                continue
            node = self.storage.get_node(node_id)
            if node is None:
                continue
            discovered[node_id] = (node, depth)

            adjacent = (
                list(self.storage.get_edges(from_node=node_id))
                + list(self.storage.get_edges(to_node=node_id))
            )
            for edge in adjacent:
                edges[self._edge_key(edge)] = edge
                if depth >= self._MAX_DEPTH:
                    continue
                neighbor = (
                    edge.to_node if edge.from_node == node_id else edge.from_node
                )
                if neighbor not in discovered:
                    queue.append((neighbor, depth + 1))

        query_terms = set(re.findall(r"\w+", query_intent.casefold()))
        candidates = []
        seed_set = set(seed_ids)
        for node_id, (node, depth) in discovered.items():
            name = str(getattr(node, "name", "") or node_id)
            file_path = self._node_file_path(node, node_id)
            metadata = getattr(node, "metadata", None) or {}
            lexical_text = " ".join(
                [name, file_path, str(metadata.get("kind", ""))]
            ).casefold()
            node_terms = set(re.findall(r"\w+", lexical_text))
            lexical_score = (
                len(query_terms & node_terms) / len(query_terms)
                if query_terms else 0.0
            )
            distance_score = 1.0 if depth == 0 else 0.72 / depth
            type_name = getattr(getattr(node, "type", None), "name", "")
            type_bonus = 0.06 if type_name in {"FUNCTION", "CLASS", "METHOD"} else 0.0
            score = min(
                1.0,
                distance_score * 0.7 + lexical_score * 0.25 + type_bonus,
            )
            if node_id in seed_set:
                score = max(score, 1.0)
            candidates.append((node_id, node, depth, file_path, score))

        candidates.sort(
            key=lambda item: (item[0] not in seed_set, -item[4], item[0])
        )

        node_refs: list[ContextNodeRef] = []
        selected_ids: set[str] = set()
        file_paths: list[str] = []
        scores: list[float] = []
        for node_id, node, _depth, file_path, score in candidates:
            node_type = getattr(node, "type", NodeType.FILE)
            name = str(getattr(node, "name", "") or node_id)
            base_text = f"{node_id} {name} {getattr(node_type, 'name', node_type)} {file_path}"
            if not budget.can_fit(base_text):
                continue
            budget.reserve(node_id, base_text)

            snippet_limit = min(budget.remaining, 600)
            snippet = self._source_excerpt(
                node, node_id, file_path, snippet_limit
            )
            if snippet and budget.can_fit(snippet):
                budget.reserve(f"{node_id}:snippet", snippet)
            else:
                snippet = ""

            node_refs.append(
                ContextNodeRef(
                    node_id=node_id,
                    node_type=node_type,
                    name=name,
                    file_path=file_path,
                    snippet=snippet,
                    relevance_score=score,
                )
            )
            selected_ids.add(node_id)
            scores.append(score)
            if file_path and file_path not in file_paths:
                file_paths.append(file_path)

        edge_refs: list[ContextEdgeRef] = []
        dependency_summary: list[str] = []
        for key, edge in edges.items():
            if edge.from_node not in selected_ids or edge.to_node not in selected_ids:
                continue
            edge_type = edge.type
            edge_text = f"{edge.from_node} {edge.to_node} {getattr(edge_type, 'name', edge_type)}"
            if not budget.can_fit(edge_text):
                continue
            budget.reserve(f"edge:{key}", edge_text)
            edge_refs.append(
                ContextEdgeRef(
                    from_node=edge.from_node,
                    to_node=edge.to_node,
                    edge_type=edge_type,
                )
            )
            if getattr(edge_type, "name", str(edge_type)) in {
                "IMPORTS", "CALLS", "DEPENDS_ON"
            }:
                dependency_summary.append(
                    f"{edge.from_node} -> {edge.to_node} ({getattr(edge_type, 'name', edge_type)})"
                )

        included_seeds = len(seed_set & selected_ids)
        seed_coverage = included_seeds / max(1, len(seed_set))
        mean_score = sum(scores) / len(scores) if scores else 0.0
        confidence = (
            min(0.98, 0.35 + 0.4 * seed_coverage + 0.25 * mean_score)
            if node_refs else 0.0
        )

        return IRContextPack(
            task_summary=(
                f"Seeded repository context: {query_intent}"
                if query_intent else "Seeded repository context"
            ),
            task_type="seeded-retrieval",
            query_intent=query_intent,
            nodes=tuple(node_refs),
            edges=tuple(edge_refs),
            required_files=tuple(file_paths),
            dependency_summary=tuple(dependency_summary),
            hidden_risks=(),
            total_tokens=budget.used,
            token_budget=effective_budget,
            confidence=confidence,
            metadata={
                "max_depth": self._MAX_DEPTH,
                "max_nodes": self._MAX_NODES,
                "seed_count": len(seed_ids),
                "selected_seed_count": included_seeds,
                "token_estimator": "conservative-utf8-heuristic",
                "token_budget_enforced": True,
            },
        )
