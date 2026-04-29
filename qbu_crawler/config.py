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
#
# 强烈建议 CHROME_USER_DATA_PATH 指向一个 *专属* 目录（如 C:\QbuCrawlerProfile），
# 不要直接指向用户真实的 Chrome profile（如 %LOCALAPPDATA%\Google\Chrome\User Data）。
# 原因：用户个人 Chrome 会持有 SingletonLock，我们 Popen 的 Chrome 启动时会把命令
# IPC 给用户 Chrome 后自己退出，port 永远起不来，导致采集死循环。
#
# CHROME_USER_DATA_SEED：用于首次种子复制的真实 profile 路径（如
# %LOCALAPPDATA%\Google\Chrome\User Data）。首次运行若 CHROME_USER_DATA_PATH 不存在，
# 会从 seed 目录只复制关键 cookie 文件（不复制扩展/缓存/历史，避免 GB 级复制）。
CHROME_USER_DATA_PATH = os.getenv("CHROME_USER_DATA_PATH", "")  # 留空则用独立浏览器
CHROME_USER_DATA_SEED = os.getenv("CHROME_USER_DATA_SEED", "")  # 留空则不做种子复制
CHROME_USER_DATA_COPY_PREFERENCES = os.getenv("CHROME_USER_DATA_COPY_PREFERENCES", "false").lower() == "true"
CHROME_USER_DATA_COPY_LOCAL_STATE = os.getenv("CHROME_USER_DATA_COPY_LOCAL_STATE", "false").lower() == "true"
CHROME_USER_DATA_SYNC_FILES = [
    ("Default", "Cookies"),
    ("Default", "Cookies-journal"),
]
if CHROME_USER_DATA_COPY_PREFERENCES:
    CHROME_USER_DATA_SYNC_FILES.append(("Default", "Preferences"))
if CHROME_USER_DATA_COPY_LOCAL_STATE:
    CHROME_USER_DATA_SYNC_FILES.append(("", "Local State"))


def _chrome_profile_needs_seed() -> bool:
    """判断专属 profile 是否需要 seed。
    - 目录不存在 → 首次初始化，需要
    - 目录存在但 Default/Cookies 缺失或 size=0 → 上次 seed 失败（如源 Chrome 正在跑时
      Cookies 被锁 → copy2 抛异常被吞），原逻辑的 isdir 短路会让 profile 永久缺 _abck
      cookie；这里兜底重 seed
    """
    if not os.path.isdir(CHROME_USER_DATA_PATH):
        return True
    cookies_path = os.path.join(CHROME_USER_DATA_PATH, "Default", "Cookies")
    try:
        return not os.path.isfile(cookies_path) or os.path.getsize(cookies_path) == 0
    except OSError:
        return True


def _seed_chrome_user_data():
    """从 CHROME_USER_DATA_SEED 复制关键文件到专属目录。
    默认只复制 Cookies，避免把真实 Chrome 的会话/启动状态带进爬虫专属 profile。
    有自愈能力：目录存在但 Cookies 缺失时会重 seed（见 _chrome_profile_needs_seed）。
    """
    import logging
    import shutil
    log = logging.getLogger(__name__)
    if not CHROME_USER_DATA_PATH or not CHROME_USER_DATA_SEED:
        return
    if not _chrome_profile_needs_seed():
        return
    if not os.path.isdir(CHROME_USER_DATA_SEED):
        log.error(
            f"[Chrome] seed 源目录不存在: {CHROME_USER_DATA_SEED}，"
            "无法初始化 _abck cookie，basspro 几乎必然被 Akamai 拒绝"
        )
        return
    dst_default = os.path.join(CHROME_USER_DATA_PATH, "Default")
    os.makedirs(dst_default, exist_ok=True)
    copied = []
    errors = []
    cookies_ok = False
    for sub, name in CHROME_USER_DATA_SYNC_FILES:
        src = os.path.join(CHROME_USER_DATA_SEED, sub, name) if sub else os.path.join(CHROME_USER_DATA_SEED, name)
        dst = os.path.join(CHROME_USER_DATA_PATH, sub, name) if sub else os.path.join(CHROME_USER_DATA_PATH, name)
        if not os.path.isfile(src):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            shutil.copy2(src, dst)
            copied.append(name)
            if name == "Cookies":
                cookies_ok = True
        except Exception as e:
            errors.append((name, str(e)))
    if copied:
        log.warning(
            f"[Chrome] 已从 seed 目录 {CHROME_USER_DATA_SEED} 向专属目录 "
            f"{CHROME_USER_DATA_PATH} 复制关键文件: {copied}"
        )
    if errors:
        # 静默吞异常会让 profile 永久残缺；记 warning 让用户看得到、但不当紧急事件
        for name, msg in errors:
            log.warning(f"[Chrome] seed 复制 {name} 失败（通常因源 Chrome 持写锁）: {msg}")
    if not cookies_ok:
        # 生产观察：seed Cookies 失败属常态（源 Chrome 通常在跑），
        # 空白 profile + Akamai 自助 challenge 依然稳定。
        # 仅在 rot streak 自愈也无效时才需人工介入关闭真实 Chrome。
        log.info(
            "[Chrome] Default/Cookies 未 seed（源 Chrome 通常持写锁）。"
            "空白 profile + Akamai 自助 challenge 已足够稳定，无需额外操作。"
        )


