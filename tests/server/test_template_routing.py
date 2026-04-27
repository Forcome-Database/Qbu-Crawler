"""F011 §6.4.1 v1.1 — REPORT_TEMPLATE_VERSION env routing for legacy fallback."""
import logging

import pytest

from qbu_crawler.server.report import _select_template


def test_default_v3_when_env_unset(monkeypatch):
    monkeypatch.delenv("REPORT_TEMPLATE_VERSION", raising=False)
    assert _select_template() == "daily_report_v3.html.j2"


def test_legacy_when_env_set(monkeypatch):
    monkeypatch.setenv("REPORT_TEMPLATE_VERSION", "v3_legacy")
    assert _select_template() == "daily_report_v3_legacy.html.j2"


def test_unknown_value_falls_back_to_v3(monkeypatch, caplog):
    monkeypatch.setenv("REPORT_TEMPLATE_VERSION", "v99_nonsense")
    with caplog.at_level(logging.WARNING):
        result = _select_template()
    assert result == "daily_report_v3.html.j2"
    assert any("Unknown" in r.message or "v99" in r.message for r in caplog.records)


def test_missing_legacy_file_falls_back_to_v3(monkeypatch, tmp_path):
    """legacy template missing → silent fallback to v3."""
    monkeypatch.setenv("REPORT_TEMPLATE_VERSION", "v3_legacy")
    monkeypatch.setattr("qbu_crawler.server.report.REPORT_TEMPLATE_DIR", tmp_path)
    (tmp_path / "daily_report_v3.html.j2").touch()  # only v3 exists
    assert _select_template() == "daily_report_v3.html.j2"


def test_explicit_v3_returns_v3(monkeypatch):
    """REPORT_TEMPLATE_VERSION=v3 explicit returns v3."""
    monkeypatch.setenv("REPORT_TEMPLATE_VERSION", "v3")
    assert _select_template() == "daily_report_v3.html.j2"
