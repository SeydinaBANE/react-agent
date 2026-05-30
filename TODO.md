# TODO — ReAct Agent

## Phase 1 — Scaffold + tooling [✓]
- [x] git init
- [x] pyproject.toml (PEP 621, ruff strict, mypy strict, commitizen)
- [x] Makefile (20+ commandes, .PHONY)
- [x] .pre-commit-config.yaml (ruff, mypy, bandit, detect-secrets, commitizen)
- [x] .gitignore, .editorconfig, .dockerignore
- [x] docker/api.Dockerfile (multi-stage, non-root)
- [x] .github/workflows/ci.yml (lint + test + security + schema)
- [x] .github/dependabot.yml
- [x] .github/pull_request_template.md + ISSUE_TEMPLATE/
- [x] CODEOWNERS
- [x] CLAUDE.md, TODO.md, .env.example
- [x] Structure de dossiers src/agent/{core,llm,memory,tools,runner,api}

## Phase 2 — Core : schemas + config + exceptions + telemetry [ ]
- [ ] src/agent/core/config.py (pydantic-settings v2)
- [ ] src/agent/core/schemas.py (Action, AgentStep, TaskTrace, TaskStatus)
- [ ] src/agent/core/exceptions.py (hiérarchie domaine)
- [ ] src/agent/core/telemetry.py (structlog + Prometheus + correlation IDs)
- [ ] tests/unit/test_schemas.py, test_config.py, test_telemetry.py
- [ ] git commit

## Phase 3 — LLM client + prompt builder [ ]
- [ ] src/agent/llm/client.py (AsyncAnthropic wrapper, tool_use)
- [ ] src/agent/llm/prompt_builder.py (system prompt ReAct + mémoire)
- [ ] tests/unit/test_llm_client.py (LLM mocké)
- [ ] git commit

## Phase 4 — ToolRegistry + 5 outils [ ]
- [ ] src/agent/tools/base.py (Protocol Tool + ToolRegistry)
- [ ] src/agent/tools/web_search.py (Brave API)
- [ ] src/agent/tools/code_executor.py (subprocess sécurisé, timeout)
- [ ] src/agent/tools/file_io.py (path whitelist)
- [ ] src/agent/tools/http_client.py (REST arbitraire)
- [ ] src/agent/tools/memory_tool.py (recherche Qdrant)
- [ ] config/tools.yaml
- [ ] tests/unit/test_tools.py
- [ ] git commit

## Phase 5 — Mémoire épisodique [ ]
- [ ] src/agent/memory/embedder.py (sentence-transformers all-MiniLM-L6-v2)
- [ ] src/agent/memory/episodic.py (Qdrant store/search/delete)
- [ ] src/agent/memory/working.py (état courant de la tâche)
- [ ] tests/unit/test_memory.py (Qdrant in-memory mock)
- [ ] git commit

## Phase 6 — ReactLoop + ApprovalGate + Tracer [ ]
- [ ] src/agent/runner/react_loop.py (boucle Thought→Action→Observation)
- [ ] src/agent/runner/approval_gate.py (suspension + résolution humaine)
- [ ] src/agent/runner/tracer.py (collecte + export trace JSON)
- [ ] tests/unit/test_react_loop.py (LLM + tools mockés)
- [ ] tests/unit/test_tracer.py
- [ ] git commit

## Phase 7 — FastAPI /api/v1/ [ ]
- [ ] src/agent/api/main.py (lifespan, CORS, metrics endpoint)
- [ ] src/agent/api/middleware.py (JWT auth, correlation ID, rate limiting)
- [ ] src/agent/api/routers/tasks.py (POST /tasks, GET /tasks/{id}/trace, POST /tasks/{id}/approve)
- [ ] src/agent/api/routers/stream.py (GET /tasks/{id}/stream SSE)
- [ ] /health (liveness) + /ready (readiness)
- [ ] RFC 7807 error handler
- [ ] Graceful shutdown (SIGTERM)
- [ ] tests/unit/test_api.py
- [ ] git commit

## Phase 8 — Tests d'intégration + coverage [ ]
- [ ] tests/conftest.py (fixtures Testcontainers)
- [ ] tests/integration/test_api.py (API complète avec Qdrant réel)
- [ ] tests/integration/test_full_run.py (tâche e2e avec LLM mocké)
- [ ] Vérifier coverage ≥ 80% (--cov-fail-under=80)
- [ ] git commit

## Phase 9 — docker-compose + scripts + schema [ ]
- [ ] docker-compose.yml (API + Qdrant + Prometheus + Grafana)
- [ ] docker-compose.override.yml (dev : volumes, hot-reload, DEBUG)
- [ ] docker-compose.test.yml (Testcontainers alternative)
- [ ] config/prometheus.yml
- [ ] scripts/run_task.py (CLI submit + live stream)
- [ ] scripts/inspect_trace.py (afficher trace JSON)
- [ ] scripts/export_schema.py (générer openapi.json)
- [ ] make all-checks → vert complet
- [ ] git commit final + cz bump → v0.1.0
