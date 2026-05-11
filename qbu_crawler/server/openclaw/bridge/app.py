"""FastAPI app for forwarding deterministic notifications through OpenClaw CLI."""

from __future__ import annotations

import ipaddress
import json
import os
import subprocess
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
import uvicorn


DEFAULT_TEMPLATES = {
    "task_completed": (
        "## {task_heading}\n\n"
        "- **目标**：{target_summary}\n"
        "- **站点**：{site}\n"
        "- **归属**：{ownership}\n"
        "- **任务类型**：{task_type}\n"
        "- **结果**：{result_summary}\n\n"
        "### 本次产出\n"
        "- **产品记录**：{product_count} 个\n"
        "- **新增评论**：{review_count} 条\n"
        "- **失败项**：{failed_summary}\n\n"
        "- **任务 ID**：{task_id}"
    ),
    "workflow_started": (
        "## 🚀 每日任务已启动\n\n"
        "- **日期**：{logical_date}\n"
        "- **状态**：已触发\n"
        "- **workflow**：{run_id}\n"
        "- **分类采集任务**：{collect_count}\n"
        "- **产品抓取任务**：{scrape_count}\n\n"
        "后续会继续跟进执行、快报和完整报告状态。"
    ),
    "workflow_fast_report": (
        "## 📊 每日快报已生成\n\n"
        "- **日期**：{logical_date}\n"
        "- **状态**：快报已生成\n"
        "- **workflow**：{run_id}\n"
        "- **产品数**：{products_count}\n"
        "- **已入库评论数**：{reviews_count}\n"
        "- **翻译进度**：{translated_count}/{reviews_count}\n\n"
        "完整版报告生成后会继续通知。"
    ),
    "workflow_full_report": (
        "## ✅ 报告产物已生成\n\n"
        "- **日期**：{logical_date}\n"
        "- **workflow**：{run_id}\n"
        "- **本地报告产物**：{report_generation_status}\n"
        "- **附件**：{excel_path}\n"
        "- **业务邮件**：{email_status}\n\n"
        "如需，我可以继续补充差评、价格波动和竞品对比解读。"
    ),
    "workflow_daily_digest": "{markdown}",
    "workflow_report_skipped": (
        "## ✅ 每日任务已完成\n\n"
        "- **日期**：{logical_date}\n"
        "- **workflow**：{run_id}\n"
        "- **产品数**：{products_count}\n"
        "- **新增评论数**：{reviews_count}\n"
        "- **说明**：新增评论为 0，已跳过 Excel 生成和邮件发送"
    ),
    "workflow_attention": (
        "## ⚠️ 任务需要人工关注\n\n"
        "- **日期**：{logical_date}\n"
        "- **原因**：{reason}"
    ),
}


@dataclass(frozen=True)
class BridgeSettings:
    auth_token: str
    allowed_sources: set[str]
    allowed_targets: set[str]
    command: list[str]
    channel: str = "dingtalk"
    request_timeout: int = 15
    message_flag: str = "--message"
    templates: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_TEMPLATES))


class NotifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str
    template_key: str
    template_vars: dict[str, Any] = Field(default_factory=dict)
    dedupe_key: str


def create_bridge_app(settings: BridgeSettings) -> FastAPI:
    app = FastAPI(title="Qbu OpenClaw Notify Bridge", version="1.0.0")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/notify")
    async def notify(
        payload: NotifyRequest,
        request: Request,
        x_bridge_token: str = Header(default="", alias="X-Bridge-Token"),
        x_forwarded_for: str = Header(default="", alias="X-Forwarded-For"),
    ):
        if not settings.auth_token or x_bridge_token != settings.auth_token:
            raise HTTPException(status_code=401, detail="invalid bridge token")

        source = _extract_source(request, x_forwarded_for)
        if settings.allowed_sources and not _source_allowed(source, settings.allowed_sources):
            raise HTTPException(status_code=403, detail="source not allowed")

        normalized_target = _normalize_target(settings, payload.target)
        if settings.allowed_targets and not _target_allowed(
            payload.target,
            normalized_target,
            settings.allowed_targets,
        ):
            raise HTTPException(status_code=403, detail="target not allowed")

        template = settings.templates.get(payload.template_key)
        if not template:
            raise HTTPException(status_code=400, detail="template not allowed")

        message = _render_template(template, payload.template_vars)
        result = _send_via_openclaw(settings, payload.target, message)
        result["dedupe_key"] = payload.dedupe_key
        result["source"] = source
        return result

    return app


def _extract_source(request: Request, x_forwarded_for: str) -> str:
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    client = request.client
    return client.host if client else ""


def _source_allowed(source: str, allowlist: set[str]) -> bool:
    if not source:
        return False
    try:
        source_ip = ipaddress.ip_address(source)
    except ValueError:
        return source in allowlist

    for allowed in allowlist:
        if "/" in allowed:
            try:
                if source_ip in ipaddress.ip_network(allowed, strict=False):
                    return True
            except ValueError:
                continue
        elif source == allowed:
            return True
    return False


