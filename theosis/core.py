"""Theosis orchestration core: fan-out -> cross-audit -> patch -> merge.

The engine is provider-agnostic: every model is reached through an
OpenAI-compatible /chat/completions call, so slots can mix providers freely.
An optional `on_event` async callback streams progress for live UIs.
"""
from __future__ import annotations
import asyncio
from typing import Awaitable, Callable, Dict, List, Optional, Tuple
import httpx
from .models import ModelSlot
from .prompts import MERGE_PROMPT, PATCH_SYS, RUBRIC

EventCb = Optional[Callable[[dict], Awaitable[None]]]

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
    return f"(mock·{slot.name}) Trả lời thử cho: \"{snippet}\" — output giả lập từ model «{slot.model}»."


async def _call(
    client: httpx.AsyncClient,
    slot: ModelSlot,
    messages: List[dict],
    temperature: float = 0.7,
) -> str:
    if slot.is_mock:
        await asyncio.sleep(0.25)  # giả lập độ trễ để thấy luồng stream
        return _mock_completion(slot, messages)
    resp = await client.post(
        f"{slot.base_url}/chat/completions",
        headers={"Authorization": f"Bearer {slot.api_key}"},
        json={"model": slot.model, "messages": messages, "temperature": temperature},
        timeout=180,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ── Phases ──────────────────────────────────────────────────────────────────
async def ask_slot(client: httpx.AsyncClient, slot: ModelSlot, request: str) -> str:
    prompt = slot.middlelayer.pre(request)
    messages: List[dict] = []
    if slot.middlelayer.system:
        messages.append({"role": "system", "content": slot.middlelayer.system})
    messages.append({"role": "user", "content": prompt})
    raw = await _call(client, slot, messages, temperature=0.7)
    return slot.middlelayer.post(raw)


async def audit(client: httpx.AsyncClient, auditor: ModelSlot, request: str, answer: str) -> str:
    messages = [
        {"role": "system", "content": RUBRIC},
        {"role": "user", "content": f"REQUEST:\n{request}\n\nANSWER TO AUDIT:\n{answer}"},
    ]
    return await _call(client, auditor, messages, temperature=0.3)


async def patch(
    client: httpx.AsyncClient, slot: ModelSlot, request: str, answer: str, critique: str
) -> str:
    messages = [
        {"role": "system", "content": PATCH_SYS},
        {
            "role": "user",
            "content": f"REQUEST:\n{request}\n\nYOUR ANSWER:\n{answer}\n\nCRITIQUE:\n{critique}",
        },
    ]
    return await _call(client, slot, messages, temperature=0.5)


async def merge(
    client: httpx.AsyncClient,
    aggregator: ModelSlot,
    request: str,
    answers: Dict[str, str],
    critiques: Dict[str, str],
) -> str:
    blob = "\n\n".join(f"### {n}\n{a}" for n, a in answers.items())
    notes = "\n\n".join(f"### Audit of {n}\n{c}" for n, c in critiques.items())
    messages = [
        {"role": "system", "content": MERGE_PROMPT},
        {
            "role": "user",
            "content": f"REQUEST:\n{request}\n\nREFINED ANSWERS:\n{blob}\n\nAUDIT NOTES:\n{notes}",
        },
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
) -> Tuple[str, dict]:
    """Run the full Theosis pipeline and return (final_answer, trail).

    trail = {
        "fanout": {slot: answer},
        "rounds": [{"pairs": {target: auditor}, "critiques": {...}, "patched": {...}}],
        "final": str,
    }
    """
    enabled = [s for s in slots if s.enabled]
    if not enabled:
        raise ValueError("Cần ít nhất 1 slot được bật.")
    by_name = {s.name: s for s in enabled}
    trail: dict = {"fanout": {}, "rounds": [], "final": None}

    async def emit(event: dict) -> None:
        if on_event:
            await on_event(event)

    async with httpx.AsyncClient() as client:
        # Phase 1 — fan-out (parallel)
        await emit({"type": "fanout_start", "slots": [s.name for s in enabled]})
        outs = await asyncio.gather(*[ask_slot(client, s, request) for s in enabled])
        answers: Dict[str, str] = {s.name: o for s, o in zip(enabled, outs)}
        trail["fanout"] = dict(answers)
        await emit({"type": "fanout_done", "answers": dict(answers)})

        # With a single slot there is nothing to cross-audit.
        rounds = max_rounds if len(enabled) >= 2 else 0
        last_crit: Dict[str, str] = {}

        for rnd in range(rounds):
            await emit({"type": "round_start", "round": rnd})

            # Phase 2 — cross-audit (parallel)
            ap = audit_pairs(enabled)
            pairs_info = {target.name: auditor.name for target, auditor in ap}
            crits = await asyncio.gather(
                *[audit(client, auditor, request, answers[target.name]) for target, auditor in ap]
            )
            last_crit = {target.name: c for (target, _), c in zip(ap, crits)}
            await emit(
                {"type": "audit_done", "round": rnd, "pairs": pairs_info, "critiques": dict(last_crit)}
            )

            # Phase 3 — patch (parallel)
            patched = await asyncio.gather(
                *[patch(client, by_name[name], request, answers[name], last_crit[name]) for name in answers]
            )
            answers = {name: p for name, p in zip(answers, patched)}
            trail["rounds"].append(
                {"pairs": pairs_info, "critiques": dict(last_crit), "patched": dict(answers)}
            )
            await emit({"type": "patch_done", "round": rnd, "answers": dict(answers)})

        # Phase 4 — V1 runs a fixed number of rounds.
        # Upgrade hook: break early on convergence (semantic similarity between
        # consecutive rounds) or when a token budget is exceeded.

        # Phase 5 — merge
        await emit({"type": "merge_start"})

        if len(enabled) >= 2:
            final = await merge(client, aggregator, request, answers, last_crit)
        else:
            final = next(iter(answers.values()))

        trail["final"] = final
        await emit({"type": "done", "final": final, "trail": trail})
        return final, trail
