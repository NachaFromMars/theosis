"""Thống kê ký ức theo thời gian — đọc store (rule) + metrics log (content-free).

Tất cả nguồn đã content-free từ thiết kế: rule chỉ có guidance trừu tượng + metadata;
metrics log chỉ có số (task_type, tokens, scores, ts). Module này thuần (stdlib),
không gọi model.

CLI:  python -m theosis.stats
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Optional

from .memory import MemoryStore


def rule_stats(store: MemoryStore) -> dict:
    rules = store.all_rules()
    by_source: dict = {}
    verified = unverified = demoted = helpful = harmful = neutral = total_uses = 0
    by_day: dict = {}
    for r in rules:
        by_source[r.source] = by_source.get(r.source, 0) + 1
        verified += 1 if r.verified else 0
        unverified += 0 if r.verified else 1
        demoted += 1 if r.demoted else 0
        if r.score > 0.0001:
            helpful += 1
        elif r.score < -0.0001:
            harmful += 1
        else:
            neutral += 1
        total_uses += r.uses
        day = (r.created_at or "")[:10]
        if day:
            by_day[day] = by_day.get(day, 0) + 1

    top = sorted(rules, key=lambda r: -r.uses)
    return {
        "total": len(rules),
        "verified": verified, "unverified": unverified, "demoted": demoted,
        "helpful": helpful, "harmful": harmful, "neutral": neutral,
        "by_source": by_source,
        "total_uses": total_uses,
        "top_used": [
            {"guidance": (r.guidance[:60] + "…") if len(r.guidance) > 61 else r.guidance,
             "uses": r.uses, "source": r.source, "demoted": r.demoted}
            for r in top[:5] if r.uses > 0
        ],
        "created_by_day": [{"date": d, "count": by_day[d]} for d in sorted(by_day)],
    }


def _read_metrics(metrics_path: Optional[str]):
    p = Path(metrics_path or os.environ.get("THEOSIS_METRICS", "metrics.local.jsonl"))
    if not p.exists():
        return []
    recs = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            recs.append(json.loads(line))
        except Exception:
            pass
    return recs


def run_stats(metrics_path: Optional[str] = None) -> dict:
    recs = _read_metrics(metrics_path)
    total = len(recs)
    by_day: dict = {}
    score_by_day: dict = {}
    task_types: dict = {}
    total_tokens = 0
    for r in recs:
        day = (r.get("ts") or "")[:10]
        if day:
            by_day[day] = by_day.get(day, 0) + 1
        tt = r.get("task_type") or "—"
        task_types[tt] = task_types.get(tt, 0) + 1
        total_tokens += (r.get("cost") or {}).get("total_tokens", 0)
        scores = r.get("scores") or []
        if scores and day:
            score_by_day.setdefault(day, []).append(sum(scores) / len(scores))
    return {
        "total_runs": total,
        "runs_by_day": [{"date": d, "count": by_day[d]} for d in sorted(by_day)],
        "avg_tokens": round(total_tokens / total) if total else 0,
        "total_tokens": total_tokens,
        "task_types": task_types,
        "avg_score_by_day": [{"date": d, "avg": round(sum(v) / len(v), 3)}
                             for d, v in sorted(score_by_day.items())],
    }


def dashboard(store: MemoryStore, metrics_path: Optional[str] = None) -> dict:
    return {"rules": rule_stats(store), "runs": run_stats(metrics_path)}


def format_dashboard(d: dict) -> str:
    r, run = d["rules"], d["runs"]
    bar = "═" * 60
    L = [bar, "  THEOSIS — THỐNG KÊ KÝ ỨC", bar]
    L.append(f"  Rule: {r['total']} tổng · {r['verified']} đã duyệt · "
             f"{r['unverified']} chưa duyệt · {r['demoted']} bị hạ")
    L.append(f"  Sức khỏe: {r['helpful']} giúp · {r['neutral']} trung tính · {r['harmful']} hại")
    L.append(f"  Lượt áp dụng (tổng uses): {r['total_uses']}")
    if r["by_source"]:
        src = " · ".join(f"{k}:{v}" for k, v in sorted(r["by_source"].items(), key=lambda x: -x[1]))
        L.append(f"  Theo nguồn: {src}")
    if r["top_used"]:
        L.append("  ── Hay dùng nhất ──")
        for t in r["top_used"]:
            flag = " [bị hạ]" if t["demoted"] else ""
            L.append(f"    {t['uses']:>3}×  {t['guidance']}{flag}")
    L.append("  " + "─" * 56)
    L.append(f"  Lượt chạy: {run['total_runs']} · ~{run['avg_tokens']} tok/lần · {run['total_tokens']} tok tổng")
    if run["task_types"]:
        tt = " · ".join(f"{k}:{v}" for k, v in sorted(run["task_types"].items(), key=lambda x: -x[1]))
        L.append(f"  Loại task: {tt}")
    if run["runs_by_day"]:
        L.append("  ── Lượt chạy theo ngày ──")
        mx = max(x["count"] for x in run["runs_by_day"]) or 1
        for x in run["runs_by_day"][-14:]:
            blocks = "█" * max(1, round(x["count"] / mx * 30))
            L.append(f"    {x['date']}  {blocks} {x['count']}")
    L.append(bar)
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(prog="theosis.stats", description="Thống kê ký ức theo thời gian")
    ap.add_argument("--json", action="store_true", help="in JSON thay vì bảng")
    args = ap.parse_args()
    store = MemoryStore()
    d = dashboard(store)
    print(json.dumps(d, ensure_ascii=False, indent=2) if args.json else format_dashboard(d))


if __name__ == "__main__":
    main()
