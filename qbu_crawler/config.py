import os
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv(encoding="utf-8-sig")


def _enum_env(name: str, default: str, allowed: tuple[str, ...]) -> str:
    """Read an enum-like env var and reject invalid rollout values early."""
    value = os.getenv(name, default).strip().lower()
    if value not in allowed:
        allowed_values = ", ".join(allowed)
        raise ValueError(f"{name} must be one of: {allowed_values}; got {value!r}")
    return value


def _clock_time_env(name: str, default: str) -> str:
    """Read an HH:MM local-time value and fail early on invalid schedules."""
    value = os.getenv(name, default).strip()
    try:
        datetime.strptime(value, "%H:%M")
    except ValueError as exc:
        raise ValueError(f"{name} must use HH:MM 24-hour format; got {value!r}") from exc
    return value


def _validate_paired_env(name_a: str, value_a: str, name_b: str, value_b: str) -> None:
    """Require two related env vars to be configured together."""
    if bool(value_a) ^ bool(value_b):
        raise ValueError(
            f"{name_a} and {name_b} must be configured together; "
            f"got {name_a}={value_a!r}, {name_b}={value_b!r}"
        )

# 数据目录：优先使用环境变量 QBU_DATA_DIR，否则使用项目根目录下的 data/
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(PACKAGE_DIR)
DATA_DIR = os.getenv("QBU_DATA_DIR", "") or os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "products.db")

# 确保 data 目录存在
os.makedirs(DATA_DIR, exist_ok=True)

# DrissionPage 浏览器配置
HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"  # 环境变量控制无头模式
PAGE_LOAD_TIMEOUT = 30  # 页面加载超时（秒）
LOAD_MODE = "eager"  # eager: DOM就绪即停(推荐) | normal: 等所有资源 | none: 连接即停
NO_IMAGES = True  # 禁止加载图片，减少带宽和加载时间

# 重试配置
RETRY_TIMES = 3  # 页面加载失败重试次数
RETRY_INTERVAL = 2  # 重试间隔（秒）

# 等待配置
BV_WAIT_TIMEOUT = 10  # Bazaarvoice 数据等待超时（秒）
BV_POLL_INTERVAL = 0.5  # BV 数据轮询间隔（秒）

# Chrome 用户数据（绕过 Akamai 等严格反爬，复用已有 cookie/session）
CHROME_USER_DATA_PATH = os.getenv("CHROME_USER_DATA_PATH", "")  # 留空则用独立浏览器

# 代理池 API（遇到反爬封锁时自动获取代理 IP）
# 示例: https://white.1024proxy.com/white/api?region=US&num=1&time=10&format=1&type=txt
PROXY_API_URL = os.getenv("PROXY_API_URL", "")
PROXY_MAX_RETRIES = int(os.getenv("PROXY_MAX_RETRIES", "3"))  # 单个 URL 最大代理轮换次数
# 指定站点直接使用代理，跳过直连尝试（逗号分隔站点标识，如 basspro,waltons）
PROXY_SITES = {s.strip() for s in os.getenv("PROXY_SITES", "").split(",") if s.strip()}

# 反爬配置
REQUEST_DELAY = (1, 3)  # 请求间随机延迟范围（秒），设为 None 禁用

# 稳定性配置
RESTART_EVERY = 50  # 每抓取 N 个产品后重启浏览器，防止内存泄漏，0 禁用
MAX_REVIEWS = 200  # 单个产品最多加载的评论数，0 表示不限制（大量评论会导致浏览器崩溃）

# MinIO 配置
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "192.168.16.116")
MINIO_PORT = int(os.getenv("MINIO_PORT", "9000"))
MINIO_USE_SSL = os.getenv("MINIO_USE_SSL", "false").lower() == "true"
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "qbu-crawler")
MINIO_PUBLIC_URL = os.getenv("MINIO_PUBLIC_URL", "https://minio-api.forcome.com")

# ── Server ──────────────────────────────────────────
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))
API_KEY = os.getenv("API_KEY", "")
LOCAL_API_BASE_URL = os.getenv("LOCAL_API_BASE_URL", "") or f"http://127.0.0.1:{SERVER_PORT}"

