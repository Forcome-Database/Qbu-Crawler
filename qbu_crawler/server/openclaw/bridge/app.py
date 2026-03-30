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
        "任务完成通知\n"
        "类型: {task_type}\n"
        "状态: {status}\n"
        "任务ID: {task_id}\n"
        "摘要: {summary}"
    ),
    "workflow_started": (
        "每日任务已启动\n"
        "日期: {logical_date}\n"
        "采集任务: {collect_count}\n"
        "抓取任务: {scrape_count}"
    ),
    "workflow_fast_report": (
        "快报已生成\n"
        "日期: {logical_date}\n"
        "产品数: {product_count}\n"
        "评论数: {review_count}\n"
        "翻译完成: {translated_count}/{review_count}"
    ),
    "workflow_full_report": (
        "完整版报告已生成\n"
        "日期: {logical_date}\n"
        "附件: {excel_path}\n"
        "邮件: {email_status}"
    ),
    "workflow_attention": (
        "需要人工关注\n"
        "日期: {logical_date}\n"
        "原因: {reason}"
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

        if settings.allowed_targets and payload.target not in settings.allowed_targets:
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
    defaults = {
        "task_type": "",
        "status": "",
        "task_id": "",
        "summary": "",
        "logical_date": "",
        "collect_count": "",
        "scrape_count": "",
        "product_count": "",
        "review_count": "",
        "translated_count": "",
        "excel_path": "",
        "email_status": "",
        "reason": "",
    }
    defaults.update(safe_vars)
    return template.format_map(defaults).strip()


def _send_via_openclaw(settings: BridgeSettings, target: str, message: str) -> dict[str, Any]:
    completed = subprocess.run(
        [
            *settings.command,
            "--channel",
            settings.channel,
            "--target",
            target,
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
