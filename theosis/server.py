"""Theosis server: OpenAI-compatible API + a live web console."""
from __future__ import annotations

import asyncio
import copy
import json
import time
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from .config import load_config, save_local_slot_dicts
from .core import theosis
from .models import MiddleLayer, ModelSlot

SLOTS, AGGREGATOR, SETTINGS = load_config()
WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="Theosis", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request models ───────────────────────────────────────────────────────────
class Msg(BaseModel):
    role: str
    content: str


class ChatReq(BaseModel):
    model: str = "theosis-v1"
    messages: List[Msg]
    max_rounds: Optional[int] = None
    max_tokens_budget: Optional[int] = None
    stream: Optional[bool] = False  # accepted for compatibility; ignored in V2


class RunReq(BaseModel):
    prompt: str
    max_rounds: Optional[int] = None
    max_tokens_budget: Optional[int] = None
    enabled_slots: Optional[List[str]] = None


def _active_slots(enabled_names: Optional[List[str]]) -> List[ModelSlot]:
    """Return slot views with `enabled` set per request, without mutating globals."""
    if enabled_names is None:
        return SLOTS
    chosen = set(enabled_names)
    views = []
    for s in SLOTS:
        view = copy.copy(s)  # shallow copy; middlelayer is read-only and shared
        view.enabled = s.name in chosen
        views.append(view)
    return views


def _default_rounds(value: Optional[int]) -> int:
    return value if value is not None else int(SETTINGS.get("max_rounds", 2))


# ── Web console ──────────────────────────────────────────────────────────────
@app.get("/")
def index():
    idx = WEB_DIR / "index.html"
    if idx.exists():
        return FileResponse(idx)
    return JSONResponse(
        {"error": "UI not found", "hint": "web/index.html is missing"}, status_code=404
    )


def _has_key(s: ModelSlot) -> bool:
    return (
        s.is_mock
        or bool(s.api_key)
        or "localhost" in s.base_url
        or "127.0.0.1" in s.base_url
    )


@app.get("/api/config")
def get_config():
    return {
        "slots": [
            {
                "name": s.name,
                "model": s.model,
                "enabled": s.enabled,
                "mock": s.is_mock,
                "has_key": _has_key(s),
                "runtime": getattr(s, "runtime", False),
            }
            for s in SLOTS
        ],
        "aggregator": {
            "name": AGGREGATOR.name,
            "model": AGGREGATOR.model,
            "mock": AGGREGATOR.is_mock,
            "has_key": _has_key(AGGREGATOR),
        },
        "settings": SETTINGS,
        "demo": any(s.is_mock for s in SLOTS),
    }


# ── Add / remove models from the UI (persisted to slots.local.yaml) ──────────
class AddSlotReq(BaseModel):
    name: str
    model: str
    base_url: str
    api_key: Optional[str] = ""
    system: Optional[str] = None
    enabled: Optional[bool] = True


def _persist_runtime_slots() -> None:
    dicts = []
    for s in SLOTS:
        if getattr(s, "runtime", False):
            d = {"name": s.name, "model": s.model, "base_url": s.base_url, "enabled": s.enabled}
            if s.api_key:
                d["api_key"] = s.api_key
            if s.middlelayer.system:
                d["system"] = s.middlelayer.system
            dicts.append(d)
    save_local_slot_dicts(dicts)


@app.post("/api/slots")
def add_slot(req: AddSlotReq):
    name = req.name.strip()
    if not name or not req.model.strip() or not req.base_url.strip():
        raise HTTPException(status_code=400, detail="Cần tên, model và base URL.")
    if any(s.name == name for s in SLOTS):
        raise HTTPException(status_code=409, detail=f"Đã có slot tên '{name}'.")
    slot = ModelSlot(
        name=name,
        model=req.model.strip(),
        base_url=req.base_url.strip(),
        api_key=(req.api_key or "").strip(),
        middlelayer=MiddleLayer(system=(req.system or None)),
        enabled=bool(req.enabled),
        runtime=True,
    )
    SLOTS.append(slot)
    _persist_runtime_slots()
    return {
        "ok": True,
        "slot": {
            "name": slot.name,
            "model": slot.model,
            "enabled": slot.enabled,
            "mock": slot.is_mock,
            "has_key": _has_key(slot),
            "runtime": True,
        },
    }


@app.delete("/api/slots/{name}")
def delete_slot(name: str):
    for i, s in enumerate(SLOTS):
        if s.name == name:
            if not getattr(s, "runtime", False):
                raise HTTPException(
                    status_code=400,
                    detail="Slot này khai báo trong config.yaml — sửa trong file, không xoá từ UI.",
                )
            SLOTS.pop(i)
            _persist_runtime_slots()
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Không tìm thấy slot.")


# ── Rich streaming run for the UI (NDJSON of progress events) ────────────────
@app.post("/api/run")
async def api_run(req: RunReq):
    slots = _active_slots(req.enabled_slots)
    max_rounds = _default_rounds(req.max_rounds)

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()

        async def on_event(event: dict):
            await queue.put(event)

        async def runner():
            try:
                await theosis(
                    req.prompt, slots, AGGREGATOR, max_rounds=max_rounds,
                    on_event=on_event, max_tokens_budget=req.max_tokens_budget,
                )
            except Exception as exc:  # surface as an error event, never crash the stream
                await queue.put({"type": "error", "message": str(exc)})
            finally:
                await queue.put(None)

        task = asyncio.create_task(runner())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield json.dumps(event, ensure_ascii=False) + "\n"
        finally:
            await task

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


# ── OpenAI-compatible endpoints (Theosis as a drop-in model) ─────────────────
@app.get("/v1/models")
def list_models():
    return {
        "object": "list",
        "data": [{"id": "theosis-v1", "object": "model", "owned_by": "theosis"}],
    }


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatReq):
    user = next((m.content for m in reversed(req.messages) if m.role == "user"), "")
    max_rounds = _default_rounds(req.max_rounds)
    try:
        final, trail = await theosis(
            user, SLOTS, AGGREGATOR, max_rounds=max_rounds,
            max_tokens_budget=req.max_tokens_budget,
        )
    except Exception as exc:
        return JSONResponse(
            status_code=502,
            content={"error": {"message": str(exc), "type": "upstream_error"}},
        )
    cost = trail.get("cost", {})
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": final},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": cost.get("prompt_tokens", 0),
            "completion_tokens": cost.get("completion_tokens", 0),
            "total_tokens": cost.get("total_tokens", 0),
        },
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "slots": [s.name for s in SLOTS if s.enabled],
        "demo": any(s.is_mock for s in SLOTS),
    }
