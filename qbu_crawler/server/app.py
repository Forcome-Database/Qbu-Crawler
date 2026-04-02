"""Application entry point — FastAPI + FastMCP in one ASGI process."""

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastmcp import FastMCP

from qbu_crawler import config, models
from qbu_crawler.server.api.tasks import router as tasks_router
from qbu_crawler.server.api.products import router as products_router
from qbu_crawler.server.mcp.tools import register_tools
from qbu_crawler.server.mcp.resources import register_resources
from qbu_crawler.server.runtime import runtime, task_manager, translator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

# Suppress noisy Pydantic validation errors when MCP clients send
# notifications (e.g. notifications/initialized) with an id field,
# causing them to be parsed as requests and fail validation.
logging.getLogger("mcp.shared.session").setLevel(logging.ERROR)

# ── Shared singletons ──────────────────────────────
# ── MCP Server ──────────────────────────────────────
mcp = FastMCP(
    "Qbu-Crawler",
    instructions=(
        "多站点产品数据爬虫服务。可以启动爬虫任务采集产品信息和评论，"
        "查询已采集的产品、评论、价格历史等数据，"
        "支持 Bass Pro Shops、Meat Your Maker 和 Walton's 三个站点。"
        "如需执行复杂查询，请先通过 Resources 了解表结构，再使用 execute_sql。"
    ),
)
register_tools(mcp)
register_resources(mcp)

# ── MCP ASGI sub-app ────────────────────────────────
mcp_app = mcp.http_app(path="/")
@asynccontextmanager
async def app_lifespan(app_instance: FastAPI):
    models.init_db()
    runtime.start()
    async with mcp_app.lifespan(app_instance):
        yield
    runtime.stop()

# ── FastAPI app ─────────────────────────────────────
app = FastAPI(
    title="Qbu-Crawler API",
    description="多站点产品数据爬虫 HTTP API",
    version="1.0.0",
    lifespan=app_lifespan,
)
app.include_router(tasks_router)
app.include_router(products_router)

# Mount MCP at /mcp
app.mount("/mcp", mcp_app)


@app.get("/health")
async def health():
    return {"status": "ok"}


def start_server(host: str | None = None, port: int | None = None):
    """Start the ASGI server."""
    models.init_db()
    h = host or config.SERVER_HOST
    p = port or config.SERVER_PORT

    if not config.API_KEY:
        logger.warning("API_KEY not set — HTTP API will reject all requests")

    logger.info(f"Starting server on {h}:{p}")
    logger.info(f"  HTTP API: http://{h}:{p}/api")
    logger.info(f"  MCP:      http://{h}:{p}/mcp")
    logger.info(f"  Docs:     http://{h}:{p}/docs")

    uvicorn.run(app, host=h, port=p)
