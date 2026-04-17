from scripts.simulate_reports.manifest import compute_verdict


def test_verdict_pass():
    expected = {"report_mode": "standard", "lifecycle_states_must_include": ["active"]}
    actual = {"report_mode": "standard", "lifecycle_states_seen": ["active", "dormant"]}
    v, failures, warnings = compute_verdict(expected, actual)
    assert v == "PASS"
    assert failures == []


def test_verdict_fail_on_mode():
    expected = {"report_mode": "change"}
    actual = {"report_mode": "standard"}
    v, failures, _ = compute_verdict(expected, actual)
    assert v == "FAIL"
    assert any("report_mode" in f for f in failures)


def test_verdict_fail_lifecycle_missing():
    expected = {"lifecycle_states_must_include": ["recurrent"]}
    actual = {"lifecycle_states_seen": ["active"]}
    v, failures, _ = compute_verdict(expected, actual)
    assert v == "FAIL"
    assert any("recurrent" in f for f in failures)


def test_verdict_html_contains():
    expected = {"html_must_contain": ["复发"]}
    actual = {"html_contains": {"复发": False}}
    v, failures, _ = compute_verdict(expected, actual)
    assert v == "FAIL"
