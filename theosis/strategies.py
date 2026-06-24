"""Council strategies — "ai chấm ai". Mỗi chiến lược trả về danh sách
(target, [auditors]) để engine chạy. Cắm thêm chiến lược = thêm một hàm
cùng chữ ký rồi đăng ký vào STRATEGIES.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from .models import ModelSlot

Assignment = List[Tuple[ModelSlot, List[ModelSlot]]]
Strategy = Callable[[List[ModelSlot], int], Assignment]


def round_robin(enabled: List[ModelSlot], k: int = 1) -> Assignment:
    """Mỗi câu trả lời bị k slot kế tiếp soi (k được clamp vào [1, n-1])."""
    n = len(enabled)
    if n <= 1:
        return [(enabled[i], []) for i in range(n)]
    k = max(1, min(k, n - 1))
    return [(enabled[i], [enabled[(i + j) % n] for j in range(1, k + 1)]) for i in range(n)]


def all_vs_all(enabled: List[ModelSlot], k: int = 1) -> Assignment:
    """Mỗi câu trả lời bị MỌI model khác soi. (k bị bỏ qua.) Kỹ nhất, tốn nhất."""
    n = len(enabled)
    if n <= 1:
        return [(enabled[i], []) for i in range(n)]
    return [(t, [a for a in enabled if a is not t]) for t in enabled]


def star(enabled: List[ModelSlot], k: int = 1) -> Assignment:
    """Một giám khảo trung tâm (slot đầu) soi tất cả; chính nó do á quân soi."""
    n = len(enabled)
    if n <= 1:
        return [(enabled[i], []) for i in range(n)]
    critic = enabled[0]
    out: Assignment = []
    for t in enabled:
        out.append((t, [enabled[1]] if t is critic else [critic]))
    return out


STRATEGIES: Dict[str, Strategy] = {
    "round_robin": round_robin,
    "all_vs_all": all_vs_all,
    "star": star,
}


def get_strategy(name: str) -> Strategy:
    return STRATEGIES.get((name or "round_robin").lower(), round_robin)
