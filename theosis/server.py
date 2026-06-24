"""Theosis server: OpenAI-compatible API + a live web console."""
from __future__ import annotations

import asyncio
import copy
import json
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from .config import load_config, save_local_slot_dicts
from .core import make_rule, theosis, theosis_stream
from .files import FileStore
from .ingest import extract_code_blocks
from .memory import MemoryStore, Rule, log_metrics
from .models import MiddleLayer, ModelSlot
from .stats import dashboard

SLOTS, AGGREGATOR, SETTINGS = load_config()
STORE = MemoryStore()
FILES = FileStore()
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


def _split_history(messages: List["Msg"]):
    """Tách (lịch sử, request hiện tại): request = tin nhắn user CUỐI, lịch sử = mọi
    message trước đó. Đây là cách chuẩn OpenAI — client giữ trạng thái, gửi cả mảng."""
    idx = None
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role == "user":
            idx = i
            break
    if idx is None:
        return [], ""
    history = [{"role": m.role, "content": m.content} for m in messages[:idx]]
    return history, messages[idx].content


class ChatReq(BaseModel):
    model: str = "theosis-v1"
    messages: List[Msg]
    max_rounds: Optional[int] = None
    max_tokens_budget: Optional[int] = None
    auditors_per_answer: Optional[int] = None
    use_executor: Optional[bool] = None
    strategy: Optional[str] = None
    use_router: Optional[bool] = None
    router: Optional[str] = None
    use_memory: Optional[bool] = None
    auto_learn: Optional[bool] = None
    verified_only: Optional[bool] = None
    summarize_history: Optional[bool] = None
    stream: Optional[bool] = False  # accepted for compatibility; ignored in V2


class RunReq(BaseModel):
    prompt: str
    max_rounds: Optional[int] = None
    max_tokens_budget: Optional[int] = None
    auditors_per_answer: Optional[int] = None
    use_executor: Optional[bool] = None
    strategy: Optional[str] = None
    use_router: Optional[bool] = None
    router: Optional[str] = None
    use_memory: Optional[bool] = None
    auto_learn: Optional[bool] = None
    verified_only: Optional[bool] = None
    summarize_history: Optional[bool] = None
    file_tokens: Optional[List[str]] = None
    history: Optional[List[Msg]] = None
    enabled_slots: Optional[List[str]] = None


class LearnReq(BaseModel):
    request: str
    correction: str
    bad_answer: Optional[str] = ""
    model: Optional[str] = None  # tên slot làm rule-maker; mặc định aggregator


class VerifyReq(BaseModel):
    verified: bool = True


class DemoteReq(BaseModel):
    demoted: bool = True
    score: Optional[float] = None


class EditRuleReq(BaseModel):
    guidance: str


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


def _default_auditors(value: Optional[int]) -> int:
    return value if value is not None else int(SETTINGS.get("auditors_per_answer", 1))


def _default_executor(value: Optional[bool]) -> bool:
    return value if value is not None else bool(SETTINGS.get("use_executor", False))


def _default_strategy(value: Optional[str]) -> str:
    return value or str(SETTINGS.get("strategy", "round_robin"))


def _default_router(value: Optional[bool]) -> bool:
    return value if value is not None else bool(SETTINGS.get("use_router", False))


def _default_router_name(value: Optional[str]) -> Optional[str]:
    return value if value is not None else SETTINGS.get("router")


def _default_memory(value: Optional[bool]) -> bool:
    return value if value is not None else bool(SETTINGS.get("use_memory", False))


def _default_auto_learn(value: Optional[bool]) -> bool:
    return value if value is not None else bool(SETTINGS.get("auto_learn", False))


def _persist_learned(trail: dict) -> None:
    """Lưu rule auto-learn (nếu có) vào STORE. Content-free — đã trừu tượng hoá từ core.
    dedup: bài học trùng được học lại → tăng uses, không nhân bản."""
    for rd in (trail.get("learned") or []):
        try:
            STORE.add_rule(Rule(**rd), dedup=True)
        except Exception:
            pass


def _default_verified_only(value: Optional[bool]) -> bool:
    return value if value is not None else bool(SETTINGS.get("verified_only", False))


def _default_summarize(value: Optional[bool]) -> bool:
    return value if value is not None else bool(SETTINGS.get("summarize_history", False))


