import os

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
