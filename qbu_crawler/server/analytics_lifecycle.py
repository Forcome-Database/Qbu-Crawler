"""P008 Phase 4: Issue lifecycle state machine for the monthly report.

States (design doc Section 6.4):
  - active:    recent credible negative review (RCW > 0.5)
  - receding:  active + positive cohort dominates in 30-day window (≥3 reviews)
  - dormant:   active/receding + silence_window days without new negative
  - recurrent: dormant + new negative

Transitions (R1-R6):
  R1: credible negative → active
  R2: active + positive cohort + ≤1:1 neg/pos in 30d + ≥3 reviews → receding
  R3: active/receding + silence_window days no new negative → dormant
  R4: dormant + new negative → recurrent
  R5: recurrent behaves like active (re-enters R2/R3 from there)
  R6: critical/high safety issues double silence_window (no premature dormant)

The silence_window is dynamic per (label_code, ownership): twice the average
inter-review interval, clamped to [14, 60] days. When fewer than 2 events exist
the average is undefined, so a conservative 30-day default is used instead of
the 14-day floor — this prevents premature dormant on single-review timelines.

Implementation notes:
  - Credibility weight uses ``window_end`` as the reference date to make
    lifecycle results deterministic regardless of when the code runs.
  - R3 (silence check) is applied only when a NEGATIVE event arrives, not on
    positive events. This prevents positive reviews from being treated as
    "evidence of silence" between two negative events. The final R3 check at
    ``window_end`` catches the trailing silence after the last event.
  - ``last_negative_date`` is tracked for ALL negatives regardless of RCW, so
    that a later credible negative can still trigger R4 (recurrent) even when
    the prior event was too weak to trigger R1 (active). RCW gating only
    applies to the state-transition rules (R1/R4), not to the temporal tracker.
  - In ``receding`` state the dormancy clock tracks the last ANY review
    (``last_any_date``), not just the last negative: an issue actively backed by
    positive reviews should not go dormant simply because no new negatives have
    arrived. For ``active`` / ``recurrent`` states the clock uses
    ``last_negative_date`` as usual.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import mean

from qbu_crawler.server.report_common import credibility_weight, detect_safety_level


_RCW_ACTIVE_THRESHOLD = 0.5
_NEG_POS_RECEDING_RATIO = 1.0
_RECEDING_MIN_REVIEWS = 3
_SILENCE_MIN = 14
_SILENCE_MAX = 60
_SILENCE_DEFAULT_INSUFFICIENT = 30  # When <2 events: avoid premature dormant
_RECEDING_WINDOW_DAYS = 30


def _parse_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _label_polarity_for(review: dict, label_code: str) -> str | None:
    raw = review.get("analysis_labels") or "[]"
    if isinstance(raw, str):
        try:
            labels = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
    else:
        labels = raw
    for lb in labels:
        if lb.get("code") == label_code:
            return (lb.get("polarity") or "").lower()
    return None


def _is_negative(review: dict, label_code: str) -> bool:
    return _label_polarity_for(review, label_code) == "negative"


def _is_positive(review: dict, label_code: str) -> bool:
    return _label_polarity_for(review, label_code) == "positive"


def _has_safety_critical(review: dict) -> bool:
    if (review.get("impact_category") or "").lower() == "safety":
        return True
    text = f"{review.get('headline', '')} {review.get('body', '')}"
    level = detect_safety_level(text)
    return level in ("critical", "high")


def _silence_window_days(timeline: list[dict], has_safety: bool) -> int:
    """Average inter-review interval × 2, clamped to [14, 60]; doubled for safety.

    When fewer than 2 events exist the average interval is undefined. Use a
    conservative 30-day default so a single recent review never triggers
    premature dormant (would happen with the 14-day floor).
    """
    if len(timeline) < 2:
        base = _SILENCE_DEFAULT_INSUFFICIENT  # 30 — see module-level constant
    else:
        sorted_dates = sorted(t["date"] for t in timeline if t.get("date"))
        intervals = [
            (sorted_dates[i] - sorted_dates[i - 1]).days
            for i in range(1, len(sorted_dates))
        ]
        avg = mean(intervals) if intervals else _SILENCE_MIN
        base = max(_SILENCE_MIN, min(int(avg * 2), _SILENCE_MAX))
    return base * 2 if has_safety else base


def derive_issue_lifecycle(
    label_code: str,
    ownership: str,
    reviews_for_label: list[dict],
    window_end: date,
) -> tuple[str, list[dict]]:
    """Walk through reviews chronologically, applying R1-R6 to derive final state.

    Returns ``(state, history)`` where history is a list of state-transition events.

    The credibility weight for each review is evaluated relative to ``window_end``
    (not ``date.today()``) to keep results deterministic across reporting runs.
    """
    relevant = [r for r in reviews_for_label if r.get("ownership") == ownership]
    if not relevant:
        return "dormant", []

    # Use window_end as the reference "today" for credibility_weight so that
    # lifecycle results are deterministic regardless of when the code runs.
    rcw_today = window_end

    timeline = []
    for r in relevant:
        d = _parse_date(r.get("date_published_parsed") or r.get("date_published"))
        if d is None:
            continue
        rcw = credibility_weight(r, today=rcw_today)
        timeline.append({
            "date": d,
            "rcw": rcw,
            "is_negative": _is_negative(r, label_code),
            "is_positive": _is_positive(r, label_code),
            "review_id": r.get("id"),
            "is_safety": _has_safety_critical(r),
        })

    timeline.sort(key=lambda t: t["date"])
    if not timeline:
        return "dormant", []

    has_safety = any(t["is_safety"] for t in timeline)
    silence_window = _silence_window_days(timeline, has_safety)

    state = "dormant"
    # last_negative_date tracks ALL negatives (not just credible ones) so that a
    # later credible negative can still trigger R4 even if the prior one was weak.
    last_negative_date: date | None = None
    # last_any_date tracks all reviews; used for dormancy clock in receding state.
    last_any_date: date | None = None
    history = []

    for event in timeline:
        ev_date = event["date"]

        # R3: silence_window check — runs only when a negative event arrives.
        # Positive reviews between two negatives are NOT evidence of silence;
        # checking R3 on positives would prematurely mark the issue dormant.
        if event["is_negative"] and state in ("active", "receding") and last_negative_date is not None:
            silent_days = (ev_date - last_negative_date).days
            if silent_days >= silence_window:
                state = "dormant"
                history.append({"date": ev_date, "transition": "→dormant", "reason": "R3"})

        if event["is_negative"]:
            # Track temporal position of ALL negatives for dormancy window purposes.
            # (RCW gate applies only to state-transition rules, not to this tracker.)
            last_negative_date = ev_date

            if event["rcw"] >= _RCW_ACTIVE_THRESHOLD:
                # R1 / R4 state transitions
                if state == "dormant":
                    if last_negative_date is not None and any(
                        t["date"] < ev_date and t["is_negative"] for t in timeline
                    ):
                        # R4: dormant + new credible negative after prior negative → recurrent
                        state = "recurrent"
                        history.append({"date": ev_date, "transition": "dormant→recurrent", "reason": "R4"})
                    else:
                        # R1: first credible negative → active
                        state = "active"
                        history.append({"date": ev_date, "transition": "→active", "reason": "R1"})
                elif state == "receding":
                    # New credible negative breaks receding → back to active
                    state = "active"
                    history.append({"date": ev_date, "transition": "receding→active", "reason": "R1"})
                elif state == "recurrent":
                    # Stay recurrent (R5: recurrent behaves like active)
                    pass
                else:
                    # active → stays active (R1 reinforcement)
                    pass

        # Update last_any_date after processing the event.
        last_any_date = ev_date

        # R2: active/recurrent + recent positive cohort dominates → receding
        if state in ("active", "recurrent"):
            window_start = ev_date - timedelta(days=_RECEDING_WINDOW_DAYS)
            recent = [t for t in timeline if window_start <= t["date"] <= ev_date]
            neg = sum(1 for t in recent if t["is_negative"])
            pos = sum(1 for t in recent if t["is_positive"])
            if pos >= 1 and len(recent) >= _RECEDING_MIN_REVIEWS and neg <= pos * _NEG_POS_RECEDING_RATIO:
                state = "receding"
                history.append({"date": ev_date, "transition": "active→receding", "reason": "R2"})

    # Final R3 check using window_end.
    # In receding state: use last_any_date (positive reviews are active signal).
    # In active/recurrent state: use last_negative_date (silence = no new negatives).
    if state in ("active", "recurrent") and last_negative_date is not None:
        silent_days = (window_end - last_negative_date).days
        if silent_days >= silence_window:
            state = "dormant"
            history.append({"date": window_end, "transition": "→dormant", "reason": "R3 (window_end)"})
    elif state == "receding" and last_any_date is not None:
        silent_days = (window_end - last_any_date).days
        if silent_days >= silence_window:
            state = "dormant"
            history.append({"date": window_end, "transition": "→dormant", "reason": "R3 (window_end)"})

    return state, history


def derive_all_lifecycles(
    all_reviews: list[dict],
    window_end: date,
) -> dict[tuple[str, str], dict]:
    """Pre-group reviews by (label_code, ownership) then derive state per group.

    Returns ``{(label_code, ownership): {"state": str, "history": list, "review_count": int,
                                         "first_seen": date|None, "last_seen": date|None}}``.
    """
    label_index: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in all_reviews:
        raw = r.get("analysis_labels") or "[]"
        if isinstance(raw, str):
            try:
                labels = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                labels = []
        else:
            labels = raw
        ownership = r.get("ownership") or "unknown"
        for lb in labels:
            code = lb.get("code")
            if not code:
                continue
            label_index[(code, ownership)].append(r)

    results: dict[tuple[str, str], dict] = {}
    for (label_code, ownership), relevant in label_index.items():
        state, history = derive_issue_lifecycle(label_code, ownership, relevant, window_end)
        dates = [_parse_date(r.get("date_published_parsed") or r.get("date_published")) for r in relevant]
        valid_dates = [d for d in dates if d]
        results[(label_code, ownership)] = {
            "state": state,
            "history": history,
            "review_count": len(relevant),
            "first_seen": min(valid_dates).isoformat() if valid_dates else None,
            "last_seen": max(valid_dates).isoformat() if valid_dates else None,
        }
    return results
