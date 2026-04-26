"""Tests for F011 H19: failure_mode enum classification + migration."""
import sqlite3

import pytest

from qbu_crawler.server.migrations.migration_0011_failure_mode_enum_backfill import (
    classify_failure_mode,
)
import qbu_crawler.server.migrations.migration_0011_failure_mode_enum_backfill as mig


# ── Classifier unit tests ───────────────────────────────────────────────────

def test_none_class_for_no_variants():
    """各种"无"变体应归到 'none' 类。"""
    cases = ["无", "无失效", "无显著失效模式", "无故障", "无失效问题",
             "无典型失效模式", "无/运行正常", "运行稳定无异常"]
    for case in cases:
        assert classify_failure_mode(case) == "none", f"{case} 应分类为 none"


def test_gear_failure():
    cases = ["齿轮过载停转", "齿轮薄弱卡顿", "齿轮磨损脱落金属屑"]
    for case in cases:
        assert classify_failure_mode(case) == "gear_failure"


def test_motor_anomaly():
    cases = ["电机过载", "马达停转", "电机温升过高"]
    for case in cases:
        assert classify_failure_mode(case) == "motor_anomaly"


def test_casing_assembly():
    cases = ["壳体装配错位", "喉道生锈", "密封圈漏液"]
    for case in cases:
        assert classify_failure_mode(case) == "casing_assembly"


def test_material_finish():
    cases = ["材料剥落", "金属碎屑", "涂层裂纹", "生锈"]
    for case in cases:
        assert classify_failure_mode(case) == "material_finish"


def test_control_electrical():
    cases = ["开关失灵", "按键接触不良", "电气故障"]
    for case in cases:
        assert classify_failure_mode(case) == "control_electrical"


def test_noise():
    cases = ["噪音过大", "运行声大", "嗡嗡声"]
    for case in cases:
        assert classify_failure_mode(case) == "noise"


def test_cleaning_difficulty():
    cases = ["清洁困难", "清洗繁琐"]
    for case in cases:
        assert classify_failure_mode(case) == "cleaning_difficulty"


def test_other_fallback():
    """无法归类 → other"""
    cases = ["完全陌生的失效现象", "xyz123"]
    for case in cases:
        assert classify_failure_mode(case) == "other"


# v1.1 新增：边界场景（解决 B1 优先级 bug）
def test_negation_prefix_overrides_keyword():
    """F011 AC-32 — 含负面 keyword 但有 negation 前缀的，归类为 'none'。"""
    cases = [
        "无齿轮问题",
        "无电机过载",
        "未发现齿轮问题",
        "没有金属碎屑",
        "未见装配错位",
    ]
    for case in cases:
        assert classify_failure_mode(case) == "none", (
            f"{case} 应归类为 none，但得到 {classify_failure_mode(case)}"
        )


def test_genuine_failure_with_no_prefix_in_middle():
    """真实失效——中间含'无'但整体语义为失效，不应归 'none'。"""
    cases = [
        ("齿轮无法运转", "gear_failure"),
        ("电机无规律停转", "motor_anomaly"),
    ]
    for case, expected in cases:
        assert classify_failure_mode(case) == expected, (
            f"{case} 应归类为 {expected}"
        )


# ── Migration integration tests ─────────────────────────────────────────────

@pytest.fixture
def fresh_db(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE review_analysis (
          id INTEGER PRIMARY KEY,
          review_id INTEGER,
          failure_mode TEXT
        );
    """)
    conn.executemany(
        "INSERT INTO review_analysis (review_id, failure_mode) VALUES (?,?)",
        [
            (1, "齿轮过载停转"),
            (2, "无齿轮问题"),
            (3, "完全陌生的失效现象"),
            (4, None),
        ],
    )
    conn.commit()
    yield conn
    conn.close()


def test_up_backfills_raw_and_rewrites_enum(fresh_db):
    mig.up(fresh_db)
    cur = fresh_db.cursor()

    # failure_mode_raw column must exist
    cols = [r[1] for r in cur.execute("PRAGMA table_info(review_analysis)").fetchall()]
    assert "failure_mode_raw" in cols

    rows = list(
        cur.execute(
            "SELECT review_id, failure_mode, failure_mode_raw FROM review_analysis ORDER BY review_id"
        )
    )
    assert rows[0] == (1, "gear_failure", "齿轮过载停转")
    assert rows[1] == (2, "none",         "无齿轮问题")
    assert rows[2] == (3, "other",        "完全陌生的失效现象")
    assert rows[3] == (4, None,           None)


def test_up_is_idempotent(fresh_db):
    """Option A guard: calling up() twice must leave all rows unchanged."""
    mig.up(fresh_db)
    snapshot = list(
        fresh_db.execute(
            "SELECT review_id, failure_mode FROM review_analysis ORDER BY review_id"
        ).fetchall()
    )
    mig.up(fresh_db)
    snapshot2 = list(
        fresh_db.execute(
            "SELECT review_id, failure_mode FROM review_analysis ORDER BY review_id"
        ).fetchall()
    )
    assert snapshot == snapshot2


def test_whitespace_and_none_inputs_classify_as_none():
    """Fix B/C — None / "" / 全空白 must be 'none', not 'other'."""
    assert classify_failure_mode(None) == "none"
    assert classify_failure_mode("") == "none"
    assert classify_failure_mode("   ") == "none"
    assert classify_failure_mode("\t\n  ") == "none"
