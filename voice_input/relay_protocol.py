"""Relay 协议辅助函数。"""

from __future__ import annotations

import os
import secrets
import time
from typing import Any


DEFAULT_RELAY_PORT = 8090
DEFAULT_RELAY_TIMEOUT = 10.0
DEFAULT_RECONNECT_INTERVAL = 3.0


def now_ms() -> int:
    return int(time.time() * 1000)


def new_request_id() -> str:
    return secrets.token_urlsafe(16)


def normalize_base_url(url: str) -> str:
    return (url or "").strip().rstrip("/")


def normalize_ws_url(url: str) -> str:
    url = normalize_base_url(url)
    if url.startswith("http://"):
        url = "ws://" + url[len("http://"):]
    elif url.startswith("https://"):
        url = "wss://" + url[len("https://"):]
    if url and not url.endswith("/relay/ws"):
        url += "/relay/ws"
    return url


def get_bearer_token(headers: Any) -> str:
    auth = headers.get("Authorization", "") if headers else ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def get_relay_token(headers: Any) -> str:
    if not headers:
        return ""
    return (
        headers.get("X-Relay-Token", "")
        or headers.get("X-Auth-Token", "")
        or get_bearer_token(headers)
    ).strip()


def token_matches(provided: str, expected: str) -> bool:
    if not expected:
        return False
    return secrets.compare_digest(str(provided or ""), str(expected or ""))


def env_or(value: str, env_key: str, default: str = "") -> str:
    return value or os.environ.get(env_key, default)