# ── Task Manager ────────────────────────────────────
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "3"))
TASK_STALE_SECONDS = int(os.getenv("TASK_STALE_SECONDS", "900"))
WORKFLOW_INTERVAL = int(os.getenv("WORKFLOW_INTERVAL", "15"))
WORKFLOW_NOTIFICATION_TARGET = os.getenv("WORKFLOW_NOTIFICATION_TARGET", "workflow")
NOTIFIER_INTERVAL = int(os.getenv("NOTIFIER_INTERVAL", "5"))
NOTIFIER_LEASE_SECONDS = int(os.getenv("NOTIFIER_LEASE_SECONDS", "60"))
NOTIFIER_MAX_ATTEMPTS = int(os.getenv("NOTIFIER_MAX_ATTEMPTS", "3"))

# ── Rollout Feature Flags ───────────────────────────
NOTIFICATION_MODE = _enum_env(
    "NOTIFICATION_MODE",
    "legacy",
    ("legacy", "shadow", "outbox"),
)
DAILY_SUBMIT_MODE = _enum_env(
    "DAILY_SUBMIT_MODE",
    "openclaw",
    ("openclaw", "embedded"),
)
REPORT_MODE = _enum_env(
    "REPORT_MODE",
    "legacy",
    ("legacy", "snapshot_fast_full"),
)
AI_DIGEST_MODE = _enum_env(
    "AI_DIGEST_MODE",
    "off",
    ("off", "async"),
)
DAILY_SCHEDULER_TIME = _clock_time_env("DAILY_SCHEDULER_TIME", "08:00")
DAILY_SCHEDULER_INTERVAL = int(os.getenv("DAILY_SCHEDULER_INTERVAL", "30"))
DAILY_SCHEDULER_RETRY_SECONDS = int(os.getenv("DAILY_SCHEDULER_RETRY_SECONDS", "300"))
WEEKLY_SCHEDULER_TIME = _clock_time_env("WEEKLY_SCHEDULER_TIME", "09:30")
WORKFLOW_TRANSLATION_WAIT_SECONDS = int(os.getenv("WORKFLOW_TRANSLATION_WAIT_SECONDS", "900"))

# ── OpenClaw Webhook（任务完成即时通知）────────────
OPENCLAW_HOOK_URL = os.getenv("OPENCLAW_HOOK_URL", "")      # e.g. http://127.0.0.1:18789
OPENCLAW_HOOK_TOKEN = os.getenv("OPENCLAW_HOOK_TOKEN", "")   # hooks.token in openclaw.json
OPENCLAW_BRIDGE_URL = os.getenv("OPENCLAW_BRIDGE_URL", "")
OPENCLAW_BRIDGE_TOKEN = os.getenv("OPENCLAW_BRIDGE_TOKEN", "")
OPENCLAW_BRIDGE_TIMEOUT = int(os.getenv("OPENCLAW_BRIDGE_TIMEOUT", "15"))

# ── LLM Translation (OpenAI-compatible) ───────────
LLM_API_BASE = os.getenv("LLM_API_BASE", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_TRANSLATE_BATCH_SIZE = int(os.getenv("LLM_TRANSLATE_BATCH_SIZE", "20"))

# ── Translation Worker ────────────────────────
TRANSLATE_INTERVAL = int(os.getenv("TRANSLATE_INTERVAL", "60"))
TRANSLATE_MAX_RETRIES = int(os.getenv("TRANSLATE_MAX_RETRIES", "3"))
TRANSLATE_WORKERS = int(os.getenv("TRANSLATE_WORKERS", "3"))

# ── Email SMTP ────────────────────────────────────
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "")
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "false").lower() == "true"

