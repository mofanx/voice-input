"""Relay Server 与 Relay Agent 之间的协议定义。"""

from __future__ import annotations

import time
import uuid
import hmac
import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Optional


PROTOCOL_VERSION = 1


TYPE_HELLO = "hello"
TYPE_HELLO_OK = "hello_ok"
TYPE_REQUEST = "request"
TYPE_RESPONSE = "response"
TYPE_PING = "ping"
TYPE_PONG = "pong"
TYPE_ERROR = "error"


ERR_AGENT_OFFLINE = "AGENT_OFFLINE"
ERR_REQUEST_TIMEOUT = "REQUEST_TIMEOUT"
ERR_LOCAL_UNREACHABLE = "LOCAL_UNREACHABLE"
ERR_UNAUTHORIZED = "UNAUTHORIZED"
ERR_BAD_REQUEST = "BAD_REQUEST"
ERR_INTERNAL = "INTERNAL_ERROR"


@dataclass(frozen=True)
class RelayError:
    code: str
    message: str

    def to_dict(self) -> Dict[str, str]:
        return {"code": self.code, "message": self.message}


def now_ms() -> int:
    return int(time.time() * 1000)


def new_request_id() -> str:
    return "req_" + uuid.uuid4().hex


def derive_agent_token(token: str) -> str:
    if not token:
        return ""
    return hmac.new(token.encode("utf-8"), b"voice-input-relay-agent-v1", hashlib.sha256).hexdigest()


def hello_message(device_id: str, token: str, local_base_url: str, capabilities: Optional[list] = None) -> Dict[str, Any]:
    return {
        "type": TYPE_HELLO,
        "protocol": PROTOCOL_VERSION,
        "device_id": device_id,
        "token": token,
        "local_base_url": local_base_url,
        "capabilities": capabilities or ["http-proxy"],
    }


def hello_ok_message(device_id: str) -> Dict[str, Any]:
    return {
        "type": TYPE_HELLO_OK,
        "protocol": PROTOCOL_VERSION,
        "device_id": device_id,
        "server_time": now_ms(),
    }


def request_message(
    method: str,
    path: str,
    query: str = "",
    headers: Optional[Dict[str, str]] = None,
    body: Any = None,
    timeout_ms: int = 30000,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "type": TYPE_REQUEST,
        "id": request_id or new_request_id(),
        "method": method.upper(),
        "path": path,
        "query": query,
        "headers": headers or {},
        "body": body,
        "timeout_ms": timeout_ms,
    }


def response_message(
    request_id: str,
    status: int,
    headers: Optional[Dict[str, str]] = None,
    body: Any = None,
    error: Optional[RelayError] = None,
) -> Dict[str, Any]:
    msg: Dict[str, Any] = {
        "type": TYPE_RESPONSE,
        "id": request_id,
        "status": status,
        "headers": headers or {},
        "body": body,
    }
    if error is not None:
        msg["error"] = error.to_dict()
    return msg


def ping_message() -> Dict[str, Any]:
    return {"type": TYPE_PING, "ts": now_ms()}


def pong_message(ts: Optional[int] = None) -> Dict[str, Any]:
    return {"type": TYPE_PONG, "ts": ts or now_ms()}


def error_message(code: str, message: str, request_id: Optional[str] = None) -> Dict[str, Any]:
    msg: Dict[str, Any] = {
        "type": TYPE_ERROR,
        "error": {"code": code, "message": message},
    }
    if request_id:
        msg["id"] = request_id
    return msg


def require_optional_dependency(package: str, extra: str) -> None:
    try:
        __import__(package)
    except ImportError as exc:
        raise SystemExit(
            f"缺少可选依赖 {package!r}。请安装: pip install 'voice-input[{extra}]'"
        ) from exc
