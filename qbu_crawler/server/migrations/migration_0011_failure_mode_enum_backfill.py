"""F011 H19 — failure_mode 自由文本 → enum 9 类归类回填。

策略：
1. 优先全文 negation 正则（解决 B1 bug: "无齿轮问题" 归 none，不走 gear_failure keyword）
2. 否则 keyword 正则匹配 → 对应 enum 值
3. 全部不命中 → 'other'
4. 保留原始文本到 failure_mode_raw

幂等性（Option A）：up() 执行 SELECT 时排除 failure_mode 已经是合法 enum 值的行，
因此可以安全地多次调用而不会把 "gear_failure" 等已归类值再次分类成 "other"。
"""
import logging
import re
import sqlite3

log = logging.getLogger(__name__)

ENUM_VALUES = (
    "none", "gear_failure", "motor_anomaly", "casing_assembly",
    "material_finish", "control_electrical", "noise", "cleaning_difficulty", "other",
)

# ── Negation regex (must test BEFORE keyword patterns) ──────────────────────
# v1.1: Handles B1 bug — phrases like "无齿轮问题" or "没有金属碎屑" that
# contain failure keywords but are semantically "no failure".
#
# Component groups used in the pattern (embedded for clarity):
#   QUALIFIER  = (任何|明显|显著|典型|具体)?
#   KEYWORD    = (齿轮|电机|马达|开关|材料|涂层|噪音|金属|装配|壳体)?
#   SUFFIX     = (失效|故障|问题|缺陷|异常|过载|碎屑|停转|错位|模式|缺失|类型)?
#
# Anchors (^...$) ensure "齿轮无法运转" (starts with 齿轮, not 无/没有/未)
# never matches the negation branch.

_Q = r"(任何|明显|显著|典型|具体)?"
_K = r"(齿轮|电机|马达|开关|材料|涂层|噪音|金属|装配|壳体)?"
_S = r"(失效|故障|问题|缺陷|异常|过载|碎屑|停转|错位|模式|缺失|类型)?"

NEGATION_FULL_PHRASES = re.compile(
    r"^("
    # 无 + optional qualifier + optional keyword + up to 2 suffix tokens
    r"无" + _Q + _K + _S + _S + r"|"
    # 没有 + optional qualifier + optional keyword + optional suffix
    r"没有" + _Q + _K + _S + r"|"
    # 未(发现|出现|表现|见到?) + optional qualifier + optional keyword + optional suffix
    r"未(发现|出现|表现|见到?)" + _Q + _K + _S + r"|"
    # 运行 + stable word + optional 无+suffix
    r"运行(稳定|正常|顺畅|流畅)(无(异常|故障|问题))?|"
    # Short exact matches
    r"无类(别)?|N/A|none|不适用"
    r")$"
    r"|"
    # 无/xxx or 未见/xxx or 没有/xxx (slash-separated compound)
    r"^(无|未见|没有)/[^/]+$",
    re.IGNORECASE,
)


# ── Keyword patterns (ordered by specificity) ───────────────────────────────
FAILURE_KEYWORD_PATTERNS = [
    ("gear_failure",        re.compile(r"齿轮")),
    ("motor_anomaly",       re.compile(r"(电机|马达|过载|温升|停转(?!.*齿轮))")),
    ("casing_assembly",     re.compile(r"(壳体|装配|喉道|密封|漏液|接口|焊缝)")),
    ("material_finish",     re.compile(r"(材料|涂层|碎屑|剥落|生锈|裂纹|金属屑)")),
    ("control_electrical",  re.compile(r"(开关|电气|按键|接触|电源|电路)")),
    ("noise",               re.compile(r"(噪音|噪声|嗡|声大|分贝)")),
    ("cleaning_difficulty", re.compile(r"清(洁|洗)(困难|繁琐|不便)")),
]


def classify_failure_mode(raw: str) -> str:
    """归类自由文本到 9 类 enum。

    两阶段分类（v1.1）：
    1. 全文 negation 检测 → 'none'（优先，绕过 keyword 检测）
    2. keyword 匹配 → 对应 enum 值
    3. 全部不命中 → 'other'
    """
    if not raw:
        return "none"
    raw = raw.strip()

    # Belt-and-suspenders: single character 无
    if raw == "无":
        return "none"

    # Stage 1: full-phrase negation (resolves B1 bug)
    if NEGATION_FULL_PHRASES.match(raw):
        return "none"

    # Stage 2: keyword matching
    for enum_val, pattern in FAILURE_KEYWORD_PATTERNS:
        if pattern.search(raw):
            return enum_val

    return "other"


def up(conn: sqlite3.Connection) -> None:
    """Apply migration: add failure_mode_raw column, backfill, reclassify.

    Idempotent (Option A): rows whose failure_mode is already a valid enum value
    are skipped on classification, so calling up() multiple times is safe.
    """
    cur = conn.cursor()

    # 1. Add failure_mode_raw column (idempotent — swallow duplicate-column error)
    try:
        cur.execute("ALTER TABLE review_analysis ADD COLUMN failure_mode_raw TEXT")
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise

    # 2. Copy current failure_mode to failure_mode_raw (only for rows not yet backfilled)
    cur.execute(
        "UPDATE review_analysis SET failure_mode_raw = failure_mode WHERE failure_mode_raw IS NULL"
    )

    # 3. Reclassify free-text values → enum, skipping rows already holding a valid enum value
    placeholders = ",".join("?" * len(ENUM_VALUES))
    rows = cur.execute(
        f"SELECT id, failure_mode FROM review_analysis "
        f"WHERE failure_mode IS NOT NULL "
        f"AND failure_mode NOT IN ({placeholders})",
        ENUM_VALUES,
    ).fetchall()

    log.info("migration_0011: reclassifying %d row(s)", len(rows))
    for row_id, raw in rows:
        enum_val = classify_failure_mode(raw)
        cur.execute(
            "UPDATE review_analysis SET failure_mode = ? WHERE id = ?",
            (enum_val, row_id),
        )

    conn.commit()


def down(conn: sqlite3.Connection) -> None:
    """Rollback: restore failure_mode from failure_mode_raw, drop the raw column."""
    cur = conn.cursor()
    cur.execute(
        "UPDATE review_analysis SET failure_mode = failure_mode_raw WHERE failure_mode_raw IS NOT NULL"
    )
    try:
        cur.execute("ALTER TABLE review_analysis DROP COLUMN failure_mode_raw")
    except sqlite3.OperationalError as e:
        # Older SQLite (< 3.35) lacks DROP COLUMN — log and continue
        log.warning("migration_0011 down() could not drop failure_mode_raw: %s", e)
    conn.commit()
