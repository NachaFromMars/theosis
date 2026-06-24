"""Theosis orchestration core: fan-out -> cross-audit -> patch -> merge.

V2: resilient calls, cost/token metering, convergence early-stop, token-budget
guard, confidence-weighted merge, multi-auditor (M-of-N), pluggable strategies,
optional code/arithmetic executor, and **streaming** of the final answer.

`theosis()` returns (final, trail). `theosis_stream()` is an async generator
that yields the final answer token-by-token (the merge call is streamed from the
aggregator). Both share `_deliberate()` for the fan-out/audit/patch phases. All
models are reached through an OpenAI-compatible /chat/completions call.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import asdict
from typing import Awaitable, AsyncIterator, Callable, Dict, List, Optional, Tuple

import httpx

from .metrics import (
    CompletionResult,
    add_cost,
    approx_tokens,
    avg_similarity,
    new_cost_acc,
    verdict_score,
)
from .memory import parse_rule
from .models import ModelSlot
from .prompts import MEMORY_PREAMBLE, MERGE_PROMPT, PATCH_SYS, ROUTER_SYS, RULEMAKER_SYS, RUBRIC, SUMMARIZER_SYS
from .router import build_roster, parse_plan
from .strategies import get_strategy, round_robin as audit_assignments
from .verifiers import evidence_text, run_verifiers

EventCb = Optional[Callable[[dict], Awaitable[None]]]

__all__ = [
    "theosis", "theosis_stream", "audit_pairs", "audit_assignments",
    "ask_slot", "audit", "patch", "merge", "merge_stream",
]

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_TRANSIENT = (httpx.TimeoutException, httpx.TransportError)


# ── Mock provider: lets the whole pipeline run without any API key ──────────
def _mock_completion(slot: ModelSlot, messages: List[dict]) -> str:
    system = " ".join(m["content"] for m in messages if m.get("role") == "system")
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
    if "DISPATCHER" in system:
        import json as _json
        roster_names = re.findall(r"^- ([^\s:]+):", user, re.MULTILINE)
        picked = roster_names[:2] if len(roster_names) >= 2 else roster_names
        wants_code = any(w in user.lower() for w in ("code", "python", "hàm", "function", "thuật toán"))
        return _json.dumps({
            "task_type": "code" if wants_code else "other",
            "slots": picked,
            "strategy": "round_robin",
            "rounds": 1,
            "use_executor": wants_code,
            "reason": "(mock) chọn 2 model đầu cho gọn",
        }, ensure_ascii=False)
    if "distill a SINGLE reusable lesson" in system or "RULEMAKER" in system:
        import json as _json
        return _json.dumps({
            "guidance": "(mock) Kiểm chứng giả định trước khi chốt; nêu rõ điều kiện biên.",
            "task_type": "other",
            "keywords": ["kiểm chứng", "điều kiện biên"],
        }, ensure_ascii=False)
    if "compress an EARLIER part of a conversation" in system or "SUMMARIZER" in system:
        return "(mock·tóm tắt) Người dùng đã cung cấp thông tin và đặt các câu hỏi nối tiếp ở các lượt trước."
    if "Revise YOUR answer" in system:
        return f"(mock·{slot.name}) Bản đã vá (giả lập) cho model «{slot.model}»."
    mem = "[ký-ức] " if "BÀI HỌC ĐÃ GHI NHỚ" in system else ""
    multi = "[đa-lượt] " if any(m.get("role") == "assistant" for m in messages) else ""
    return f"(mock·{slot.name}) {mem}{multi}Trả lời thử cho: “{snippet}” — output giả lập từ model «{slot.model}»."


def _history_messages(history: Optional[List[dict]]) -> List[dict]:
    """Lọc lịch sử hội thoại thành các message {role, content} hợp lệ. Thuần."""
    out: List[dict] = []
    for m in history or []:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if role in ("user", "assistant", "system") and content:
            out.append({"role": role, "content": content})
    return out


def _prepare_history(history: Optional[List[dict]], max_turns: int = 8,
                     max_chars: int = 4000) -> List[dict]:
    """Cắt cửa sổ lịch sử: giữ N lượt gần nhất, mỗi lượt cắt theo ký tự (chặn phình token)."""
    h = _history_messages(history)[-max_turns:]
    out = []
    for m in h:
        c = m["content"]
        if len(c) > max_chars:
            c = c[:max_chars] + "…[cắt]"
        out.append({"role": m["role"], "content": c})
    return out


async def _summarize_history(client: httpx.AsyncClient, slot: ModelSlot, turns: List[dict]):
    """Nén các lượt CŨ thành một tóm tắt ngắn (giữ ngữ cảnh dài mà không phình token).
    Trả (summary_text, result)."""
    convo = "\n".join(f"{m['role']}: {m['content']}" for m in turns)
    messages = [
        {"role": "system", "content": SUMMARIZER_SYS},
        {"role": "user", "content": f"CONVERSATION TO SUMMARIZE:\n{convo}"},
    ]
    res = await _call(client, slot, messages, temperature=0.3)
    return res.text, res


async def _prepare_history_smart(client: httpx.AsyncClient, slot: ModelSlot,
                                 history: Optional[List[dict]], max_turns: int,
                                 summarize: bool):
    """Như _prepare_history nhưng nếu summarize=True và lịch sử dài hơn cửa sổ:
    nén phần CŨ (ngoài cửa sổ) thành 1 message tóm tắt, đặt trước N lượt gần nhất.
    Trả (effective_history, summary_result_or_None)."""
    full = _history_messages(history)
    window = _prepare_history(full, max_turns)
    if not summarize or len(full) <= max_turns:
        return window, None
    older = full[:-max_turns]
    summary, res = await _summarize_history(client, slot, older)
    summary = (summary or "").strip()
    if not summary:
        return window, res
    head = {"role": "system", "content": f"TÓM TẮT CÁC LƯỢT TRƯỚC:\n{summary}"}
    return [head] + window, res


def _chunk_words(text: str) -> List[str]:
    """Cắt text thành các mẩu nhỏ (mô phỏng token) để stream cho mock / single-slot."""
    return re.findall(r"\S+\s*", text or "") or [text or ""]


# ── Resilient low-level call (non-stream) ───────────────────────────────────
async def _call(
    client: httpx.AsyncClient,
    slot: ModelSlot,
    messages: List[dict],
    temperature: float = 0.7,
    attempts: int = 2,
    timeout: float = 90.0,
) -> CompletionResult:
    if slot.is_mock:
        await asyncio.sleep(0.2)
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


async def _call_stream(
    client: httpx.AsyncClient,
    slot: ModelSlot,
    messages: List[dict],
    temperature: float = 0.4,
    timeout: float = 120.0,
) -> AsyncIterator[str]:
    """Gọi model với stream=True, yield từng mẩu nội dung (content delta)."""
    if slot.is_mock:
        for tok in _chunk_words(_mock_completion(slot, messages)):
            await asyncio.sleep(0.02)
            yield tok
        return
    async with client.stream(
        "POST",
        f"{slot.base_url}/chat/completions",
        headers={"Authorization": f"Bearer {slot.api_key}"},
        json={"model": slot.model, "messages": messages, "temperature": temperature, "stream": True},
        timeout=timeout,
    ) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                delta = json.loads(payload)["choices"][0]["delta"].get("content")
            except Exception:
                continue
            if delta:
                yield delta


def _errmsg(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return f"{type(exc).__name__}: {exc}"


# ── Phases ───────────────────────────────────────────────────────────────────
async def ask_slot(
    client: httpx.AsyncClient, slot: ModelSlot, request: str,
    lessons: Optional[str] = None, history: Optional[List[dict]] = None,
) -> CompletionResult:
    prompt = slot.middlelayer.pre(request)
    messages: List[dict] = []
    if slot.middlelayer.system:
        messages.append({"role": "system", "content": slot.middlelayer.system})
    if lessons:
        messages.append({"role": "system", "content": f"{MEMORY_PREAMBLE}\n{lessons}"})
    messages.extend(_history_messages(history))
    messages.append({"role": "user", "content": prompt})
    res = await _call(client, slot, messages, temperature=0.7)
    res.text = slot.middlelayer.post(res.text)
    return res


async def make_rule(
    client: httpx.AsyncClient, model_slot: ModelSlot, request: str, bad_answer: str, correction: str
):
    """Gọi rule-maker -> Rule trừu tượng (content-free). Trả (rule, result).

    Raw content chỉ nằm trong prompt tạm này, KHÔNG được persist. Chỉ rule trả về
    (đã trừu tượng hoá) mới được lưu bởi caller.
    """
    messages = [
        {"role": "system", "content": RULEMAKER_SYS},
        {"role": "user", "content": (
            f"REQUEST:\n{request}\n\nFLAWED ANSWER:\n{bad_answer}\n\n"
            f"CORRECTION / WHAT WAS WRONG:\n{correction}"
        )},
    ]
    res = await _call(client, model_slot, messages, temperature=0.3)
    return parse_rule(res.text, source="learned"), res


async def audit(client: httpx.AsyncClient, auditor: ModelSlot, request: str, answer: str) -> CompletionResult:
    messages = [
        {"role": "system", "content": RUBRIC},
        {"role": "user", "content": f"REQUEST:\n{request}\n\nANSWER TO AUDIT:\n{answer}"},
    ]
    return await _call(client, auditor, messages, temperature=0.3)


async def patch(client: httpx.AsyncClient, slot: ModelSlot, request: str, answer: str,
                critique: str, history: Optional[List[dict]] = None) -> CompletionResult:
    messages = [{"role": "system", "content": PATCH_SYS}]
    messages.extend(_history_messages(history))
    messages.append({"role": "user", "content": f"REQUEST:\n{request}\n\nYOUR ANSWER:\n{answer}\n\nCRITIQUE:\n{critique}"})
    return await _call(client, slot, messages, temperature=0.5)


def _merge_messages(
    request: str,
    answers: Dict[str, str],
    critiques: Dict[str, str],
    scores: Optional[Dict[str, float]] = None,
    evidence: Optional[Dict[str, dict]] = None,
    history: Optional[List[dict]] = None,
) -> List[dict]:
    blob = "\n\n".join(f"### {n}\n{a}" for n, a in answers.items())
    notes = "\n\n".join(f"### Audit of {n}\n{c}" for n, c in critiques.items())
    ratings = ""
    if scores:
        ratings = "\n\nAUDITOR RATINGS (0..1, higher = stronger — prioritise accordingly):\n" + \
            "\n".join(f"- {n}: {scores.get(n, 0.5):.2f}" for n in answers)
    ev_block = ""
    if evidence:
        evs = [f"- {n}: {e['summary']}" for n, e in evidence.items() if e.get("status") != "na"]
        if evs:
            ev_block = "\n\nGROUND-TRUTH CHECKS (code đã chạy / số đã kiểm — tin cái này):\n" + "\n".join(evs)
    messages = [{"role": "system", "content": MERGE_PROMPT}]
    messages.extend(_history_messages(history))
    messages.append({"role": "user", "content": f"REQUEST:\n{request}\n\nREFINED ANSWERS:\n{blob}\n\nAUDIT NOTES:\n{notes}{ratings}{ev_block}"})
    return messages


async def merge(
    client: httpx.AsyncClient,
    aggregator: ModelSlot,
    request: str,
    answers: Dict[str, str],
    critiques: Dict[str, str],
    scores: Optional[Dict[str, float]] = None,
    evidence: Optional[Dict[str, dict]] = None,
    history: Optional[List[dict]] = None,
) -> CompletionResult:
    return await _call(client, aggregator,
                       _merge_messages(request, answers, critiques, scores, evidence, history),
                       temperature=0.4)


async def merge_stream(
    client: httpx.AsyncClient,
    aggregator: ModelSlot,
    request: str,
    answers: Dict[str, str],
    critiques: Dict[str, str],
    scores: Optional[Dict[str, float]] = None,
    evidence: Optional[Dict[str, dict]] = None,
    history: Optional[List[dict]] = None,
) -> AsyncIterator[str]:
    async for tok in _call_stream(client, aggregator, _merge_messages(request, answers, critiques, scores, evidence, history), temperature=0.4):
        yield tok


async def _verify_all(answers: Dict[str, str], timeout: float) -> Dict[str, dict]:
    names = list(answers)
    results = await asyncio.gather(
        *[asyncio.to_thread(run_verifiers, answers[n], True, timeout) for n in names]
    )
    return dict(zip(names, results))


def _pick_failure(answers: Dict[str, str], evidence: Dict[str, dict]):
    """Chọn một câu trả lời bị executor (ground truth) báo FAIL, để auto-learn. Thuần."""
    for name, ev in (evidence or {}).items():
        if ev.get("status") == "fail" and name in answers:
            return name, answers[name], ev.get("summary", "")
    return None


def _learn_signal(answers, evidence, scores, last_reviews, trail, low_conf_threshold=0.35):
    """Chọn MỘT tín hiệu 'biết là cần học', ưu tiên nguồn MẠNH → YẾU. Thuần.

    Trả (source, slot_name, answer, correction) hoặc None.
      1) executor_fail   — ground truth bắt câu sai            (mạnh)
      2) low_confidence  — cả hội đồng tự chấm thấp            (yếu)
      3) no_converge     — chạy hết ≥2 vòng mà vẫn bất đồng    (yếu)
    """
    fail = _pick_failure(answers, evidence)
    if fail:
        name, ans, summary = fail
        return ("auto:executor_fail", name, ans, f"Executor (ground truth) báo lỗi: {summary}")

    if not scores:
        return None
    best = max(scores, key=lambda n: scores[n])
    best_score = scores[best]

    if best_score < low_conf_threshold:
        revs = last_reviews.get(best) or []
        crit = " ".join(r.get("critique", "") for r in revs)[:300]
        return ("auto:low_confidence", best, answers.get(best, ""),
                f"Cả hội đồng chấm thấp (điểm tốt nhất {best_score:.2f}). Critique tiêu biểu: {crit}")

    rounds_ran = len(trail.get("rounds") or [])
    if trail.get("stopped_reason") is None and rounds_ran >= 2:
        return ("auto:no_converge", best, answers.get(best, ""),
                f"Hội đồng không hội tụ sau {rounds_ran} vòng — câu trả lời còn bất đồng (task khó/mơ hồ).")
    return None


def _pick_router(slots: List[ModelSlot], aggregator: ModelSlot, name: Optional[str]) -> ModelSlot:
    """Chọn slot làm router: theo tên nếu có, không thì dùng aggregator."""
    by = {s.name: s for s in slots}
    return by[name] if name and name in by else aggregator


async def _run_router(client, request, enabled, router_slot, def_strategy, def_rounds, def_executor):
    messages = [
        {"role": "system", "content": ROUTER_SYS},
        {"role": "user", "content": f"REQUEST:\n{request}\n\nROSTER:\n{build_roster(enabled)}"},
    ]
    res = None
    try:
        res = await _call(client, router_slot, messages, temperature=0.2)
        text = res.text
    except Exception:
        text = None
    plan = parse_plan(text, enabled, def_strategy=def_strategy, def_rounds=def_rounds, def_executor=def_executor)
    return plan, res


def audit_pairs(enabled: List[ModelSlot]) -> List[Tuple[ModelSlot, ModelSlot]]:
    """Round-robin 1:1 — slot i is audited by the next slot. (k=1 case.)"""
    n = len(enabled)
    return [(enabled[i], enabled[(i + 1) % n]) for i in range(n)]


# ── Deliberation (fan-out -> audit -> patch -> score); shared by both runners ─
async def _deliberate(
    client: httpx.AsyncClient,
    request: str,
    slots: List[ModelSlot],
    aggregator: ModelSlot,
    *,
    max_rounds: int,
    on_event: EventCb,
    max_tokens_budget: Optional[int],
    converge_threshold: float,
    auditors_per_answer: int,
    use_executor: bool,
    executor_timeout: float,
    strategy: str,
    use_router: bool = False,
    router: Optional[str] = None,
    memory_rules: Optional[List[str]] = None,
    auto_learn: bool = False,
    low_confidence_threshold: float = 0.35,
    history: Optional[List[dict]] = None,
):
    enabled = [s for s in slots if s.enabled]
    if not enabled:
        raise ValueError("Cần ít nhất 1 slot được bật.")

    cost = new_cost_acc()
    trail: dict = {"fanout": {}, "rounds": [], "final": None, "cost": cost,
                   "scores": {}, "evidence": {}, "route": None, "memory": None,
                   "learned": None, "stopped_reason": None}

    async def emit(event: dict) -> None:
        if on_event:
            await on_event(event)

    def over_budget() -> bool:
        return max_tokens_budget is not None and cost["total_tokens"] >= max_tokens_budget

    # Phase 0 — smart router (opt-in): để một model quyết model + chiến lược + vòng + executor
    if use_router and enabled:
        router_slot = _pick_router(enabled, aggregator, router)
        plan, rres = await _run_router(client, request, enabled, router_slot,
                                       strategy, max_rounds, use_executor)
        if rres is not None:
            add_cost(cost, router_slot.model, rres.usage)
        chosen = [s for s in enabled if s.name in set(plan.slots)]
        if chosen:
            enabled = chosen
        strategy, max_rounds, use_executor = plan.strategy, plan.rounds, plan.use_executor
        trail["route"] = {
            "task_type": plan.task_type, "slots": [s.name for s in enabled],
            "strategy": strategy, "rounds": max_rounds, "use_executor": use_executor,
            "reason": plan.reason, "routed": plan.routed,
        }
        await emit({"type": "route", **trail["route"]})

    # Phase 1 — fan-out (parallel, resilient)
    lessons = None
    if memory_rules:
        lessons = "\n".join(f"- {g}" for g in memory_rules)
        trail["memory"] = list(memory_rules)
        await emit({"type": "memory", "rules": list(memory_rules)})
    await emit({"type": "fanout_start", "slots": [s.name for s in enabled]})
    results = await asyncio.gather(*[ask_slot(client, s, request, lessons, history) for s in enabled], return_exceptions=True)
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

    evidence: Dict[str, dict] = {}
    if use_executor:
        evidence = await _verify_all(answers, executor_timeout)
        trail["evidence"] = dict(evidence)
        await emit({"type": "evidence", "phase": "fanout",
                    "results": {n: {"status": e["status"], "summary": e["summary"]} for n, e in evidence.items()}})

    rounds = max_rounds if len(enabled) >= 2 else 0
    last_crit: Dict[str, str] = {}
    last_reviews: Dict[str, List[dict]] = {}

    for rnd in range(rounds):
        if over_budget():
            trail["stopped_reason"] = "budget"
            await emit({"type": "budget_hit", "tokens": cost["total_tokens"]})
            break

        await emit({"type": "round_start", "round": rnd})

        # Phase 2 — cross-audit (chiến lược cắm được, parallel, resilient)
        assignments = get_strategy(strategy)(enabled, auditors_per_answer)
        flat = [(target, auditor) for target, auditors in assignments for auditor in auditors]
        aug_answers = {}
        for name in answers:
            appx = evidence_text(evidence.get(name)) if evidence else ""
            aug_answers[name] = answers[name] + (f"\n\n[EVIDENCE]\n{appx}" if appx else "")
        audit_results = await asyncio.gather(
            *[audit(client, auditor, request, aug_answers[target.name]) for target, auditor in flat],
            return_exceptions=True,
        )
        reviews: Dict[str, List[dict]] = {t.name: [] for t in enabled}
        for (target, auditor), res in zip(flat, audit_results):
            if isinstance(res, Exception):
                await emit({"type": "slot_error", "slot": auditor.name, "phase": "audit", "message": _errmsg(res)})
            else:
                add_cost(cost, auditor.model, res.usage)
                reviews[target.name].append(
                    {"auditor": auditor.name, "critique": res.text, "verdict": verdict_score(res.text)}
                )

        last_reviews = {t: revs for t, revs in reviews.items() if revs}
        last_crit = {
            t: "\n\n".join(f"— Theo {r['auditor']}:\n{r['critique']}" for r in revs)
            for t, revs in last_reviews.items()
        }
        pairs_info = {t: [r["auditor"] for r in revs] for t, revs in last_reviews.items()}
        review_events = [
            {"target": t, "auditor": r["auditor"], "critique": r["critique"], "verdict": r["verdict"]}
            for t, revs in last_reviews.items() for r in revs
        ]
        await emit({"type": "audit_done", "round": rnd, "reviews": review_events,
                    "pairs": pairs_info, "critiques": dict(last_crit), "cost": dict(cost)})

        # Phase 3 — patch (parallel, resilient) — only targets that got a critique
        prev = dict(answers)
        targets = [name for name in answers if name in last_crit]
        patch_results = await asyncio.gather(
            *[patch(client, by_name[name], request, answers[name], last_crit[name], history) for name in targets],
            return_exceptions=True,
        )
        for name, res in zip(targets, patch_results):
            if isinstance(res, Exception):
                await emit({"type": "slot_error", "slot": name, "phase": "patch", "message": _errmsg(res)})
            else:
                add_cost(cost, by_name[name].model, res.usage)
                answers[name] = res.text
        trail["rounds"].append({
            "pairs": pairs_info,
            "critiques": dict(last_crit),
            "reviews": {t: [dict(r) for r in revs] for t, revs in last_reviews.items()},
            "patched": dict(answers),
        })
        await emit({"type": "patch_done", "round": rnd, "answers": dict(answers), "cost": dict(cost)})

        if use_executor:
            evidence = await _verify_all(answers, executor_timeout)
            trail["evidence"] = dict(evidence)
            await emit({"type": "evidence", "phase": f"round{rnd}",
                        "results": {n: {"status": e["status"], "summary": e["summary"]} for n, e in evidence.items()}})

        # Phase 4 — convergence early-stop
        sim = avg_similarity(prev, answers)
        if sim >= converge_threshold:
            trail["stopped_reason"] = "converged"
            await emit({"type": "converged", "round": rnd, "similarity": round(sim, 3)})
            break

    # Confidence scores: average auditor verdict, điều chỉnh theo ground-truth
    scores: Dict[str, float] = {}
    for name in answers:
        revs = last_reviews.get(name)
        s = round(sum(r["verdict"] for r in revs) / len(revs), 3) if revs else 0.5
        ev = evidence.get(name)
        if ev and ev.get("status") == "fail":
            s = min(s, 0.15)
        elif ev and ev.get("status") == "pass":
            s = max(s, 0.7)
        scores[name] = round(s, 3)
    trail["scores"] = scores

    # Phase 5 — auto-learn (opt-in): khi có tín hiệu 'biết là cần học' (executor sai,
    # hội đồng chấm thấp, hoặc không hội tụ) → chưng cất rule content-free, chưa duyệt.
    # Best-effort — lỗi ở đây không phá run.
    if auto_learn:
        sig = _learn_signal(answers, evidence, scores, last_reviews, trail, low_confidence_threshold)
        if sig:
            source, name, bad, correction = sig
            try:
                rule, lres = await make_rule(client, aggregator, request, bad, correction)
                if lres is not None:
                    add_cost(cost, aggregator.model, lres.usage)
                if rule is not None:
                    rule.source = source
                    trail["learned"] = [asdict(rule)]
                    await emit({"type": "learned", "source": source.split(":")[-1],
                                "slot": name, "rule": asdict(rule)})
            except Exception:
                pass

    return answers, last_crit, scores, evidence, enabled, trail, cost


# ── Orchestrators ────────────────────────────────────────────────────────────
async def theosis(
    request: str,
    slots: List[ModelSlot],
    aggregator: ModelSlot,
    max_rounds: int = 2,
    on_event: EventCb = None,
    max_tokens_budget: Optional[int] = None,
    converge_threshold: float = 0.97,
    auditors_per_answer: int = 1,
    use_executor: bool = False,
    executor_timeout: float = 6.0,
    strategy: str = "round_robin",
    use_router: bool = False,
    router: Optional[str] = None,
    memory_rules: Optional[List[str]] = None,
    auto_learn: bool = False,
    low_confidence_threshold: float = 0.35,
    history: Optional[List[dict]] = None,
    max_history_turns: int = 8,
    summarize_history: bool = False,
) -> Tuple[str, dict]:
    """Run the full pipeline and return (final_answer, trail)."""
    async def emit(event: dict) -> None:
        if on_event:
            await on_event(event)

    async with httpx.AsyncClient() as client:
        hist, _sres = await _prepare_history_smart(client, aggregator, history, max_history_turns, summarize_history)
        answers, last_crit, scores, evidence, enabled, trail, cost = await _deliberate(
            client, request, slots, aggregator, max_rounds=max_rounds, on_event=on_event,
            max_tokens_budget=max_tokens_budget, converge_threshold=converge_threshold,
            auditors_per_answer=auditors_per_answer, use_executor=use_executor,
            executor_timeout=executor_timeout, strategy=strategy,
            use_router=use_router, router=router, memory_rules=memory_rules,
            auto_learn=auto_learn, low_confidence_threshold=low_confidence_threshold,
            history=hist,
        )
        if _sres is not None:
            add_cost(cost, aggregator.model, _sres.usage)
        await emit({"type": "merge_start"})
        if len(enabled) >= 2:
            mres = await merge(client, aggregator, request, answers, last_crit, scores, evidence, hist)
            add_cost(cost, aggregator.model, mres.usage)
            final = mres.text
        else:
            final = next(iter(answers.values()))
        trail["final"] = final
        trail["cost"] = dict(cost)
        await emit({"type": "done", "final": final, "trail": trail, "cost": dict(cost), "scores": scores})
        return final, trail


async def theosis_stream(
    request: str,
    slots: List[ModelSlot],
    aggregator: ModelSlot,
    max_rounds: int = 2,
    on_event: EventCb = None,
    max_tokens_budget: Optional[int] = None,
    converge_threshold: float = 0.97,
    auditors_per_answer: int = 1,
    use_executor: bool = False,
    executor_timeout: float = 6.0,
    strategy: str = "round_robin",
    use_router: bool = False,
    router: Optional[str] = None,
    memory_rules: Optional[List[str]] = None,
    auto_learn: bool = False,
    low_confidence_threshold: float = 0.35,
    history: Optional[List[dict]] = None,
    max_history_turns: int = 8,
    summarize_history: bool = False,
) -> AsyncIterator[str]:
    """Run the pipeline and stream the final answer token-by-token.

    The deliberation phases run first (you can observe them via ``on_event``);
    then the merge is streamed from the aggregator and yielded chunk by chunk.
    """
    async with httpx.AsyncClient() as client:
        hist, _sres = await _prepare_history_smart(client, aggregator, history, max_history_turns, summarize_history)
        answers, last_crit, scores, evidence, enabled, trail, _cost = await _deliberate(
            client, request, slots, aggregator, max_rounds=max_rounds, on_event=on_event,
            max_tokens_budget=max_tokens_budget, converge_threshold=converge_threshold,
            auditors_per_answer=auditors_per_answer, use_executor=use_executor,
            executor_timeout=executor_timeout, strategy=strategy,
            use_router=use_router, router=router, memory_rules=memory_rules,
            auto_learn=auto_learn, low_confidence_threshold=low_confidence_threshold,
            history=hist,
        )
        if on_event:
            await on_event({"type": "merge_start"})
        if len(enabled) >= 2:
            async for tok in merge_stream(client, aggregator, request, answers, last_crit, scores, evidence, hist):
                yield tok
        else:
            for tok in _chunk_words(next(iter(answers.values()))):
                yield tok
