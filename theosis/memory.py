"""Immune Memory — kho rule *content-free* + log metrics *content-free*.

NGUYÊN TẮC CỨNG: chỉ lưu rule ĐÃ trừu tượng hoá (bài học chung). KHÔNG bao giờ
ghi query / answer / correction gốc xuống đĩa. Raw content chỉ xuất hiện thoáng
qua trong prompt rule-maker (lúc sinh rule) rồi bị bỏ — không persist. Nhờ vậy
sau này nối EdenTheosis không phải retrofit privacy.

Module này thuần (chỉ stdlib + file I/O), không gọi model — để test được và
tránh import vòng với core.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


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


@dataclass
class Rule:
    """Một bài học trừu tượng. KHÔNG chứa nội dung gốc của user."""
    guidance: str
    task_type: str = "other"
    keywords: List[str] = field(default_factory=list)
    source: str = "manual"
    id: str = ""
    created_at: str = ""
    uses: int = 0
    verified: bool = False  # chưa duyệt; gate cho Eden sau này
    score: float = 0.0      # hiệu ứng biên đo từ eval (>0 giúp, <0 hại); 0 = chưa rõ
    demoted: bool = False   # eval chứng minh có hại → loại khỏi việc tiêm (vẫn giữ để review)

    def __post_init__(self):
        if not self.id:
            self.id = "r_" + uuid.uuid4().hex[:10]
        if not self.created_at:
            self.created_at = _now()


def parse_rule(text: Optional[str], source: str = "manual") -> Optional[Rule]:
    """Đổi text model thành Rule. Ưu tiên JSON; fallback dùng text làm guidance."""
    raw = _extract_json(text)
    if isinstance(raw, dict) and raw.get("guidance"):
        kws = raw.get("keywords") or []
        if not isinstance(kws, list):
            kws = []
        return Rule(
            guidance=str(raw["guidance"]).strip()[:400],
            task_type=str(raw.get("task_type") or "other").lower(),
            keywords=[str(k).strip()[:40] for k in kws][:6],
            source=source,
        )
    t = (text or "").strip()
    return Rule(guidance=t[:400], source=source) if t else None


class MemoryStore:
    """Kho rule file-backed (JSON). Mặc định `memory.local.json` (đã gitignore)."""

    def __init__(self, path: Optional[str] = None):
        self.path = Path(path or os.environ.get("THEOSIS_MEMORY", "memory.local.json"))
        self._rules: List[Rule] = []
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._rules = [Rule(**r) for r in data.get("rules", [])]
            except Exception:
                self._rules = []

    def _save(self):
        self.path.write_text(
            json.dumps({"rules": [asdict(r) for r in self._rules]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add_rule(self, rule: Rule, dedup: bool = False) -> Rule:
        """Thêm rule. dedup=True: nếu đã có rule trùng guidance thì tăng uses, không nhân bản
        (giảm nhiễu khi cùng một bài học bị học lại nhiều lần)."""
        if dedup:
            for r in self._rules:
                if r.guidance == rule.guidance:
                    r.uses += 1
                    self._save()
                    return r
        self._rules.append(rule)
        self._save()
        return rule

    def all_rules(self) -> List[Rule]:
        return list(self._rules)

    def relevant(self, task_type: Optional[str] = None, request: str = "",
                 limit: int = 5, verified_only: bool = False) -> List[Rule]:
        """Lấy rule liên quan: ưu tiên trùng task_type, rồi keyword trong request.

        verified_only=True → chỉ xét rule đã được duyệt (cổng chất lượng).
        Rule bị 'demoted' (eval chứng minh hại) luôn bị loại khỏi việc tiêm."""
        pool = [r for r in self._rules if not r.demoted]
        if verified_only:
            pool = [r for r in pool if r.verified]
        req = (request or "").lower()
        scored = []
        for r in pool:
            s = 0
            if task_type and r.task_type == task_type:
                s += 2
            if any(k and k.lower() in req for k in r.keywords):
                s += 1
            scored.append((s, r))
        scored = [t for t in scored if t[0] > 0] or ([] if task_type or req else scored)
        scored.sort(key=lambda x: -x[0])
        return [r for _, r in scored[:limit]]

    def set_verified(self, rule_id: str, verified: bool = True) -> bool:
        for r in self._rules:
            if r.id == rule_id:
                r.verified = bool(verified)
                self._save()
                return True
        return False

    def set_demoted(self, rule_id: str, demoted: bool = True, score: Optional[float] = None) -> bool:
        for r in self._rules:
            if r.id == rule_id:
                r.demoted = bool(demoted)
                if score is not None:
                    r.score = float(score)
                self._save()
                return True
        return False

    def set_score(self, rule_id: str, score: float) -> bool:
        for r in self._rules:
            if r.id == rule_id:
                r.score = float(score)
                self._save()
                return True
        return False

    def update_guidance(self, rule_id: str, guidance: str) -> bool:
        g = str(guidance).strip()[:400]
        if not g:
            return False
        for r in self._rules:
            if r.id == rule_id:
                r.guidance = g
                self._save()
                return True
        return False

    def remove(self, rule_id: str) -> bool:
        n = len(self._rules)
        self._rules = [r for r in self._rules if r.id != rule_id]
        if len(self._rules) != n:
            self._save()
            return True
        return False

    def clear(self):
        self._rules = []
        self._save()

    def bump_uses(self, ids) -> None:
        ids = set(ids)
        changed = False
        for r in self._rules:
            if r.id in ids:
                r.uses += 1
                changed = True
        if changed:
            self._save()


def format_rules_for_prompt(rules: List[Rule]) -> str:
    """Khối bài học để chèn vào prompt (chỉ guidance — content-free)."""
    return "\n".join(f"- {r.guidance}" for r in rules)


def log_metrics(trail: dict, path: Optional[str] = None) -> dict:
    """Ghi log *content-free* mỗi lần chạy (cho eval / A-B). KHÔNG ghi nội dung."""
    p = Path(path or os.environ.get("THEOSIS_METRICS", "metrics.local.jsonl"))
    route = trail.get("route") or {}
    rec = {
        "ts": _now(),
        "task_type": route.get("task_type"),
        "strategy": route.get("strategy"),
        "n_models": len(trail.get("fanout") or {}),   # số model (tên), không phải nội dung
        "rounds": len(trail.get("rounds") or []),
        "stopped_reason": trail.get("stopped_reason"),
        "cost": trail.get("cost") or {},
        "scores": list((trail.get("scores") or {}).values()),
    }
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec
