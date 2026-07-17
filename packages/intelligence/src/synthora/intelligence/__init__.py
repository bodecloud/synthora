"""Synthora intelligence layer: STORM/Co-STORM style knowledge formation."""

from synthora.intelligence.discourse import DiscourseManager
from synthora.intelligence.embeddings import (
    HashEmbeddings,
    cosine_similarity,
    make_embedding_similarity,
)
from synthora.intelligence.knowledge_map import KnowledgeMap
from synthora.intelligence.outline import OutlineBuilder, SectionWriter
from synthora.intelligence.perspectives import PerspectiveEngine

__all__ = [
    "DiscourseManager",
    "HashEmbeddings",
    "KnowledgeMap",
    "OutlineBuilder",
    "PerspectiveEngine",
    "SectionWriter",
    "cosine_similarity",
    "make_embedding_similarity",
]
