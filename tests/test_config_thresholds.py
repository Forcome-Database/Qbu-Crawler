"""Tests for configurable report thresholds."""


def test_default_negative_threshold():
    from qbu_crawler import config
    assert config.NEGATIVE_THRESHOLD == 2


def test_default_low_rating_threshold():
    from qbu_crawler import config
    assert config.LOW_RATING_THRESHOLD == 3


def test_default_health_red():
    from qbu_crawler import config
    assert config.HEALTH_RED == 45


def test_default_health_yellow():
    from qbu_crawler import config
    assert config.HEALTH_YELLOW == 60


def test_default_high_risk_threshold():
    from qbu_crawler import config
    assert config.HIGH_RISK_THRESHOLD == 35
