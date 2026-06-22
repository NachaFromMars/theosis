# Theosis

> Multi-model orchestration engine: **fan-out → cross-audit → patch → merge**

Theosis is a provider-agnostic LLM orchestration core. It sends a single request to a council of models in parallel, has each model adversarially audit its peers, patches each answer based on the critique, then synthesises everything into one final response.

---

## Pipeline

```
Request
  │
  ▼
Phase 1 ── Fan-out (parallel)
  │         Send the same request to all enabled slots simultaneously.
  │
  ▼
Phase 2 ── Cross-audit (parallel, round-robin)
  │         Slot A audits Slot B, B audits C, … N audits A.
  │         Each auditor returns: VERDICT / ISSUES / MISSING / KEEP.
  │
  ▼
Phase 3 ── Patch (parallel)
  │         Each slot revises its own answer using the critique it received.
  │
  ▼ (repeat Phase 2–3 for max_rounds)
  │
  ▼
Phase 5 ── Merge
            An aggregator model synthesises all refined answers into one
            final coherent response.
```

---

## Quickstart

```bash
pip install httpx
python example.py        # runs with built-in mock slots, no API key needed
```

To use real models, edit `config.yaml` and supply API keys via environment variables or directly in the config file.

---

## Structure

```
theosis/
├── theosis/
│   ├── __init__.py   — public API
│   ├── core.py       — orchestration engine
│   ├── models.py     — ModelSlot, MiddleLayer dataclasses
│   └── prompts.py    — RUBRIC, PATCH_SYS, MERGE_PROMPT
├── config.yaml       — example configuration
├── example.py        — runnable demo (mock mode)
└── pyproject.toml
```

---

## Key concepts

| Concept | Description |
|---|---|
| **ModelSlot** | One model endpoint. Holds name, model id, API key, base URL, and an optional MiddleLayer. |
| **MiddleLayer** | Pre/post hooks per slot — transform the request before sending and the raw reply before passing forward. |
| **Aggregator** | A dedicated slot that merges all refined answers in Phase 5. |
| **Mock mode** | `ModelSlot.mock("name")` runs the full pipeline locally without any API call. |
| **EventCb** | Async callback `on_event(dict)` — stream every phase event to a live UI or logger. |

---

## Provider compatibility

Any OpenAI-compatible `/chat/completions` endpoint works:
OpenAI, Anthropic (via proxy), OpenRouter, Mistral, local Ollama, etc.

---

## License

MIT
