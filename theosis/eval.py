"""Eval harness — đo ký ức (immune memory) thực sự GIÚP hay HẠI, có hệ thống.

Chạy mỗi task HAI lần với cùng cấu hình: baseline (tắt ký ức) vs treatment (bật
ký ức), rồi so sánh. Tín hiệu mạnh nhất là `expect_contains` (ground truth do
người viết task đặt) và executor pass-rate; điểm thẩm định (LLM chấm) chỉ là
proxy yếu — báo cáo nói rõ điều đó.

CLI:
    python -m theosis.eval tasks.json [--trials N] [--rounds R] [--no-executor]
"""
from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .config import load_config
from .core import theosis
from .memory import MemoryStore


@dataclass
class EvalTask:
    prompt: str
    task_type: Optional[str] = None
    expect_contains: Optional[str] = None   # ground truth: câu trả lời cuối PHẢI chứa chuỗi này


@dataclass
class EvalReport:
    n_tasks: int
    n_trials: int
    has_ground_truth: bool
    baseline: dict
    treatment: dict
    deltas: dict
    verdict: str
    per_task: List[dict] = field(default_factory=list)


def load_tasks(path) -> List[EvalTask]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("tasks", [])
    return [
        EvalTask(prompt=t["prompt"], task_type=t.get("task_type"),
                 expect_contains=t.get("expect_contains"))
        for t in data
    ]


def _run_metrics(task: EvalTask, final: str, trail: dict) -> dict:
    scores = list((trail.get("scores") or {}).values())
    ev = trail.get("evidence") or {}
    ran = [e for e in ev.values() if e.get("status") in ("pass", "fail")]
    exec_pass = (sum(1 for e in ran if e["status"] == "pass") / len(ran)) if ran else None
    check = task.expect_contains.lower() in (final or "").lower() if task.expect_contains else None
    return {
        "check": check,
        "score": round(sum(scores) / len(scores), 3) if scores else None,
        "tokens": (trail.get("cost") or {}).get("total_tokens", 0),
        "rounds": len(trail.get("rounds") or []),
        "exec_pass": exec_pass,
    }


def _aggregate(runs: List[dict]) -> dict:
    if not runs:
        return {"n": 0, "check_pass_rate": None, "avg_score": None, "avg_tokens": 0, "avg_rounds": 0}
    checks = [r["check"] for r in runs if r["check"] is not None]
    scores = [r["score"] for r in runs if r["score"] is not None]
    return {
        "n": len(runs),
        "check_pass_rate": round(sum(1 for c in checks if c) / len(checks), 3) if checks else None,
        "avg_score": round(sum(scores) / len(scores), 3) if scores else None,
        "avg_tokens": round(sum(r["tokens"] for r in runs) / len(runs)),
        "avg_rounds": round(sum(r["rounds"] for r in runs) / len(runs), 2),
    }


def _deltas(b: dict, t: dict) -> dict:
    def d(k):
        return None if b.get(k) is None or t.get(k) is None else round(t[k] - b[k], 3)
    return {k: d(k) for k in ("check_pass_rate", "avg_score", "avg_tokens", "avg_rounds")}


def _verdict(b: dict, t: dict, has_gt: bool, n: int) -> str:
    if has_gt and b.get("check_pass_rate") is not None and t.get("check_pass_rate") is not None:
        d, metric = t["check_pass_rate"] - b["check_pass_rate"], "tỉ lệ đúng (ground truth)"
    elif b.get("avg_score") is not None and t.get("avg_score") is not None:
        d, metric = t["avg_score"] - b["avg_score"], "điểm thẩm định (LLM chấm — proxy yếu)"
    else:
        return "Không đủ dữ liệu để kết luận."
    if d > 0.001:
        verd = f"Ký ức GIÚP (+{d:.3f} theo {metric})"
    elif d < -0.001:
        verd = f"Ký ức HẠI ({d:.3f} theo {metric})"
    else:
        verd = f"Không khác biệt rõ ({metric})"
    if n < 10 or not has_gt:
        verd += "  ⚠ mẫu nhỏ/thiếu ground-truth — chưa đủ ý nghĩa thống kê (tăng --trials, thêm expect_contains)."
    return verd


