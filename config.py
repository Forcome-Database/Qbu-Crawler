import os
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "products.db")

# 确保 data 目录存在
os.makedirs(DATA_DIR, exist_ok=True)

# DrissionPage 浏览器配置
HEADLESS = False  # 设为 True 可无头运行
PAGE_LOAD_TIMEOUT = 30  # 页面加载超时（秒）
LOAD_MODE = "eager"  # eager: DOM就绪即停(推荐) | normal: 等所有资源 | none: 连接即停
NO_IMAGES = True  # 禁止加载图片，减少带宽和加载时间

# 重试配置
RETRY_TIMES = 3  # 页面加载失败重试次数
RETRY_INTERVAL = 2  # 重试间隔（秒）

# 等待配置
BV_WAIT_TIMEOUT = 10  # Bazaarvoice 数据等待超时（秒）
BV_POLL_INTERVAL = 0.5  # BV 数据轮询间隔（秒）

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

# ── Task Manager ────────────────────────────────────
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "3"))

# ── LLM Translation (OpenAI-compatible) ───────────
LLM_API_BASE = os.getenv("LLM_API_BASE", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_TRANSLATE_BATCH_SIZE = int(os.getenv("LLM_TRANSLATE_BATCH_SIZE", "20"))

# ── Translation Worker ────────────────────────
TRANSLATE_INTERVAL = int(os.getenv("TRANSLATE_INTERVAL", "60"))
TRANSLATE_MAX_RETRIES = int(os.getenv("TRANSLATE_MAX_RETRIES", "3"))

# ── Email SMTP ────────────────────────────────────
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "")
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "false").lower() == "true"

# ── Report ────────────────────────────────────────
REPORT_DIR = os.getenv("REPORT_DIR", "") or os.path.join(BASE_DIR, "data", "reports")
os.makedirs(REPORT_DIR, exist_ok=True)
EMAIL_RECIPIENTS = [
    addr.strip()
    for addr in os.getenv("EMAIL_RECIPIENTS", "").split(",")
    if addr.strip()
]

# ── Timezone ──────────────────────────────────────────
SHANGHAI_TZ = timezone(timedelta(hours=8))


def now_shanghai() -> datetime:
    """Return current time in Asia/Shanghai timezone."""
    return datetime.now(SHANGHAI_TZ)


# ── SQL Query Limits ────────────────────────────────
SQL_QUERY_TIMEOUT = 5
SQL_QUERY_MAX_ROWS = 500