def _fetch_memory(use_memory: bool, text: str, verified_only: bool = False):
    """Lấy rule liên quan từ STORE. Trả (list guidance | None, list rule objects)."""
    if not use_memory:
        return None, []
    rules = STORE.relevant(request=text, verified_only=verified_only)
    return ([r.guidance for r in rules] or None), rules


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
    use_memory = _default_memory(req.use_memory)
    auto_learn = _default_auto_learn(req.auto_learn)
    # tri giác: ghép context file (chia chung cho mọi slot) vào trước prompt
    file_ctx = FILES.text_for(req.file_tokens) if req.file_tokens else ""
    full_prompt = (file_ctx + "\n\n" + req.prompt) if file_ctx else req.prompt
    # ký ức dò theo prompt GỐC của người dùng (không lẫn nội dung file)
    mem_guidance, applied = _fetch_memory(use_memory, req.prompt, _default_verified_only(req.verified_only))

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()

        async def on_event(event: dict):
            await queue.put(event)

        async def runner():
            try:
                if file_ctx:
                    await queue.put({"type": "attachments",
                                     "files": FILES.uploads_meta(req.file_tokens)})
                final, trail = await theosis(
                    full_prompt, slots, AGGREGATOR, max_rounds=max_rounds,
                    history=[m.model_dump() for m in (req.history or [])],
                    summarize_history=_default_summarize(req.summarize_history),
                    on_event=on_event, max_tokens_budget=req.max_tokens_budget,
                    auditors_per_answer=_default_auditors(req.auditors_per_answer),
                    use_executor=_default_executor(req.use_executor),
                    strategy=_default_strategy(req.strategy),
                    use_router=_default_router(req.use_router),
                    router=_default_router_name(req.router),
                    memory_rules=mem_guidance,
                    auto_learn=auto_learn,
                )
                if auto_learn:
                    _persist_learned(trail)
                if use_memory:
                    if applied:
                        STORE.bump_uses([r.id for r in applied])
                    log_metrics(trail)  # content-free
                # xuất artifact: code block trong câu trả lời cuối → file tải về
                for i, blk in enumerate(extract_code_blocks(final), 1):
                    meta = FILES.add_output(f"artifact_{i}{blk['ext']}", blk["content"].encode("utf-8"))
                    await queue.put({"type": "artifact", "lang": blk["lang"], **meta})
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


@app.post("/api/learn")
async def api_learn(req: LearnReq):
    """Dạy một bài học từ một câu trả lời sai. Chỉ rule trừu tượng được lưu (content-free)."""
    slot = next((s for s in SLOTS if s.name == req.model), AGGREGATOR) if req.model else AGGREGATOR
    async with httpx.AsyncClient() as client:
        rule, _ = await make_rule(client, slot, req.request, req.bad_answer or "", req.correction)
    if rule is None:
        raise HTTPException(status_code=400, detail="Không tạo được rule từ phản hồi này.")
    rule.source = "manual"
    rule.verified = True   # người dạy = đã có human-in-the-loop → coi như đã duyệt
    STORE.add_rule(rule)
    return asdict(rule)


@app.get("/api/memory")
def get_memory():
    return {"rules": [asdict(r) for r in STORE.all_rules()]}


@app.get("/api/stats")
def get_stats():
    """Thống kê ký ức theo thời gian (content-free): rule + lượt chạy từ metrics log."""
    return dashboard(STORE)


@app.post("/api/upload")
async def upload_files(files: List[UploadFile] = File(...)):
    """Nhận file (mọi định dạng) → tri giác thành text dùng chung cho council.
    Trả token + metadata; dùng token trong /api/run qua field file_tokens."""
    out = []
    for f in files:
        data = await f.read()
        try:
            out.append(FILES.add_upload(f.filename or "file", data))
        except ValueError as e:
            raise HTTPException(status_code=413, detail=str(e))
    return {"files": out}


@app.get("/api/files/{token}")
def download_file(token: str):
    """Tải file (đã upload hoặc artifact xuất ra) theo token."""
    got = FILES.read(token)
    if not got:
        raise HTTPException(status_code=404, detail="Không thấy file.")
    data, filename, media = got
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.post("/api/memory/{rule_id}/verify")
def verify_memory(rule_id: str, req: VerifyReq):
    if not STORE.set_verified(rule_id, req.verified):
        raise HTTPException(status_code=404, detail="Không thấy rule.")
    return {"ok": True, "id": rule_id, "verified": req.verified}


