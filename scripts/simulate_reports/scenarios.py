"""Scenario definitions: SID → {description, events, expected}.

`events` is a list of structured dicts applied by timeline.apply_events().
`expected` feeds manifest.compute_verdict().
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Callable


@dataclass
class Scenario:
    sid: str
    logical_date: date
    phase: str
    tier: str             # 'daily' | 'weekly' | 'monthly'
    description: str
    events: list[dict] = field(default_factory=list)
    expected: dict = field(default_factory=dict)


# Helper constructors ---------------------------------------------------------

def _ev(op: str, **kwargs) -> dict:
    return {"op": op, **kwargs}


# Named scenarios -------------------------------------------------------------

SCENARIOS: dict[str, Scenario] = {}


def _add(s: Scenario):
    SCENARIOS[s.sid] = s


# S01 cold-start: D01 = 2026-03-20
_add(Scenario(
    sid="S01", logical_date=date(2026, 3, 20), phase="P1", tier="daily",
    description="首日部署冷启动 (is_partial=true)",
    events=[],  # prepare 已把 scraped_at 重分布好
    expected={
        "tier": "daily", "report_mode": "full",
        "is_partial": True,
        "html_must_contain": [],
    },
))

# S02 normal Full (仅声明一次作为代表；时间轴会多天复用 S02 变体)
_add(Scenario(
    sid="S02", logical_date=date(2026, 3, 21), phase="P1", tier="daily",
    description="常规 Full 模式",
    events=[
        _ev("inject_new_reviews", count=8, polarity="positive",
            label="quality_stability"),
        _ev("inject_new_reviews", count=3, polarity="negative",
            label="shipping"),
    ],
    expected={"tier": "daily", "report_mode": "full", "is_partial": False},
))

# S03 safety doubled (D07 = 2026-03-26)
_add(Scenario(
    sid="S03", logical_date=date(2026, 3, 26), phase="P1", tier="daily",
    description="Safety incidents 集中注入，触发 R6 silence×2",
    events=[
        _ev("inject_new_reviews", count=6, polarity="negative",
            label="safety"),
        _ev("inject_safety_incidents_from_today", level="critical",
            failure_mode="foreign_object"),
    ],
    expected={"tier": "daily", "report_mode": "full"},
))

# S04 R1 active (D08 = 2026-03-27)
_add(Scenario(
    sid="S04", logical_date=date(2026, 3, 27), phase="P2", tier="daily",
    description="quality_stability 集中差评 → R1 active",
    events=[
        _ev("inject_new_reviews", count=6, polarity="negative",
            label="quality_stability"),
    ],
    expected={
        "tier": "daily", "report_mode": "full",
        "lifecycle_states_must_include": ["active"],
    },
))

# S05 R2 receding (D12 = 2026-03-31)
_add(Scenario(
    sid="S05", logical_date=date(2026, 3, 31), phase="P2", tier="daily",
    description="quality_stability 正负比回落 → R2 receding",
    events=[
        _ev("inject_new_reviews", count=8, polarity="positive",
            label="quality_stability"),
    ],
    expected={
        "tier": "daily",
        "lifecycle_states_must_include": ["receding"],
    },
))

# S06 R3 dormant (D15 = 2026-04-03) — no events, just static over silence window
_add(Scenario(
    sid="S06", logical_date=date(2026, 4, 3), phase="P3", tier="daily",
    description="quality_stability 进入静默（背景）",
    events=[
        _ev("inject_new_reviews", count=3, polarity="negative",
            label="shipping"),  # 其他 label 照常
    ],
    expected={"tier": "daily"},
))

# S07 daily-change (D16 = 2026-04-04)
_add(Scenario(
    sid="S07", logical_date=date(2026, 4, 4), phase="P3", tier="daily",
    description="0 新评论 + 价格-15% + 库存 out_of_stock → Change 模式",
    events=[
        _ev("mutate_random_product", price_delta_pct=-0.15,
            stock_status="out_of_stock"),
    ],
    expected={"tier": "daily", "report_mode": "change"},
))

# S08 quiet email days (D17-D19)
for sid, d, n in [("S08a", date(2026, 4, 5), 1),
                  ("S08b", date(2026, 4, 6), 2),
                  ("S08c", date(2026, 4, 7), 3)]:
    _add(Scenario(
        sid=sid, logical_date=d, phase="P3", tier="daily",
        description=f"Quiet 模式第 {n} 天（发邮件）",
        events=[],
        expected={
            "tier": "daily", "report_mode": "quiet",
            "email_count_min": 1,
        },
    ))

# S09 quiet silent days (D20-D22)
for sid, d in [("S09a", date(2026, 4, 8)),
               ("S09b", date(2026, 4, 9)),
               ("S09c", date(2026, 4, 10))]:
    _add(Scenario(
        sid=sid, logical_date=d, phase="P3", tier="daily",
        description="Quiet 模式持续静默（不发邮件）",
        events=[],
        expected={
            "tier": "daily", "report_mode": "quiet",
            "email_count_max": 0,
        },
    ))

# S10 R4 recurrent (D26 = 2026-04-14) — 距 D11 last-active 15 天 ≥ silence_window 14
_add(Scenario(
    sid="S10", logical_date=date(2026, 4, 14), phase="P4", tier="daily",
    description="quality_stability 复发 → R4 recurrent",
    events=[
        _ev("inject_new_reviews", count=4, polarity="negative",
            label="quality_stability"),
    ],
    expected={
        "tier": "daily",
        "lifecycle_states_must_include": ["recurrent"],
    },
))

# S11 needs-attention (D27 = 2026-04-15)
_add(Scenario(
    sid="S11", logical_date=date(2026, 4, 15), phase="P4", tier="daily",
    description="30% 当日评论翻译 stalled → needs_attention",
    events=[
        _ev("inject_new_reviews", count=10, polarity="positive",
            label="shipping"),
        _ev("force_translation_stall", pending_fraction=0.3),
    ],
    expected={
        "tier": "daily",
        "email_count_max": 0,
    },
))

# Weekly & monthly ------------------------------------------------------------
for wid, d, phase in [
    ("W0", date(2026, 3, 23), "P1"),
    ("W1", date(2026, 3, 30), "P2"),
    ("W2", date(2026, 4, 6),  "P3"),
    ("W3", date(2026, 4, 13), "P4"),
    ("W4", date(2026, 4, 20), "P5"),
    ("W5", date(2026, 4, 27), "P5"),
]:
    _add(Scenario(
        sid=wid, logical_date=d, phase=phase, tier="weekly",
        description=f"周报 {d.isocalendar().year}W{d.isocalendar().week:02d}",
        events=[],
        expected={"tier": "weekly"},
    ))

_add(Scenario(
    sid="M1", logical_date=date(2026, 5, 1), phase="P5", tier="monthly",
    description="月报 2026-04（含品类对标 + LLM 高管摘要）",
    events=[],
    expected={
        "tier": "monthly",
        "excel_must_have_sheets": ["评论明细", "产品概览"],
    },
))
