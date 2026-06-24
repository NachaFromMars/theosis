"""Load slot configuration from YAML (keys via env) or fall back to demo mode.

UI-added slots are persisted to a gitignored local file (slots.local.yaml) so
they survive restarts — without ever writing API keys into the committed
config.yaml.
"""
from __future__ import annotations

import os
from typing import List, Tuple

import yaml

from .metrics import set_cost_table
from .models import MiddleLayer, ModelSlot

# Load a local .env if present (optional dependency).
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional
    pass

DEFAULT_CONFIG_PATH = os.environ.get("THEOSIS_CONFIG", "config.yaml")
LOCAL_SLOTS_PATH = os.environ.get("THEOSIS_LOCAL_SLOTS", "slots.local.yaml")


def _slot_from_dict(d: dict, runtime: bool = False) -> ModelSlot:
    api_key = ""
    if d.get("api_key_env"):
        api_key = os.environ.get(d["api_key_env"], "")
    elif d.get("api_key"):
        api_key = d["api_key"]
    return ModelSlot(
        name=d["name"],
        model=d["model"],
        base_url=d["base_url"],
        api_key=api_key,
        middlelayer=MiddleLayer(system=d.get("system")),
        enabled=d.get("enabled", True),
        runtime=runtime,
    )


DEFAULT_SETTINGS = {
    "max_rounds": 2,
    "strategy": "round_robin",
    "auditors_per_answer": 1,
    "use_executor": False,
    "use_router": False,
    "use_memory": False,
    "auto_learn": False,
    "verified_only": False,
    "summarize_history": False,
}


def demo_slots() -> List[ModelSlot]:
    """Mock slots so the UI and pipeline run with zero configuration."""
    return [
        ModelSlot(
            "opus", "claude-opus-4-8 · demo", "mock://",
            middlelayer=MiddleLayer(system="Bạn nghiêm ngặt, chính xác."),
        ),
        ModelSlot(
            "gpt", "gpt-4o · demo", "mock://",
            middlelayer=MiddleLayer(system="Bạn đa góc nhìn, đào sâu."),
        ),
        ModelSlot("deepseek", "deepseek-chat · demo", "mock://", enabled=False),
    ]


def demo_aggregator() -> ModelSlot:
    return ModelSlot("aggregator", "claude-opus-4-8 · demo", "mock://")


# ── UI-added slots persistence (gitignored) ─────────────────────────────────
def load_local_slot_dicts() -> List[dict]:
    if not os.path.exists(LOCAL_SLOTS_PATH):
        return []
    with open(LOCAL_SLOTS_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("slots", []) or []


def save_local_slot_dicts(slot_dicts: List[dict]) -> None:
    with open(LOCAL_SLOTS_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump({"slots": slot_dicts}, f, allow_unicode=True, sort_keys=False)


def load_config(path: str = None) -> Tuple[List[ModelSlot], ModelSlot, dict]:
    """Return (slots, aggregator, settings).

    Falls back to demo (mock) slots when THEOSIS_DEMO=1, when the config file is
    missing, or when it defines no slots — so a fresh clone always runs. Any
    UI-added slots from slots.local.yaml are merged in (overriding same-name).
    """
    path = path or DEFAULT_CONFIG_PATH

    if os.environ.get("THEOSIS_DEMO") == "1" or not os.path.exists(path):
        slots, aggregator, settings = demo_slots(), demo_aggregator(), dict(DEFAULT_SETTINGS)
    else:
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        slots = [_slot_from_dict(s) for s in cfg.get("slots", [])]
        aggregator = _slot_from_dict(cfg["aggregator"]) if cfg.get("aggregator") else demo_aggregator()
        settings = {**DEFAULT_SETTINGS, **(cfg.get("settings") or {})}  # config.yaml ghi đè default
        if cfg.get("pricing"):
            set_cost_table(cfg["pricing"])
        if not slots:
            slots = demo_slots()

    local = [_slot_from_dict(d, runtime=True) for d in load_local_slot_dicts()]
    if local:
        local_names = {s.name for s in local}
        slots = [s for s in slots if s.name not in local_names] + local

    return slots, aggregator, settings
