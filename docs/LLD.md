# Low-Level Design (LLD) Patterns

This document maps the design patterns applied in `src/devops_agent` and where to extend them.

## Pattern map

| Pattern | Role | Location |
|---------|------|----------|
| **Facade** | Stable entry for workers/API | `agents/orchestrator.py` → `InvestigationOrchestrator` |
| **Template Method** | Fixed lifecycle skeleton | `agents/workflow.py` → `InvestigationWorkflow.run` |
| **Command** | One class per investigation phase | `agents/phases.py` → `TriagePhase`, `InvestigatePhase`, … |
| **Observer** | Journal + tool-loop side effects | `agents/journal.py` → `JournalEmitter`, `CompositeObserver` |
| **Factory** | Compose tools + MCP into a loop | `tools/registry.py` → `ToolRegistryFactory` |
| **Strategy** | LLM backend | `agents/reasoner.py` → `Reasoner` / `get_reasoner()` |
| **Strategy** | Runbook retrieval | `rag/strategy.py` → `Bm25RetrievalStrategy`, `OpenSearchRetrievalStrategy` |
| **Adapter** | Topology over Store | `topology/graph.py` → `walk(store=, space_id=)` |
| **Adapter** | Queue / Store backends | `queueing.py`, `persistence/*` |
| **Repository** | Aggregate persistence protocol | `persistence/protocol.py` → `Store` |
| **Circuit Breaker** | Per-provider resilience | `resilience/circuit_breaker.py` |
| **Idempotency (Lock)** | Exactly-once investigation claim | `resilience/idempotency.py` |

## Investigation lifecycle (Template Method + Command)

```
InvestigationOrchestrator.run()          # Facade
  └─ InvestigationWorkflow.run()         # Template Method
       ├─ _prepare()                     # Factory + Observer wiring
       ├─ _run_phases()                  # for phase in pipeline: Command.execute()
       │    ├─ TriagePhase
       │    ├─ InvestigatePhase
       │    ├─ MitigatePhase
       │    └─ PreventPhase
       └─ _complete() / _fail()
```

To add a phase (e.g. `PostMortemPhase`), implement `PhaseCommand` and pass a custom list into `InvestigationWorkflow(phases=[...])`. Do not fork `run()`.

## Tool surface (Factory + Strategy)

```
ToolRegistryFactory.build_loop(space_id, mcp_ids)
  ├─ builtin_tools(space_id)             # Factory product
  ├─ McpRegistry.tools_for_space(...)    # allowlisted MCP tools
  └─ ToolLoop(registry, reasoner)        # Strategy: Bedrock | LocalReasoner
```

`ToolRegistry.dispatch(name, args)` is the single dispatch point (replaces linear scans + MCP prefix branching).

## Observability (Observer)

`JournalEmitter` implements `InvestigationObserver`:

- `on_record(...)` → immutable journal rows  
- `on_event(kind, data)` → adapts ToolLoop callbacks into `TOOL_CALL` / `EVIDENCE`

Attach Slack/metrics later via `CompositeObserver(journal, metrics, slack)`.

## Retrieval (Strategy)

```python
strategy = build_retrieval_strategy()  # BM25 or OpenSearch Adapter
strategy.rebuild(runbooks)
hits = strategy.search(query, k=4)
```

## Topology (Adapter)

```python
walk("checkout-api", depth=2, store=store, space_id=inv.agent_space_id)
```

Builtin tools bind `space_id` at Factory time so blast-radius walks stay Agent-Space scoped.

## What not to pattern-spray

- Keep `domain/models.py` as plain Pydantic contracts (no pattern wrappers).  
- Do not split `Store` into many repositories until tables/files force it.  
- Do not replace the Bedrock converse loop — only inject Strategy at the edges.
