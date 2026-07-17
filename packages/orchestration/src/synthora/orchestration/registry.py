"""Pipeline registry (R-PIPE-1): named LangGraph pipelines."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from langgraph.graph.state import CompiledStateGraph


@dataclass
class PipelineSpec:
    id: str
    name: str
    description: str
    builder: Callable[[], CompiledStateGraph]
    tags: list[str] = field(default_factory=list)


class PipelineRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, PipelineSpec] = {}

    def register(self, spec: PipelineSpec) -> None:
        self._specs[spec.id] = spec

    def get(self, pipeline_id: str) -> PipelineSpec:
        if pipeline_id not in self._specs:
            raise KeyError(
                f"unknown pipeline '{pipeline_id}' (known: {sorted(self._specs)})"
            )
        return self._specs[pipeline_id]

    def build(self, pipeline_id: str) -> CompiledStateGraph:
        return self.get(pipeline_id).builder()

    def list_specs(self) -> list[PipelineSpec]:
        return [self._specs[k] for k in sorted(self._specs)]


pipeline_registry = PipelineRegistry()
