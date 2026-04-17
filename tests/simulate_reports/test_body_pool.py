import sqlite3
import pytest
from scripts.simulate_reports.body_pool import BodyPool


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "t.db"
    c = sqlite3.connect(str(p))
    c.executescript("""
        CREATE TABLE reviews (id INTEGER PRIMARY KEY, body TEXT, headline TEXT, rating REAL, body_hash TEXT);
        CREATE TABLE review_issue_labels (id INTEGER PRIMARY KEY, review_id INT, label_code TEXT, label_polarity TEXT);
        INSERT INTO reviews VALUES
            (1, 'great quality', 'Love it', 5.0, 'h1'),
            (2, 'fell apart', 'Garbage', 1.0, 'h2'),
            (3, 'arrived late', 'Bad shipping', 2.0, 'h3');
        INSERT INTO review_issue_labels (review_id, label_code, label_polarity) VALUES
            (1, 'quality_stability', 'positive'),
            (2, 'quality_stability', 'negative'),
            (3, 'shipping', 'negative');
    """)
    c.commit()
    return p


def test_pool_sample_negative_quality(db):
    pool = BodyPool(db)
    sample = pool.sample("quality_stability", "negative", n=1)
    assert len(sample) == 1
    assert sample[0]["body"] == "fell apart"


def test_pool_sample_more_than_available(db):
    pool = BodyPool(db)
    sample = pool.sample("quality_stability", "negative", n=5)  # only 1 exists
    assert len(sample) >= 1  # reuses allowed
