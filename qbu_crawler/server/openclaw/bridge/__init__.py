"""Hardened notification bridge for must-deliver OpenClaw messaging."""

from .app import BridgeSettings, create_bridge_app

__all__ = ["BridgeSettings", "create_bridge_app"]