# ── Report ────────────────────────────────────────
REPORT_LABEL_MODE = _enum_env("REPORT_LABEL_MODE", "rule", ("rule", "hybrid"))
REPORT_PERSPECTIVE = _enum_env("REPORT_PERSPECTIVE", "dual", ("dual", "window"))
# PDF config removed in V3 — Playwright pipeline eliminated
# ── Report Thresholds ─────────────────────────────
NEGATIVE_THRESHOLD = int(os.getenv("REPORT_NEGATIVE_THRESHOLD", "2"))
LOW_RATING_THRESHOLD = int(os.getenv("REPORT_LOW_RATING_THRESHOLD", "3"))
HEALTH_RED = int(os.getenv("REPORT_HEALTH_RED", "45"))
HEALTH_YELLOW = int(os.getenv("REPORT_HEALTH_YELLOW", "60"))
HIGH_RISK_THRESHOLD = int(os.getenv("REPORT_HIGH_RISK_THRESHOLD", "35"))
REPORT_OFFLINE_MODE = os.getenv("REPORT_OFFLINE_MODE", "false").lower() == "true"
REPORT_HTML_PUBLIC_URL = os.getenv("REPORT_HTML_PUBLIC_URL", "")
REPORT_DIR = os.getenv("REPORT_DIR", "") or os.path.join(DATA_DIR, "reports")
REPORT_CLUSTER_ANALYSIS = os.getenv("REPORT_CLUSTER_ANALYSIS", "true").lower() == "true"
REPORT_MAX_CLUSTER_ANALYSIS = int(os.getenv("REPORT_MAX_CLUSTER_ANALYSIS", "3"))
SAFETY_TIERS_PATH = os.getenv("SAFETY_TIERS_PATH", os.path.join(DATA_DIR, "safety_tiers.json"))
os.makedirs(REPORT_DIR, exist_ok=True)
OPENCLAW_WORKSPACE_DIR = os.getenv("OPENCLAW_WORKSPACE_DIR", "") or os.path.join(
    BASE_DIR,
    "qbu_crawler",
    "server",
    "openclaw",
    "workspace",
)
DAILY_SOURCE_CSV_PATH = os.getenv("DAILY_SOURCE_CSV_PATH", "") or os.path.join(
    OPENCLAW_WORKSPACE_DIR,
    "data",
    "sku-list-source.csv",
)
DAILY_PRODUCT_CSV_PATH = os.getenv("DAILY_PRODUCT_CSV_PATH", "") or os.path.join(
    OPENCLAW_WORKSPACE_DIR,
    "data",
    "sku-product-details.csv",
)
DAILY_SOURCE_CSV_URL = os.getenv("DAILY_SOURCE_CSV_URL", "").strip()
DAILY_PRODUCT_CSV_URL = os.getenv("DAILY_PRODUCT_CSV_URL", "").strip()
_validate_paired_env(
    "DAILY_SOURCE_CSV_URL",
    DAILY_SOURCE_CSV_URL,
    "DAILY_PRODUCT_CSV_URL",
    DAILY_PRODUCT_CSV_URL,
)
EMAIL_RECIPIENTS = [
    addr.strip()
    for addr in os.getenv("EMAIL_RECIPIENTS", "").split(",")
    if addr.strip()
]
EMAIL_BCC_MODE = os.getenv("EMAIL_BCC_MODE", "false").lower() == "true"

# ── P008 Phase 2: Recipient channels ──────────────────────
EMAIL_RECIPIENTS_EXEC = [
    addr.strip()
    for addr in os.getenv("EMAIL_RECIPIENTS_EXEC", "").split(",")
    if addr.strip()
]
EMAIL_RECIPIENTS_SAFETY = [
    addr.strip()
    for addr in os.getenv("EMAIL_RECIPIENTS_SAFETY", "").split(",")
    if addr.strip()
]

# ── P008 Phase 2: Tier configurations ─────────────────────
TIER_CONFIGS = {
    "daily": {
        "window": "24h",
        "cumulative": True,
        "dimensions": ["kpi", "clusters", "competitive_gap", "attention_signals"],
        "template": "daily_briefing.html.j2",
        "excel": False,
        "delivery": {"email": "smart", "archive": True},
    },
    "weekly": {
        "window": "7d",
        "cumulative": True,
        "dimensions": ["kpi", "clusters", "competitive_gap",
                        "risk_ranking", "heatmap", "trend_charts"],
        "template": "weekly_report.html.j2",
        "excel": True,
        "delivery": {"email": "always", "archive": True},
    },
    "monthly": {
        "window": "month",
        "cumulative": True,
        "dimensions": ["kpi", "clusters", "competitive_gap",
                        "risk_ranking", "heatmap", "trend_charts",
                        "category_benchmark", "issue_lifecycle",
                        "product_scorecard", "executive_summary"],
        "template": "monthly_report.html.j2",
        "excel": True,
        "delivery": {"email": "always", "archive": True},
    },
}

# ── Timezone ──────────────────────────────────────────
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def now_shanghai() -> datetime:
    """Return current time in Asia/Shanghai timezone."""
    return datetime.now(SHANGHAI_TZ)


# ── SQL Query Limits ────────────────────────────────
SQL_QUERY_TIMEOUT = 5
SQL_QUERY_MAX_ROWS = 500