def _render_template(template: str, template_vars: dict[str, Any]) -> str:
    safe_vars = {
        key: "" if value is None else str(value)
        for key, value in template_vars.items()
    }
    if safe_vars.get("email_status"):
        safe_vars["email_status"] = _display_email_status(safe_vars["email_status"])
    if safe_vars.get("report_generation_status"):
        safe_vars["report_generation_status"] = _display_report_generation_status(
            safe_vars["report_generation_status"]
        )
    if safe_vars.get("workflow_notification_status"):
        safe_vars["workflow_notification_status"] = _display_workflow_notification_status(
            safe_vars["workflow_notification_status"]
        )
    defaults = {
        "task_heading": "✅ 任务已完成",
        "task_type": "",
        "status": "",
        "task_id": "",
        "summary": "",
        "target_summary": "",
        "site": "",
        "ownership": "",
        "result_summary": "",
        "product_count": "",
        "review_count": "",
        "failed_summary": "",
        "logical_date": "",
        "run_id": "",
        "collect_count": "",
        "scrape_count": "",
        "product_count": "",
        "review_count": "",
        "products_count": "",
        "reviews_count": "",
        "translated_count": "",
        "untranslated_count": "",
        "excel_path": "",
        "email_status": "",
        "report_generation_status": "",
        "workflow_notification_status": "",
        "reason": "",
    }
    defaults.update(safe_vars)
    return template.format_map(defaults).strip()


def _send_via_openclaw(settings: BridgeSettings, target: str, message: str) -> dict[str, Any]:
    normalized_target = _normalize_target(settings, target)
    completed = subprocess.run(
        [
            *settings.command,
            "--channel",
            settings.channel,
            "--target",
            normalized_target,
            settings.message_flag,
            message,
        ],
        capture_output=True,
        text=True,
        timeout=settings.request_timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "openclaw message send failed",
                "exit_code": completed.returncode,
                "stderr": (completed.stderr or "").strip(),
            },
        )

    bridge_request_id = _extract_message_id(completed.stdout) or f"bridge-{uuid.uuid4().hex}"
    return {
        "bridge_request_id": bridge_request_id,
        "http_status": 200,
    }


def _normalize_target(settings: BridgeSettings, target: str) -> str:
    if settings.channel == "dingtalk" and target.startswith("chat:"):
        return "channel:" + target[5:]
    return target


def _target_allowed(raw_target: str, normalized_target: str, allowlist: set[str]) -> bool:
    return raw_target in allowlist or normalized_target in allowlist


def _extract_message_id(stdout: str) -> str:
    text = (stdout or "").strip()
    if not text:
        return ""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return ""
    if not isinstance(data, dict):
        return ""
    for key in ("message_id", "request_id", "id"):
        value = data.get(key)
        if value:
            return str(value)
    return ""


def _display_email_status(status: str) -> str:
    value = status.strip().lower()
    if value == "success":
        return "已发送"
    if value == "failed":
        return "发送失败"
    if value == "skipped":
        return "已跳过（无新增评论）"
    return status


def _display_report_generation_status(status: str) -> str:
    value = status.strip().lower()
    if value == "generated":
        return "已生成"
    if value == "failed":
        return "生成失败"
    if value == "pending":
        return "生成中"
    if value == "skipped":
        return "已跳过"
    if value == "unknown":
        return "未知"
    return status


def _display_workflow_notification_status(status: str) -> str:
    value = status.strip().lower()
    if value == "sent":
        return "已送达"
    if value == "pending":
        return "待投递"
    if value == "deadletter":
        return "投递失败（deadletter）"
    if value == "partial":
        return "部分送达"
    if value == "skipped":
        return "已跳过"
    if value == "unknown":
        return "未知"
    return status


def build_settings_from_env() -> BridgeSettings:
    command_text = os.getenv("OPENCLAW_MESSAGE_COMMAND", "openclaw message send").strip()
    command = [part for part in command_text.split(" ") if part]
    return BridgeSettings(
        auth_token=os.getenv("QBU_OPENCLAW_BRIDGE_TOKEN", ""),
        allowed_sources=_csv_set("QBU_OPENCLAW_BRIDGE_ALLOWED_SOURCES"),
        allowed_targets=_csv_set("QBU_OPENCLAW_BRIDGE_ALLOWED_TARGETS"),
        command=command,
        channel=os.getenv("QBU_OPENCLAW_BRIDGE_CHANNEL", "dingtalk"),
        request_timeout=int(os.getenv("QBU_OPENCLAW_BRIDGE_TIMEOUT", "15")),
        message_flag=os.getenv("QBU_OPENCLAW_BRIDGE_MESSAGE_FLAG", "--message"),
    )


def main():
    settings = build_settings_from_env()
    app = create_bridge_app(settings)
    uvicorn.run(
        app,
        host=os.getenv("QBU_OPENCLAW_BRIDGE_HOST", "127.0.0.1"),
        port=int(os.getenv("QBU_OPENCLAW_BRIDGE_PORT", "18888")),
    )


def _csv_set(env_name: str) -> set[str]:
    return {item.strip() for item in os.getenv(env_name, "").split(",") if item.strip()}


if __name__ == "__main__":
    main()
