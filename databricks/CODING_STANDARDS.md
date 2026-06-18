# Coding Standards — Caltrans Databricks App

## Project Structure

```
databricks/
├── app.py                    # Streamlit entry point (UI only, no business logic)
├── app.yaml                  # Databricks App config
├── databricks.yml            # Bundle config
├── requirements.txt          # Python dependencies
├── .streamlit/
│   └── config.toml           # Streamlit theme (light mode)
├── src/
│   ├── __init__.py
│   ├── databricks_client.py  # Shared: LLM client + model constants
│   ├── result_store.py       # Shared: SQLite result persistence
│   │
│   ├── # --- PDE (Project Delivery Evaluator) ---
│   ├── pde_agents.py         # Agentic pipeline (Planning, Orchestrator, Prompt Gen, Code Gen, Delivery)
│   ├── project_delivery_evaluator.py  # Core evaluation logic, rubric, scoring, Excel export
│   ├── pde_memory_manager.py # Institutional memory for PDE rules
│   ├── delivery_method_kb.py # Static knowledge base text
│   │
│   ├── # --- CUCP (Re-Evaluations) ---
│   ├── cucp_reevals.py       # 3-level evaluation pipeline
│   ├── memory_manager.py     # CUCP correction memory
│   ├── memory_db.json        # CUCP memory persistence
│   │
│   ├── # --- Other Use Cases ---
│   ├── ai_content_detector.py
│   ├── ai_content_detector_ui.py
│   ├── ai_judge.py
│   ├── chat_ui.py
│   ├── foundation_model_chat.py
│   ├── highway_incident_summarizer.py
│   ├── landing_ai_row_eval_chunked.py
│   ├── landing_ai_ui.py
│   ├── llm_evaluation.py
│   ├── llm_training.py
│   ├── personal_narrative_insights.py
│   └── reentry_care_plan.py
│
├── image/                    # Static assets (logos)
├── style/                    # CSS
├── templates/                # Excel templates
├── docs/                     # Architecture docs, flowcharts
│
└── tests/
    ├── e2e/
    │   ├── conftest.py       # Playwright fixtures
    │   └── test_pde_flow.py  # Full PDE E2E test
    └── unit/
        └── test_result_store.py
```

## Naming Conventions

| Element        | Convention           | Example                        |
|----------------|---------------------|--------------------------------|
| Files          | snake_case          | `result_store.py`              |
| Functions      | snake_case          | `run_pde_evaluation()`         |
| Classes        | PascalCase          | `ResultStore`                  |
| Constants      | UPPER_SNAKE         | `MODEL_GPT4O`                  |
| Private        | Leading underscore  | `_build_system_prompt()`       |
| Test files     | `test_` prefix      | `test_pde_flow.py`            |

## Module Responsibilities

### `databricks_client.py`
- Single source of truth for LLM client initialization
- Model name constants
- No business logic

### `pde_agents.py`
- Entry point: `run_pde_evaluation()`
- 5 agents as pure functions (no Streamlit dependency)
- Each agent has a single responsibility
- Uses `result_store.py` for persistence

### `result_store.py`
- SQLite-based key-value store
- Fingerprint computation (SHA-256)
- Stage-separated storage (prompt vs code)
- No LLM calls, no UI

### `project_delivery_evaluator.py`
- Rubric definitions, scoring matrix
- Excel generation
- System prompt construction
- Called by `pde_agents.py`, never directly from `app.py` for evaluation

## Rules

1. **No business logic in `app.py`** — UI rendering only, delegate to `src/`
2. **No Streamlit imports in agent/evaluator modules** — keeps them testable
3. **All LLM calls go through `databricks_client.py`** — single auth point
4. **Result Store is the only persistence for PDE** — no session-dependent caching for core results
5. **Type hints on public functions** — private helpers can skip them
6. **No hardcoded model names outside `databricks_client.py`** — use constants
7. **Tests must not call real LLM endpoints** — mock `get_openai_client()`
