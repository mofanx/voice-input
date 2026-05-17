"""Relay Agent CLI 入口。"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import Any, Dict
from urllib.parse import urljoin

from .protocol import (
    ERR_BAD_REQUEST,
    ERR_LOCAL_UNREACHABLE,
    TYPE_PING,
    TYPE_REQUEST,
    hello_message,
    pong_message,
    require_optional_dependency,
    response_message,
)


LOG = logging.getLogger("voice_input.relay.agent")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="voice-input Relay Agent")
    parser.add_argument("--relay", required=True, help="Relay WebSocket 地址，例如 wss://relay.example.com/relay/agent")
    parser.add_argument("--relay-token", required=True, help="Agent 连接 Relay 使用的 token")
    parser.add_argument("--device", default="default", help="设备 ID，默认 default")
    parser.add_argument("--local", default="http://127.0.0.1:8080", help="本地 voice-input 地址")
    parser.add_argument("--local-token", default="", help="本地 voice-input token")
    parser.add_argument("--timeout", type=float, default=30.0, help="本地请求超时时间（秒）")
    parser.add_argument("--reconnect", type=float, default=3.0, help="断线重连间隔（秒）")
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"], help="日志级别")
    return parser


def _safe_headers(headers: Dict[str, Any]) -> Dict[str, str]:
    skipped = {
        "host",
        "content-length",
        "connection",
        "upgrade",
        "x-auth-token",
        "authorization",
        "x-real-ip",
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-port",
        "x-forwarded-proto",
        "forwarded",
    }
    return {str(k): str(v) for k, v in (headers or {}).items() if str(k).lower() not in skipped}


def _local_url(base: str, path: str, query: str = "") -> str:
    url = urljoin(base.rstrip("/") + "/", path.lstrip("/"))
    if query:
        url += "?" + query.lstrip("?")
    return url


async def _handle_request(msg: Dict[str, Any], client: Any, local_base: str, local_token: str, timeout: float) -> Dict[str, Any]:
    request_id = str(msg.get("id") or "")
    if not request_id:
        return response_message("", 400, error=None, body={"code": ERR_BAD_REQUEST, "message": "missing request id"})

    method = str(msg.get("method") or "GET").upper()
    path = str(msg.get("path") or "/")
    query = str(msg.get("query") or "")
    headers = _safe_headers(msg.get("headers") or {})
    body = msg.get("body")
    if local_token:
        headers["X-Auth-Token"] = local_token

    try:
        resp = await client.request(
            method,
            _local_url(local_base, path, query),
            headers=headers,
            json=body if isinstance(body, (dict, list)) else None,
            content=body if isinstance(body, (str, bytes)) else None,
            timeout=timeout,
        )
        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                payload: Any = resp.json()
            except Exception:
                payload = resp.text
        else:
            payload = resp.text
        return response_message(
            request_id,
            resp.status_code,
            headers={"content-type": content_type} if content_type else {},
            body=payload,
        )
    except Exception as exc:
        LOG.warning("本地请求失败: %s", exc)
        return response_message(
            request_id,
            502,
            body={"code": ERR_LOCAL_UNREACHABLE, "message": str(exc)},
        )


async def run_agent(args: argparse.Namespace) -> None:
    import httpx
    import websockets

    while True:
        try:
            LOG.info("连接 Relay: %s", args.relay)
            async with websockets.connect(args.relay, ping_interval=20, ping_timeout=20) as ws:
                await ws.send(json.dumps(hello_message(args.device, args.relay_token, args.local)))
                async with httpx.AsyncClient() as client:
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except Exception:
                            LOG.warning("收到无法解析的 Relay 消息")
                            continue

                        msg_type = msg.get("type")
                        if msg_type == TYPE_PING:
                            await ws.send(json.dumps(pong_message(msg.get("ts"))))
                        elif msg_type == TYPE_REQUEST:
                            response = await _handle_request(msg, client, args.local, args.local_token, args.timeout)
                            await ws.send(json.dumps(response))
                        else:
                            LOG.debug("忽略 Relay 消息: %s", msg_type)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            LOG.warning("Relay 连接断开: %s", exc)
            await asyncio.sleep(args.reconnect)


def main(argv=None) -> int:
    require_optional_dependency("websockets", "relay-agent")
    require_optional_dependency("httpx", "relay-agent")
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper()), format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(run_agent(args))
    except KeyboardInterrupt:
        LOG.info("Relay Agent 已停止")
    except Exception as exc:
        raise SystemExit(f"Relay Agent 启动失败: {exc}") from exc
    return 0


if __name__ == "__main__":
    main()