@app.post("/api/memory/{rule_id}/demote")
def demote_memory(rule_id: str, req: DemoteReq):
    """Hạ (demoted=true) hoặc khôi phục (demoted=false) một rule thủ công."""
    if not STORE.set_demoted(rule_id, req.demoted, req.score):
        raise HTTPException(status_code=404, detail="Không thấy rule.")
    return {"ok": True, "id": rule_id, "demoted": req.demoted}


@app.patch("/api/memory/{rule_id}")
def edit_memory(rule_id: str, req: EditRuleReq):
    if not STORE.update_guidance(rule_id, req.guidance):
        raise HTTPException(status_code=400, detail="Sửa thất bại (id sai hoặc guidance rỗng).")
    return {"ok": True, "id": rule_id}


@app.delete("/api/memory/{rule_id}")
def delete_memory(rule_id: str):
    if rule_id == "all":
        STORE.clear()
        return {"ok": True, "cleared": True}
    if not STORE.remove(rule_id):
        raise HTTPException(status_code=404, detail="Không thấy rule.")
    return {"ok": True}


# ── OpenAI-compatible endpoints (Theosis as a drop-in model) ─────────────────
@app.get("/v1/models")
def list_models():
    return {
        "object": "list",
        "data": [{"id": "theosis-v1", "object": "model", "owned_by": "theosis"}],
    }


async def _openai_sse(user: str, history: list, req: "ChatReq"):
    """Phát SSE theo định dạng streaming của OpenAI (chat.completion.chunk)."""
    cid = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    def chunk(delta=None, finish=None) -> str:
        body = {
            "id": cid, "object": "chat.completion.chunk", "created": created, "model": req.model,
            "choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}],
        }
        return "data: " + json.dumps(body, ensure_ascii=False) + "\n\n"

    yield chunk({"role": "assistant"})
    mem_guidance, _ = _fetch_memory(_default_memory(req.use_memory), user, _default_verified_only(req.verified_only))
    try:
        async for tok in theosis_stream(
            user, SLOTS, AGGREGATOR, max_rounds=_default_rounds(req.max_rounds),
            history=history, summarize_history=_default_summarize(req.summarize_history),
            max_tokens_budget=req.max_tokens_budget,
            auditors_per_answer=_default_auditors(req.auditors_per_answer),
            use_executor=_default_executor(req.use_executor),
            strategy=_default_strategy(req.strategy),
            use_router=_default_router(req.use_router),
            router=_default_router_name(req.router),
            memory_rules=mem_guidance,
            auto_learn=_default_auto_learn(req.auto_learn),
        ):
            yield chunk({"content": tok})
    except Exception as exc:  # surface upstream errors inside the stream
        yield chunk({"content": f"\n[error: {exc}]"})
    yield chunk(finish="stop")
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatReq):
    history, user = _split_history(req.messages)
    if req.stream:
        return StreamingResponse(_openai_sse(user, history, req), media_type="text/event-stream")
    max_rounds = _default_rounds(req.max_rounds)
    use_memory = _default_memory(req.use_memory)
    auto_learn = _default_auto_learn(req.auto_learn)
    mem_guidance, applied = _fetch_memory(use_memory, user, _default_verified_only(req.verified_only))
    try:
        final, trail = await theosis(
            user, SLOTS, AGGREGATOR, max_rounds=max_rounds, history=history,
            summarize_history=_default_summarize(req.summarize_history),
            max_tokens_budget=req.max_tokens_budget,
            auditors_per_answer=_default_auditors(req.auditors_per_answer),
            use_executor=_default_executor(req.use_executor),
            strategy=_default_strategy(req.strategy),
            use_router=_default_router(req.use_router),
            router=_default_router_name(req.router),
            memory_rules=mem_guidance,
            auto_learn=auto_learn,
        )
    except Exception as exc:
        return JSONResponse(
            status_code=502,
            content={"error": {"message": str(exc), "type": "upstream_error"}},
        )
    if auto_learn:
        _persist_learned(trail)
    if use_memory:
        if applied:
            STORE.bump_uses([r.id for r in applied])
        log_metrics(trail)
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
