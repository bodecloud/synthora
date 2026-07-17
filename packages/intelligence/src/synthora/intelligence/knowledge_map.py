"""Hierarchical knowledge map with insert/reorganize (R-STORM-3).

Ports Co-STORM's dynamic mind map: information is placed under the best
matching concept node; when a node collects more than ``capacity`` infos it
is reorganized into subtopics. Similarity is lexical by default (token
Jaccard) and pluggable for embedding backends.
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from synthora.core.models import Citation, KnowledgeEdge, KnowledgeNode
from synthora.core.parsing import parse_json_response
from synthora.core.ports import ChatModel

SimilarityFn = Callable[[str, str], float]


def tokenize(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2}


def jaccard(a: str, b: str) -> float:
    ta, tb = tokenize(a), tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


class KnowledgeMap:
    def __init__(
        self,
        root_name: str,
        *,
        capacity: int = 10,
        similarity: SimilarityFn = jaccard,
    ) -> None:
        self.capacity = capacity
        self.similarity = similarity
        self.root = KnowledgeNode(name=root_name)
        self.nodes: dict[str, KnowledgeNode] = {self.root.id: self.root}
        self.edges: list[KnowledgeEdge] = []

    @classmethod
    def from_nodes(
        cls,
        nodes: list[KnowledgeNode],
        edges: Optional[list[KnowledgeEdge]] = None,
        *,
        capacity: int = 10,
        similarity: SimilarityFn = jaccard,
    ) -> "KnowledgeMap":
        """Rebuild a map from persisted node/edge state (e.g. after mind_map_upsert)."""
        if not nodes:
            raise ValueError("KnowledgeMap.from_nodes requires at least one node")
        root = next((n for n in nodes if not n.parent_id), nodes[0])
        kmap = cls.__new__(cls)
        kmap.capacity = capacity
        kmap.similarity = similarity
        kmap.root = root
        kmap.nodes = {n.id: n for n in nodes}
        kmap.edges = list(edges or [])
        return kmap

    # -- structure helpers -------------------------------------------------

    def children(self, node_id: str) -> list[KnowledgeNode]:
        return [n for n in self.nodes.values() if n.parent_id == node_id]

    def add_node(self, name: str, *, parent_id: Optional[str] = None) -> KnowledgeNode:
        parent = parent_id or self.root.id
        node = KnowledgeNode(name=name, parent_id=parent)
        self.nodes[node.id] = node
        self.edges.append(
            KnowledgeEdge(source_id=parent, target_id=node.id, relation="parent_of")
        )
        return node

    def add_relation(self, source_id: str, target_id: str, relation: str) -> None:
        self.edges.append(
            KnowledgeEdge(source_id=source_id, target_id=target_id, relation=relation)
        )

    def all_infos(self) -> list[Citation]:
        return [c for n in self.nodes.values() for c in n.infos]

    # -- insert ------------------------------------------------------------

    def best_node_for(self, text: str) -> KnowledgeNode:
        """Best placement: highest similarity between text and node name+summary."""
        best, best_score = self.root, -1.0
        for node in self.nodes.values():
            score = self.similarity(text, f"{node.name} {node.summary}")
            if score > best_score:
                best, best_score = node, score
        return best

    def insert(self, info: Citation) -> KnowledgeNode:
        target = self.best_node_for(f"{info.title} {info.snippet}")
        target.infos.append(info)
        return target

    # -- reorganize --------------------------------------------------------

    async def reorganize(self, llm: ChatModel) -> list[KnowledgeNode]:
        """Split any node whose info count exceeds capacity into subtopics.

        Returns the list of newly created nodes.
        """
        created: list[KnowledgeNode] = []
        for node in list(self.nodes.values()):
            if len(node.infos) <= self.capacity:
                continue
            listing = "\n".join(
                f"{i}: {c.title} — {c.snippet[:120]}" for i, c in enumerate(node.infos)
            )
            raw = await llm.complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "Cluster these information snippets into 2-4 subtopics "
                            'of the parent concept. Reply JSON: [{"name": "...", '
                            '"indices": [0, 3, ...]}] covering every index exactly '
                            "once."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Parent concept: {node.name}\n\n{listing}",
                    },
                ]
            )
            clusters = parse_json_response(raw)
            if not isinstance(clusters, list) or not clusters:
                continue
            infos = node.infos
            node.infos = []
            assigned: set[int] = set()
            for cluster in clusters:
                if not isinstance(cluster, dict) or not cluster.get("name"):
                    continue
                child = self.add_node(str(cluster["name"]), parent_id=node.id)
                created.append(child)
                for idx in cluster.get("indices", []):
                    if isinstance(idx, int) and 0 <= idx < len(infos) and idx not in assigned:
                        child.infos.append(infos[idx])
                        assigned.add(idx)
            leftovers = [c for i, c in enumerate(infos) if i not in assigned]
            node.infos.extend(leftovers)
        return created

    # -- export ------------------------------------------------------------

    def to_outline_text(self, node: Optional[KnowledgeNode] = None, depth: int = 0) -> str:
        node = node or self.root
        lines = [f"{'  ' * depth}- {node.name} ({len(node.infos)} sources)"]
        for child in self.children(node.id):
            lines.append(self.to_outline_text(child, depth + 1))
        return "\n".join(lines)