_seed_chrome_user_data()

# 专属 profile 连续失败阈值：>= 该值则下次启动前自动删除 profile 并从 SEED 重建
# 每次失败 = 在 _get_page_user_data 里轮完所有代理仍无法解封，说明 _abck 已彻底失效
# 设 0 禁用自愈，保留原行为
CHROME_PROFILE_ROT_THRESHOLD = int(os.getenv("CHROME_PROFILE_ROT_THRESHOLD", "2"))

# 代理池 API（遇到反爬封锁时自动获取代理 IP）
# 示例: https://white.1024proxy.com/white/api?region=US&num=1&time=10&format=1&type=txt
PROXY_API_URL = os.getenv("PROXY_API_URL", "")
PROXY_MAX_RETRIES = int(os.getenv("PROXY_MAX_RETRIES", "3"))  # 单个 URL 最大代理轮换次数
# 指定站点直接使用代理，跳过直连尝试（逗号分隔站点标识，如 basspro,waltons）
PROXY_SITES = {s.strip() for s in os.getenv("PROXY_SITES", "").split(",") if s.strip()}

# 反爬配置
REQUEST_DELAY = (1, 3)  # 请求间随机延迟范围（秒），设为 None 禁用

# basspro 专属配置：Akamai session 层检测的针对性调整
# 调大 REQUEST_DELAY + 中途回首页刷 _abck sensor data，降低 session 层升级 challenge 概率
BASSPRO_REQUEST_DELAY = (
    int(os.getenv("BASSPRO_REQUEST_DELAY_MIN", "8")),
    int(os.getenv("BASSPRO_REQUEST_DELAY_MAX", "18")),
)
# 每 N 个产品后回首页停留，触发 Akamai bm-loader 的 sensor POST 刷新 _abck
# 设 0 禁用
BASSPRO_SESSION_REFRESH_EVERY = int(os.getenv("BASSPRO_SESSION_REFRESH_EVERY", "4"))

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
REPORT_CONTRACT_STRICT_MODE = os.getenv("REPORT_CONTRACT_STRICT_MODE", "true").lower() == "true"
REPORT_HTML_PUBLIC_URL = os.getenv("REPORT_HTML_PUBLIC_URL", "")
REPORT_DIR = os.getenv("REPORT_DIR", "") or os.path.join(DATA_DIR, "reports")
SCRAPE_QUALITY_ALERT_RATIO = float(os.getenv("SCRAPE_QUALITY_ALERT_RATIO", "0.10"))
SCRAPE_QUALITY_ALERT_RECIPIENTS = [
    s.strip() for s in os.getenv("SCRAPE_QUALITY_ALERT_RECIPIENTS", "").split(",")
    if s.strip()
]
REPORT_CLUSTER_ANALYSIS = os.getenv("REPORT_CLUSTER_ANALYSIS", "true").lower() == "true"
REPORT_MAX_CLUSTER_ANALYSIS = int(os.getenv("REPORT_MAX_CLUSTER_ANALYSIS", "3"))
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

# ── Timezone ──────────────────────────────────────────
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def now_shanghai() -> datetime:
    """Return current time in Asia/Shanghai timezone."""
    return datetime.now(SHANGHAI_TZ)


# ── SQL Query Limits ────────────────────────────────
SQL_QUERY_TIMEOUT = 5
SQL_QUERY_MAX_ROWS = 500
