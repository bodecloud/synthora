# Research pipelines

All pipelines are LangGraph `StateGraph`s over the shared `AgentState`,
registered in `pipeline_registry`. Select one per run via `pipeline_id`.

## fast_research

`clarify? → brief → single_researcher → report`

One researcher ReAct loop (search strategy against the configured engines),
compression, one-shot answer. Minutes-scale, minimal tokens.

## deep_research (flagship)

`clarify? → brief → supervisor ⇄ parallel researchers → perspectives →
discourse → knowledge_map → outline → section_write → critic → report`

- The supervisor plans subtopics and dispatches up to
  `max_concurrent_research_units` researchers in parallel; researchers
  compress raw findings before returning (context isolation).
- The STORM stage discovers `num_perspectives` expert personas, runs a
  Co-STORM roundtable (`max_discourse_turns`, moderator every 3rd turn
  surfacing unused evidence), builds the knowledge map, designs the outline,
  and writes cited sections.
- A critic reviews the draft; the final writer addresses the critique.

## academic_research

`brief → lit_search → citation_verify → outline → section_write →
peer_review → report → bibliography`

Literature search runs directly against academic engines (configure
`search_engines: ["arxiv", "semantic_scholar"]`). Citation verification
cross-checks each source against the brief; rejected sources are dropped from
the bibliography and their confidence lowered.

## autonomous_research

`brief → (hypothesize → investigate → gap_finder)* → knowledge_map → report`

Bounded discovery loop (`max_autonomous_cycles`): generate hypotheses, deploy
the supervisor to investigate them, discover remaining knowledge gaps, spawn
new research paths from those gaps, update the knowledge base, and repeat
until gaps close or the cycle budget is exhausted.

## Configuration knobs (per run, `RunConfig`)

| Knob | Default | Applies to |
|---|---|---|
| `planner/researcher/compressor/writer/critic_model` | gpt-4o-mini / gpt-4o | all |
| `search_engines`, `search_strategy` | `["searxng"]`, `source_based` | all |
| `allow_clarification` | false | fast, deep |
| `max_concurrent_research_units` | 5 | deep, autonomous |
| `max_researcher_iterations` | 6 | deep, autonomous |
| `max_react_tool_calls` | 10 | all |
| `num_perspectives` | 3 | deep |
| `max_discourse_turns` | 12 | deep |
| `knowledge_node_capacity` | 10 | deep, autonomous |
| `moderator_alpha` | 0.5 | deep |
| `max_autonomous_cycles` | 3 | autonomous |
