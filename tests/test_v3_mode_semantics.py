"""F011 §4.1.3 — module retired.

Previously this file held three tests (test_bootstrap_email_shows_monitoring_start_not_empty_state,
test_incremental_email_renders_explicit_empty_state,
test_active_email_renders_competitor_positive_review_signal) that asserted on
the legacy email_full.html.j2 change_digest banner ("Monitoring Start" /
"No significant changes" / fresh_competitor_positive_reviews block).

F011 §4.1 redesigns the email body around 4 KPI lamps + Hero + Top 3 +
product_status; §4.1.3 explicitly removes the change_digest banner and the
competitor positive-review block from the email. The asserted wording no
longer renders. New email-template coverage lives in
tests/server/test_email_full_template.py.
"""
