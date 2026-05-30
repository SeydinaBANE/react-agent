# ReAct Agent

Autonomous LLM agent with episodic memory, tool use, and human-in-the-loop approval.

## Quick start

```bash
cp .env.example .env   # Fill in ANTHROPIC_API_KEY
make install
make dev
make run GOAL="Research the 3 best RAG papers from 2024 and summarize them"
```

See [CLAUDE.md](CLAUDE.md) for the full architecture guide.
