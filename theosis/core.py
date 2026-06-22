"""Theosis orchestration core: fan-out -> cross-audit -> patch -> merge.

V2: resilient (retry + per-slot timeout + drop-on-failure), cost/token metering,
convergence early-stop, token-budget guard, and confidence-weighted merge.
All models are reached through an OpenAI-compatible /chat/completions call, so
slots can mix providers freely. An optional `on_event` async callback streams
progress for live UIs.
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

import httpx

from .metrics import (
    CompletionResult,
    add_cost,
    approx_tokens,
    avg_similarity,
    new_cost_acc,
    verdict_score,
)
from .models import ModelSlot
from .prompts import MERGE_PROMPT, PATCH_SYS, RUBRIC

EventCb = Optional[Callable[[dict], Awaitable[None]]]

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_TRANSIENT = (httpx.TimeoutException, httpx.TransportError)


# ── Mock provider: lets the whole pipeline run without any API key ──────────
def _mock_completion(slot: ModelSlot, messages: List[dict]) -> str:
    system = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
    user = messages[-1]["content"]
    snippet = " ".join(user.split())[:90]
    if "ADVERSARIAL AUDITOR" in system:
        return (
            "VERDICT: mixed\n"
            "ISSUES:\n"
            f"- [MED] (mock) câu trả lời của «{slot.name}» thiếu ví dụ cụ thể -> thêm một ví dụ.\n"
            "- [LOW] (mock) phần mở đầu hơi dài -> rút gọn.\n"
            "MISSING: một câu chốt rõ ràng.\n"
            "KEEP: cách đặt vấn đề mạch lạc."
        )
    if "SYNTHESIZER" in system:
        return (
            "(mock·merge) Đây là câu trả lời hợp nhất giả lập từ council. "
            "Gắn API key thật vào config.yaml để Theosis tổng hợp nội dung thật."
        )
    if "Revise YOUR answer" in system:
        return f"(mock·{slot.name}) Bản đã vá (giả lập) cho model «{slot.model}»."
    return f"(mock·{slot.name}) Trả lời thử cho: “{snippet}” — output giả lập từ model «{slot.model}»."


# ── Resilient low-level call ────────────────────────────────────────────────
async def _call(
    client: httpx.AsyncClient,
    slot: ModelSlot,
    messages: List[dict],
    temperature: float = 0.7,
    attempts: int = 2,
    timeout: float = 90.0,
) -> CompletionResult:
    if slot.is_mock:
        await asyncio.sleep(0.2)  # giả lập độ trễ để thấy luồng stream
        text = _mock_completion(slot, messages)
        pt = approx_tokens(messages)
        ct = max(1, len(text) // 4)
        return CompletionResult(text=text, model=slot.model,
                                usage={"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct},
                                latency_ms=200)

    last_exc: Optional[Exception] = None
    for attempt in range(attempts):
        t0 = time.perf_counter()
        try:
            resp = await client.post(
                f"{slot.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {slot.api_key}"},
                json={"model": slot.model, "messages": messages, "temperature": temperature},
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
            return CompletionResult(text=text, model=slot.model, usage=usage,
                                    latency_ms=int((time.perf_counter() - t0) * 1000))
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            if exc.response.status_code in _RETRYABLE_STATUS and attempt < attempts - 1:
                await asyncio.sleep(0.4 * (attempt + 1))
                continue
            raise
        except _TRANSIENT as exc:
            last_exc = exc
            if attempt < attempts - 1:
                await asyncio.sleep(0.4 * (attempt + 1))
                continue
            raise
    raise last_exc  # pragma: no cover


def _errmsg(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return f"{type(exc).__name__}: {exc}"


# ── Phases (each returns a CompletionResult) ─────────────────────────────────
async def ask_slot(client: httpx.AsyncClient, slot: ModelSlot, request: str) -> CompletionResult:
    prompt = slot.middlelayer.pre(request)
    messages: List[dict] = []
    if slot.middlelayer.system:
        messages.append({"role": "system", "content": slot.middlelayer.system})
    messages.append({"role": "user", "content": prompt})
    res = await _call(client, slot, messages, temperature=0.7)
    res.text = slot.middlelayer.post(res.text)
    return res


async def audit(client: httpx.AsyncClient, auditor: ModelSlot, request: str, answer: str) -> CompletionResult:
    messages = [
        {"role": "system", "content": RUBRIC},
        {"role": "user", "content": f"REQUEST:\n{request}\n\nANSWER TO AUDIT:\n{answer}"},
    ]
    return await _call(client, auditor, messages, temperature=0.3)


async def patch(client: httpx.AsyncClient, slot: ModelSlot, request: str, answer: str, critique: str) -> CompletionResult:
    messages = [
        {"role": "system", "content": PATCH_SYS},
        {"role": "user", "content": f"REQUEST:\n{request}\n\nYOUR ANSWER:\n{answer}\n\nCRITIQUE:\n{critique}"},
    ]
    return await _call(client, slot, messages, temperature=0.5)


async def merge(
    client: httpx.AsyncClient,
    aggregator: ModelSlot,
    request: str,
    answers: Dict[str, str],
    critiques: Dict[str, str],
    scores: Optional[Dict[str, float]] = None,
) -> CompletionResult:
    blob = "\n\n".join(f"### {n}\n{a}" for n, a in answers.items())
    notes = "\n\n".join(f"### Audit of {n}\n{c}" for n, c in critiques.items())
    ratings = ""
    if scores:
        ratings = "\n\nAUDITOR RATINGS (0..1, higher = stronger — prioritise accordingly):\n" + \
            "\n".join(f"- {n}: {scores.get(n, 0.5):.2f}" for n in answers)
    messages = [
        {"role": "system", "content": MERGE_PROMPT},
        {"role": "user", "content": f"REQUEST:\n{request}\n\nREFINED ANSWERS:\n{blob}\n\nAUDIT NOTES:\n{notes}{ratings}"},
    ]
    return await _call(client, aggregator, messages, temperature=0.4)


def audit_pairs(enabled: List[ModelSlot]) -> List[Tuple[ModelSlot, ModelSlot]]:
    """Round-robin: slot i is audited by the next slot. Generalises to N slots."""
    n = len(enabled)
    return [(enabled[i], enabled[(i + 1) % n]) for i in range(n)]


# ── Orchestrator ─────────────────────────────────────────────────────────────
async def theosis(
    request: str,
    slots: List[ModelSlot],
    aggregator: ModelSlot,
    max_rounds: int = 2,
    on_event: EventCb = None,
    max_tokens_budget: Optional[int] = None,
    converge_threshold: float = 0.97,
) -> Tuple[str, dict]:
    """Run the full Theosis pipeline and return (final_answer, trail).

    Resilient: a slot that errors is dropped (event ``slot_error``) instead of
    crashing the batch. Stops early on convergence or token budget.
    """
    enabled = [s for s in slots if s.enabled]
    if not enabled:
        raise ValueError("Cần ít nhất 1 slot được bật.")

    cost = new_cost_acc()
    trail: dict = {"fanout": {}, "rounds": [], "final": None, "cost": cost,
                   "scores": {}, "stopped_reason": None}

    async def emit(event: dict) -> None:
        if on_event:
            await on_event(event)

    def over_budget() -> bool:
        return max_tokens_budget is not None and cost["total_tokens"] >= max_tokens_budget

    async with httpx.AsyncClient() as client:
        # Phase 1 — fan-out (parallel, resilient)
        await emit({"type": "fanout_start", "slots": [s.name for s in enabled]})
        results = await asyncio.gather(
            *[ask_slot(client, s, request) for s in enabled], return_exceptions=True
        )
        answers: Dict[str, str] = {}
        alive: List[ModelSlot] = []
        for s, res in zip(enabled, results):
            if isinstance(res, Exception):
                await emit({"type": "slot_error", "slot": s.name, "phase": "fanout", "message": _errmsg(res)})
            else:
                add_cost(cost, s.model, res.usage)
                answers[s.name] = res.text
                alive.append(s)
        if not answers:
            raise RuntimeError("Tất cả model đều lỗi ở fan-out.")
        enabled = alive
        by_name = {s.name: s for s in enabled}
        trail["fanout"] = dict(answers)
        await emit({"type": "fanout_done", "answers": dict(answers), "cost": dict(cost)})

        rounds = max_rounds if len(enabled) >= 2 else 0
        last_crit: Dict[str, str] = {}

        for rnd in range(rounds):
            if over_budget():
                trail["stopped_reason"] = "budget"
                await emit({"type": "budget_hit", "tokens": cost["total_tokens"]})
                break

            await emit({"type": "round_start", "round": rnd})

            # Phase 2 — cross-audit (parallel, resilient)
            ap = audit_pairs(enabled)
            pairs_info = {target.name: auditor.name for target, auditor in ap}
            audit_results = await asyncio.gather(
                *[audit(client, auditor, request, answers[target.name]) for target, auditor in ap],
                return_exceptions=True,
            )
            last_crit = {}
            for (target, auditor), res in zip(ap, audit_results):
                if isinstance(res, Exception):
                    await emit({"type": "slot_error", "slot": auditor.name, "phase": "audit", "message": _errmsg(res)})
                else:
                    add_cost(cost, auditor.model, res.usage)
                    last_crit[target.name] = res.text
            await emit({"type": "audit_done", "round": rnd, "pairs": pairs_info,
                        "critiques": dict(last_crit), "cost": dict(cost)})

            # Phase 3 — patch (parallel, resilient) — only targets that got a critique
            prev = dict(answers)
            targets = [name for name in answers if name in last_crit]
            patch_results = await asyncio.gather(
                *[patch(client, by_name[name], request, answers[name], last_crit[name]) for name in targets],
                return_exceptions=True,
            )
            for name, res in zip(targets, patch_results):
                if isinstance(res, Exception):
                    await emit({"type": "slot_error", "slot": name, "phase": "patch", "message": _errmsg(res)})
                else:
                    add_cost(cost, by_name[name].model, res.usage)
                    answers[name] = res.text
            trail["rounds"].append({"pairs": pairs_info, "critiques": dict(last_crit), "patched": dict(answers)})
            await emit({"type": "patch_done", "round": rnd, "answers": dict(answers), "cost": dict(cost)})

            # Phase 4 — convergence early-stop
            sim = avg_similarity(prev, answers)
            if sim >= converge_threshold:
                trail["stopped_reason"] = "converged"
                await emit({"type": "converged", "round": rnd, "similarity": round(sim, 3)})
                break

        # Confidence scores from the latest critiques
        scores = {name: verdict_score(last_crit.get(name, "")) for name in answers}
        trail["scores"] = scores

        # Phase 5 — weighted merge
        await emit({"type": "merge_start"})
        if len(enabled) >= 2:
            mres = await merge(client, aggregator, request, answers, last_crit, scores)
            add_cost(cost, aggregator.model, mres.usage)
            final = mres.text
        else:
            final = next(iter(answers.values()))
        trail["final"] = final
        trail["cost"] = dict(cost)
        await emit({"type": "done", "final": final, "trail": trail, "cost": dict(cost), "scores": scores})
        return final, trail
