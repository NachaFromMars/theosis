"""Tests — run with: pytest  (no API keys needed, uses mock slots)."""
import asyncio

from theosis.config import demo_aggregator, demo_slots
from theosis.core import audit_pairs, theosis
from theosis.metrics import avg_similarity, estimate_cost, verdict_score
from theosis.models import ModelSlot


# ── pipeline basics ─────────────────────────────────────────────────────────
def test_audit_pairs_is_round_robin():
    class S:
        def __init__(self, name):
            self.name = name

    a, b, c = S("a"), S("b"), S("c")
    pairs = [(t.name, au.name) for t, au in audit_pairs([a, b, c])]
    assert pairs == [("a", "b"), ("b", "c"), ("c", "a")]


def test_pipeline_runs_in_mock_mode():
    slots = demo_slots()
    for s in slots:
        s.enabled = True
    final, trail = asyncio.run(theosis("xin chào", slots, demo_aggregator(), max_rounds=1))
    assert isinstance(final, str) and final.strip()
    assert trail["fanout"] and len(trail["rounds"]) == 1
    for s in slots:
        assert s.name in trail["fanout"]


def test_single_slot_skips_cross_audit():
    slots = demo_slots()
    for s in slots:
        s.enabled = s.name == "opus"
    final, trail = asyncio.run(theosis("hi", slots, demo_aggregator(), max_rounds=2))
    assert trail["rounds"] == []
    assert final.strip()


def test_no_enabled_slot_raises():
    slots = demo_slots()
    for s in slots:
        s.enabled = False
    try:
        asyncio.run(theosis("hi", slots, demo_aggregator(), max_rounds=1))
        assert False, "expected ValueError"
    except ValueError:
        pass


# ── V2: resilience ──────────────────────────────────────────────────────────
def test_failing_slot_is_dropped_not_fatal():
    good = ModelSlot("good", "m", "mock://")
    bad = ModelSlot("bad", "m", "http://127.0.0.1:1/v1", api_key="x")  # connection refused
    final, trail = asyncio.run(theosis("hi", [good, bad], demo_aggregator(), max_rounds=1))
    assert "good" in trail["fanout"]
    assert "bad" not in trail["fanout"]  # bị loại, không làm sập mẻ
    assert final.strip()


# ── V2: cost meter ──────────────────────────────────────────────────────────
def test_cost_meter_accumulates():
    slots = demo_slots()
    for s in slots:
        s.enabled = True
    _, trail = asyncio.run(theosis("hi", slots, demo_aggregator(), max_rounds=1))
    cost = trail["cost"]
    assert cost["calls"] > 0 and cost["total_tokens"] > 0


def test_estimate_cost_known_and_default():
    # gpt-4o: 2.5 in / 10 out per 1M
    c = estimate_cost("gpt-4o", {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000})
    assert abs(c - 12.5) < 1e-6
    # model lạ -> bảng giá mặc định
    c2 = estimate_cost("unknown-model", {"prompt_tokens": 1_000_000, "completion_tokens": 0})
    assert c2 > 0


# ── V2: convergence + scoring helpers ───────────────────────────────────────
def test_avg_similarity_identical_is_one():
    assert avg_similarity({"a": "hello world"}, {"a": "hello world"}) == 1.0


def test_verdict_score_mapping():
    assert verdict_score("VERDICT: strong") == 1.0
    assert verdict_score("VERDICT: weak") == 0.2
    assert verdict_score("no verdict here") == 0.5


def test_scores_present_in_trail():
    slots = demo_slots()
    for s in slots:
        s.enabled = True
    _, trail = asyncio.run(theosis("hi", slots, demo_aggregator(), max_rounds=1))
    assert set(trail["scores"]) >= {"opus", "gpt"}
