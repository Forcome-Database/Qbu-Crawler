"""
统一管理：
1. 在 import 业务模块之前设置所有 env
2. 提供 load_business() 懒加载业务模块并返回所需对象
3. 保证业务模块在整个进程生命周期内只 import 一次
"""
import os
from types import SimpleNamespace
from . import config


_LOADED = None


def set_env():
    """Must be called BEFORE first business import. Idempotent."""
    config.SIM_DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.REPORT_WORK_DIR.mkdir(parents=True, exist_ok=True)
    config.CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

    # QBU_DATA_DIR drives DB_PATH resolution in qbu_crawler/config.py
    os.environ["QBU_DATA_DIR"] = str(config.SIM_DATA_DIR)
    os.environ["REPORT_DIR"] = str(config.REPORT_WORK_DIR)

    # Simulation: disable outbound side-effects so business code is fully
    # deterministic and self-contained.
    #   - SMTP_HOST cleared => send_email short-circuits with
    #     {"success": False, "error": "SMTP_HOST not configured"}
    #   - OPENCLAW_HOOK_URL cleared => _maybe_trigger_ai_digest no-ops
    os.environ["SMTP_HOST"] = ""
    os.environ["OPENCLAW_HOOK_URL"] = ""
    os.environ["OPENCLAW_BRIDGE_URL"] = ""


def load_business():
    """Lazy import business modules and return a namespace handle."""
    global _LOADED
    if _LOADED is not None:
        return _LOADED
    set_env()
    from qbu_crawler import config as qbu_config
    from qbu_crawler import models
    from qbu_crawler.server import workflows, report_snapshot

    # Sanity check: business cached DB_PATH must equal our sim DB
    expected = str(config.SIM_DB)
    if str(qbu_config.DB_PATH) != expected:
        raise RuntimeError(
            f"Business DB_PATH={qbu_config.DB_PATH!r} != simulation DB={expected!r}. "
            "env_bootstrap must run before any qbu_crawler import."
        )

    if not config.SIM_DB.exists():
        raise RuntimeError(
            f"Simulation DB not found at {config.SIM_DB}. "
            "Run `python -m scripts.simulate_reports prepare` first."
        )

    # Apply schema migrations to the simulation DB so new columns / indexes
    # (e.g. workflow_runs.is_partial, idx_safety_incidents_review_level_mode)
    # added after the baseline snapshot was created are picked up.
    models.init_db()

    _LOADED = SimpleNamespace(
        config=qbu_config,
        models=models,
        workflows=workflows,
        report_snapshot=report_snapshot,
    )
    return _LOADED
