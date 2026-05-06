from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from qbu_crawler import config


@dataclass(frozen=True)
class EmailDecision:
    send_email: bool
    reason: str
    cadence: str
    report_window_type: str
    window_days: int


def _logical_date(value: str) -> date:
    return date.fromisoformat(str(value)[:10])


def _is_bootstrap(snapshot: dict) -> bool:
    if snapshot.get("report_semantics") == "bootstrap":
        return True
    if snapshot.get("is_bootstrap") is True:
        return True
    return False


def decide_business_email(*, run: dict, snapshot: dict, mode: str) -> EmailDecision:
    window_days = int(getattr(config, "REPORT_WEEKLY_WINDOW_DAYS", 7))
    if bool(getattr(config, "REPORT_EMAIL_FORCE_DISABLED", False)):
        return EmailDecision(False, "email_disabled", getattr(config, "REPORT_EMAIL_CADENCE", "weekly"), "daily", window_days)
    if _is_bootstrap(snapshot):
        if bool(getattr(config, "REPORT_EMAIL_SEND_BOOTSTRAP", True)):
            return EmailDecision(True, "bootstrap", "bootstrap", "bootstrap", window_days)
        return EmailDecision(False, "bootstrap_email_disabled", "bootstrap", "daily", window_days)

    cadence = getattr(config, "REPORT_EMAIL_CADENCE", "weekly")
    if cadence == "daily":
        return EmailDecision(True, "daily_cadence", "daily", "daily", window_days)

    logical_date = _logical_date(run.get("logical_date") or snapshot.get("logical_date"))
    if logical_date.isoweekday() == int(getattr(config, "REPORT_WEEKLY_EMAIL_WEEKDAY", 1)):
        return EmailDecision(True, "weekly_report_day", "weekly", "weekly", window_days)
    return EmailDecision(False, "weekly_cadence_skip", "weekly", "daily", window_days)
