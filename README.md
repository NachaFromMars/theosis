# theosis — Multi-model orchestration engine

> Stop trusting one model. **theosis** runs your question through a council of LLMs — fan-out → cross-audit → patch → merge — so weak answers get caught and strong ones rise to the top.

[![OpenClaw Skill](https://img.shields.io/badge/OpenClaw-Skill-blueviolet)](https://github.com/NachaFromMars)
[![Version](https://img.shields.io/badge/Version-2.0.0-orange)](CHANGELOG.md)
[![License](https://img.shields.io/badge/License-Apache--2.0-green)](LICENSE)

## Overview

theosis is a multi-model orchestration engine. Instead of asking a single LLM and hoping it's right, it dispatches your query to a configurable council of models, has them cross-audit each other's answers, patches the weak spots, and merges everything into one high-confidence response. Built async on `httpx` + `asyncio`, it exposes an OpenAI-compatible endpoint so any client that talks to `/v1/chat/completions` can use it as a drop-in upgrade.

## The Pipeline

```
   Your question
        │
        ▼
   ┌─────────┐   Fan-out: every model answers independently
   │ FAN-OUT │
   └─────────┘
        │
        ▼
  ┌────────────┐  Cross-audit: models critique each other's answers
  │ CROSS-AUDIT│  (VERDICT: strong / mixed / weak)
  └────────────┘
        │
        ▼
   ┌─────────┐   Patch: weak answers get revised
   │  PATCH  │
   └─────────┘
        │
        ▼
   ┌─────────┐   Merge: confidence-weighted aggregation → final answer
   │  MERGE  │
   └─────────┘
```

## Features

- **Multi-model council** — configure any OpenAI-compatible endpoint (OpenAI, Anthropic, OpenRouter, DeepSeek, xAI/Grok, Groq, local Ollama)
- **Resilient pipeline** — per-slot retry + timeout; a failing model (timeout/401/429/5xx) is dropped from the round, never crashes the batch
- **Cost & token meter** — reads `usage` from each response, accumulates tokens in/out + estimated cost per model
- **Token budget guard** — set `max_tokens_budget`; exceeding it cleanly stops and merges what's available
- **Convergence early-stop** — compares answer similarity between rounds; stops early when answers converge
- **Confidence scoring → weighted merge** — parses `VERDICT` (strong/mixed/weak) into scores so the aggregator favors strong answers
- **OpenAI-compatible API** — `/v1/chat/completions` with real token `usage`
- **CLI + server** — `python -m theosis "question"` or run as an HTTP service

## Quick Start

```bash
pip install .

# Try it with no API keys (mock models)
THEOSIS_DEMO=1 python run.py
# → http://localhost:8000

# CLI
python -m theosis "your question" --rounds 2 --json

# Production server
python run.py   # http://localhost:8000
```

Configure your council in `config.yaml` — each slot is an OpenAI-compatible endpoint. API keys are read from environment variables via `api_key_env` (never written to the file).

```yaml
slots:
  - name: opus
    model: claude-opus-4-8
    base_url: https://api.anthropic.com/v1
    api_key_env: ANTHROPIC_API_KEY
    enabled: true
  - name: gpt
    model: gpt-4o
    base_url: https://api.openai.com/v1
    api_key_env: OPENAI_API_KEY
    enabled: true
```

## Why "theosis"?

A council that refines itself — each model lifting the others toward a better answer than any single one could reach alone.

## Trigger Keywords (OpenClaw)

theosis, multi-model orchestration, model council, cross-audit, fan-out merge, ensemble LLM, consensus answer

## Related Skills

- [infinity-neural](https://github.com/NachaFromMars/infinity-neural) — zero-decay memory for agents
- [mula-audit](https://github.com/NachaFromMars/mula-audit) — multi-agent code quality audit

---
Part of the [NachaFromMars](https://github.com/NachaFromMars) OpenClaw skill ecosystem.