async def run_eval(tasks, slots, aggregator, store=None, *, rounds=2,
                   use_executor=True, trials=1, on_progress=None) -> EvalReport:
    base_runs: List[dict] = []
    treat_runs: List[dict] = []
    per_task: List[dict] = []

    for ti, task in enumerate(tasks):
        b_acc, t_acc = [], []
        for _ in range(trials):
            # arm A — baseline (không ký ức)
            fb, tb = await theosis(task.prompt, slots, aggregator,
                                   max_rounds=rounds, use_executor=use_executor)
            mb = _run_metrics(task, fb, tb)
            b_acc.append(mb)
            base_runs.append(mb)

            # arm B — treatment (ký ức liên quan, nếu có store)
            rules = None
            if store is not None:
                rel = store.relevant(request=task.prompt)
                rules = [r.guidance for r in rel] or None
            ft, tt = await theosis(task.prompt, slots, aggregator,
                                   max_rounds=rounds, use_executor=use_executor, memory_rules=rules)
            mt = _run_metrics(task, ft, tt)
            t_acc.append(mt)
            treat_runs.append(mt)

        per_task.append({"prompt": task.prompt, "expect_contains": task.expect_contains,
                         "baseline": _aggregate(b_acc), "treatment": _aggregate(t_acc)})
        if on_progress:
            on_progress(ti + 1, len(tasks))

    base_agg, treat_agg = _aggregate(base_runs), _aggregate(treat_runs)
    has_gt = any(t.expect_contains for t in tasks)
    return EvalReport(
        n_tasks=len(tasks), n_trials=trials, has_ground_truth=has_gt,
        baseline=base_agg, treatment=treat_agg, deltas=_deltas(base_agg, treat_agg),
        verdict=_verdict(base_agg, treat_agg, has_gt, len(tasks) * trials), per_task=per_task,
    )


def format_report(rep: EvalReport) -> str:
    bar = "═" * 64

    def pct(v):
        return "—" if v is None else f"{v * 100:.0f}%"

    def num(v, dp=3):
        return "—" if v is None else f"{v:.{dp}f}"

    def row(name, a):
        return (f"  {name:<11} đúng:{pct(a['check_pass_rate']):>5}   "
                f"điểm:{num(a['avg_score']):>6}   tok:{a['avg_tokens']:>6}   vòng:{a['avg_rounds']}")

    d = rep.deltas
    dcpr = "—" if d["check_pass_rate"] is None else f"{d['check_pass_rate'] * 100:+.0f}%"
    dsc = "—" if d["avg_score"] is None else f"{d['avg_score']:+.3f}"
    dtok = "—" if d["avg_tokens"] is None else f"{d['avg_tokens']:+}"

    lines = [
        bar,
        f"  THEOSIS EVAL — {rep.n_tasks} task × {rep.n_trials} lượt"
        + ("   (có ground truth)" if rep.has_ground_truth else "   (không ground truth)"),
        bar,
        row("Baseline", rep.baseline),
        row("Ký ức", rep.treatment),
        "  " + "─" * 60,
        f"  Δ (ký ức−base) đúng:{dcpr:>5}   điểm:{dsc:>6}   tok:{dtok:>6}",
        bar,
        "  → " + rep.verdict,
        bar,
    ]
    return "\n".join(lines)


@dataclass
class RuleEval:
    id: str
    guidance: str
    source: str
    delta_check: Optional[float]
    delta_score: Optional[float]
    marginal: Optional[float]   # thước đo dùng để quyết định (check nếu có ground truth, không thì score)
    demoted: bool
    n: int


@dataclass
class RuleEvalReport:
    n_rules: int
    n_tasks: int
    n_trials: int
    has_ground_truth: bool
    baseline: dict
    per_rule: List[RuleEval] = field(default_factory=list)


async def eval_rules(tasks, slots, aggregator, store, *, rounds=2,
                     use_executor=True, trials=1, on_progress=None) -> RuleEvalReport:
    """Đo hiệu ứng biên TỪNG rule bằng ablation: baseline (không ký ức) vs CHỈ rule đó.

    Chi phí O(rules × tasks × trials) lời gọi — đây là công cụ offline, không phải đường chạy nóng.
    """
    rules = store.all_rules()
    has_gt = any(t.expect_contains for t in tasks)

    base_runs = []
    for task in tasks:
        for _ in range(trials):
            fb, tb = await theosis(task.prompt, slots, aggregator, max_rounds=rounds, use_executor=use_executor)
            base_runs.append(_run_metrics(task, fb, tb))
    base = _aggregate(base_runs)

    per_rule = []
    for ri, rule in enumerate(rules):
        truns = []
        for task in tasks:
            for _ in range(trials):
                ft, tt = await theosis(task.prompt, slots, aggregator, max_rounds=rounds,
                                       use_executor=use_executor, memory_rules=[rule.guidance])
                truns.append(_run_metrics(task, ft, tt))
        d = _deltas(base, _aggregate(truns))
        marg = d["check_pass_rate"] if (has_gt and d["check_pass_rate"] is not None) else d["avg_score"]
        per_rule.append(RuleEval(
            id=rule.id, guidance=rule.guidance, source=rule.source,
            delta_check=d["check_pass_rate"], delta_score=d["avg_score"],
            marginal=marg, demoted=rule.demoted, n=len(truns),
        ))
        if on_progress:
            on_progress(ri + 1, len(rules))

    return RuleEvalReport(n_rules=len(rules), n_tasks=len(tasks), n_trials=trials,
                          has_ground_truth=has_gt, baseline=base, per_rule=per_rule)


