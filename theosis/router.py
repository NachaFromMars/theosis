"""Smart Router — phần thuần: dựng roster, parse & validate kế hoạch định tuyến.

Tách khỏi core (không gọi model ở đây) để: (1) tránh import vòng, (2) test được
mà không cần mạng. core dựng prompt + gọi model, rồi đưa text vào `parse_plan`.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import List, Optional

from .strategies import STRATEGIES

TASK_TYPES = {"code", "math", "factual", "reasoning", "creative", "other"}


@dataclass
class RoutePlan:
    task_type: str = "other"
    slots: List[str] = field(default_factory=list)
    strategy: str = "round_robin"
    rounds: int = 2
    use_executor: bool = False
    reason: str = ""
    routed: bool = False  # True nếu do model quyết; False nếu fallback


def build_roster(enabled) -> str:
    """Mô tả ngắn từng model cho router chọn: '- name: persona'."""
    lines = []
    for s in enabled:
        persona = (getattr(s.middlelayer, "system", "") or s.model or "").strip().replace("\n", " ")
        if len(persona) > 80:
            persona = persona[:77] + "..."
        lines.append(f"- {s.name}: {persona or s.model}")
    return "\n".join(lines)


def _extract_json(text: Optional[str]):
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _as_bool(v, default: bool) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    return str(v).strip().lower() in ("true", "1", "yes", "y", "có")


def parse_plan(
    text: Optional[str],
    enabled,
    *,
    def_strategy: str = "round_robin",
    def_rounds: int = 2,
    def_executor: bool = False,
) -> RoutePlan:
    """Đổi text model thành RoutePlan đã validate. Lỗi/thiếu → dùng default (an toàn)."""
    names = [s.name for s in enabled]
    nameset = set(names)
    raw = _extract_json(text)

    if not isinstance(raw, dict):
        return RoutePlan(
            task_type="other", slots=list(names), strategy=def_strategy,
            rounds=def_rounds, use_executor=def_executor,
            reason="fallback: không đọc được kế hoạch", routed=False,
        )

    # slots: chỉ giữ tên có thật; rỗng -> tất cả
    sel = [n for n in (raw.get("slots") or []) if n in nameset]
    if not sel:
        sel = list(names)

    # strategy: không hợp lệ -> default
    strat = str(raw.get("strategy") or def_strategy).lower()
    if strat not in STRATEGIES:
        strat = def_strategy

    # rounds: clamp 0..3
    try:
        rounds = int(raw.get("rounds", def_rounds))
    except Exception:
        rounds = def_rounds
    rounds = max(0, min(rounds, 3))

    task = str(raw.get("task_type") or "other").lower()
    if task not in TASK_TYPES:
        task = "other"

    return RoutePlan(
        task_type=task,
        slots=sel,
        strategy=strat,
        rounds=rounds,
        use_executor=_as_bool(raw.get("use_executor"), def_executor),
        reason=str(raw.get("reason") or "")[:200],
        routed=True,
    )
