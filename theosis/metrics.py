"""Metrics & helpers: completion result, cost/token meter, convergence, scoring."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict


@dataclass
class CompletionResult:
    """Chuẩn trả về của một lời gọi model — đồng nhất cho mọi provider."""
    text: str
    model: str = ""
    usage: Dict[str, int] = field(default_factory=dict)  # prompt_tokens / completion_tokens / total_tokens
    latency_ms: int = 0


# Giá tham khảo (USD / 1M token) — input, output. CHỈNH theo bảng giá thực tế.
COST_TABLE = {
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.6),
    "claude-opus-4-8": (15.0, 75.0),
    "claude-3.5-sonnet": (3.0, 15.0),
    "deepseek-chat": (0.27, 1.10),
    "grok-4": (5.0, 15.0),
    "llama-3.3-70b-versatile": (0.0, 0.0),
}
DEFAULT_PRICE = (1.0, 3.0)


def estimate_cost(model: str, usage: Dict[str, int]) -> float:
    p_in, p_out = COST_TABLE.get((model or "").strip(), DEFAULT_PRICE)
    pt = usage.get("prompt_tokens", 0)
    ct = usage.get("completion_tokens", 0)
    return pt / 1_000_000 * p_in + ct / 1_000_000 * p_out


def new_cost_acc() -> dict:
    return {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "usd": 0.0}


def add_cost(acc: dict, model: str, usage: Dict[str, int]) -> None:
    pt = usage.get("prompt_tokens", 0)
    ct = usage.get("completion_tokens", 0)
    total = usage.get("total_tokens") or (pt + ct)
    acc["calls"] += 1
    acc["prompt_tokens"] += pt
    acc["completion_tokens"] += ct
    acc["total_tokens"] += total
    acc["usd"] = round(acc["usd"] + estimate_cost(model, usage), 6)


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a or "", b or "").ratio()


def avg_similarity(prev: Dict[str, str], cur: Dict[str, str]) -> float:
    """Độ tương đồng trung bình giữa hai bộ câu trả lời (để phát hiện hội tụ)."""
    keys = [k for k in cur if k in prev]
    if not keys:
        return 0.0
    return sum(similarity(prev[k], cur[k]) for k in keys) / len(keys)


_VERDICT = re.compile(r"VERDICT:\s*(strong|good|mixed|weak|poor)", re.IGNORECASE)
_SCORE = {"strong": 1.0, "good": 1.0, "mixed": 0.5, "weak": 0.2, "poor": 0.2}


def verdict_score(critique: str) -> float:
    """Đổi VERDICT trong critique thành điểm tin cậy (0..1). Không rõ → 0.5."""
    m = _VERDICT.search(critique or "")
    return _SCORE.get(m.group(1).lower(), 0.5) if m else 0.5


def approx_tokens(messages) -> int:
    """Ước số token thô cho mock (≈ ký tự / 4)."""
    chars = sum(len(m.get("content", "")) for m in messages)
    return max(1, chars // 4)