def auto_demote(store, report: RuleEvalReport, threshold: float = -0.05) -> List[str]:
    """Hạ rule có marginal < threshold (chứng minh HẠI). Cập nhật score cho mọi rule.
    Chỉ HẠ tự động — KHÔNG tự khôi phục (đó là quyết định của người duyệt)."""
    demoted = []
    for re in report.per_rule:
        if re.marginal is None:
            continue
        sc = round(re.marginal, 3)
        if re.marginal < threshold:
            store.set_demoted(re.id, True, score=sc)
            demoted.append(re.id)
        else:
            store.set_score(re.id, sc)
    return demoted


def format_rule_report(rep: RuleEvalReport, threshold: float = -0.05) -> str:
    bar = "═" * 70
    lines = [
        bar,
        f"  THEOSIS — HIỆU ỨNG BIÊN TỪNG RULE · {rep.n_rules} rule × {rep.n_tasks} task × {rep.n_trials} lượt"
        + ("   (ground truth)" if rep.has_ground_truth else "   (proxy điểm — yếu)"),
        bar,
    ]
    if not rep.per_rule:
        lines.append("  (kho ký ức trống — chưa có rule để đánh giá)")
        lines.append(bar)
        return "\n".join(lines)
    for re in rep.per_rule:
        m = re.marginal
        ms = "—" if m is None else (f"{m * 100:+.0f}%" if rep.has_ground_truth else f"{m:+.3f}")
        tag = "—"
        if m is not None:
            tag = "⊘ HẠI → hạ" if m < threshold else ("✓ giúp" if m > 0.001 else "· trung tính")
        flag = "  [đang bị hạ]" if re.demoted else ""
        g = (re.guidance[:46] + "…") if len(re.guidance) > 47 else re.guidance
        lines.append(f"  {ms:>6}  {tag:<14} {g}{flag}")
    lines.append(bar)
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(prog="theosis.eval", description="Đo ký ức giúp hay hại")
    ap.add_argument("tasks", help="file JSON danh sách task (xem eval_tasks.example.json)")
    ap.add_argument("--trials", type=int, default=1, help="số lượt/ task (nhiều hơn = bớt nhiễu)")
    ap.add_argument("--rounds", type=int, default=2, help="số vòng audit")
    ap.add_argument("--no-executor", action="store_true", help="tắt executor (mất tín hiệu ground truth)")
    ap.add_argument("--rules", action="store_true", help="đo hiệu ứng biên TỪNG rule (ablation), thay vì tổng thể")
    ap.add_argument("--demote", action="store_true", help="(kèm --rules) tự HẠ rule chứng minh có hại")
    ap.add_argument("--threshold", type=float, default=-0.05, help="ngưỡng marginal để hạ (mặc định -0.05)")
    args = ap.parse_args()

    tasks = load_tasks(args.tasks)
    slots, aggregator, _ = load_config()
    store = MemoryStore()

    def prog(i, n):
        print(f"  … {i}/{n}", flush=True)

    if args.rules:
        rep = asyncio.run(eval_rules(
            tasks, slots, aggregator, store,
            rounds=args.rounds, use_executor=not args.no_executor, trials=args.trials, on_progress=prog,
        ))
        print(format_rule_report(rep, threshold=args.threshold))
        if args.demote:
            ids = auto_demote(store, rep, threshold=args.threshold)
            print(f"\n  → Đã hạ {len(ids)} rule" + (f": {ids}" if ids else " (không có rule nào dưới ngưỡng)."))
    else:
        rep = asyncio.run(run_eval(
            tasks, slots, aggregator, store,
            rounds=args.rounds, use_executor=not args.no_executor, trials=args.trials, on_progress=prog,
        ))
        print(format_report(rep))


if __name__ == "__main__":
    main()
