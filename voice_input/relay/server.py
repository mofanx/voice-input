"""Relay Server CLI 入口。"""

import argparse
import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .protocol import (
    ERR_AGENT_OFFLINE,
    ERR_INTERNAL,
    ERR_REQUEST_TIMEOUT,
    ERR_UNAUTHORIZED,
    TYPE_HELLO,
    TYPE_RESPONSE,
    hello_ok_message,
    new_request_id,
    request_message,
    require_optional_dependency,
)


LOG = logging.getLogger("voice_input.relay.server")
RELAY_TOKEN_COOKIE = "voice_input_relay_token"
PUBLIC_PROXY_PATHS = {
    "manifest.json",
    "sw.js",
    "icon.svg",
    "icon-192.png",
    "icon-512.png",
}


@dataclass
class RelayState:
    client_token: str = ""
    agent_token: str = ""
    default_device: str = "default"
    request_timeout: float = 30.0
    agent_ws: Optional[Any] = None
    agent_device: str = ""
    pending: Dict[str, asyncio.Future] = field(default_factory=dict)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="voice-input Relay Server")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=8787, help="监听端口，默认 8787")
    parser.add_argument("--client-token", default="", help="手机端访问 Relay 使用的 token")
    parser.add_argument("--agent-token", default="", help="Agent 注册 Relay 使用的 token")
    parser.add_argument("--default-device", default="default", help="默认设备 ID")
    parser.add_argument("--timeout", type=float, default=30.0, help="转发请求超时时间（秒）")
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"], help="日志级别")
    return parser


def _json_response(payload: Any, status: int = 200):
    from fastapi.responses import JSONResponse

    return JSONResponse(payload, status_code=status)


def _error_response(code: str, message: str, status: int):
    return _json_response({"code": status, "error": {"code": code, "message": message}, "message": message}, status)


def _check_client_token(req: Any, state: RelayState) -> bool:
    if not state.client_token:
        return True
    token = req.headers.get("x-auth-token") or req.query_params.get("token") or req.cookies.get(RELAY_TOKEN_COOKIE) or ""
    return token == state.client_token


def _should_set_client_cookie(req: Any, state: RelayState) -> bool:
    if not state.client_token:
        return False
    return (req.query_params.get("token") or "") == state.client_token


def _set_client_cookie(resp: Any, state: RelayState) -> Any:
    if state.client_token:
        resp.set_cookie(
            RELAY_TOKEN_COOKIE,
            state.client_token,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=30 * 24 * 60 * 60,
        )
    return resp


async def _body_for_request(req: Any) -> Any:
    content_type = req.headers.get("content-type", "")
    raw = await req.body()
    if not raw:
        return None
    if "application/json" in content_type:
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return raw.decode("utf-8", errors="replace")
    return raw.decode("utf-8", errors="replace")


def create_app(state: RelayState):
    from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import Response

    app = FastAPI(title="voice-input Relay Server")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "X-Auth-Token", "Authorization"],
        max_age=86400,
    )

    @app.websocket("/relay/agent")
    async def relay_agent(ws: WebSocket):
        await ws.accept()
        try:
            raw = await ws.receive_text()
            hello = json.loads(raw)
            if hello.get("type") != TYPE_HELLO:
                await ws.close(code=1008)
                return
            token = str(hello.get("token") or "")
            if state.agent_token and token != state.agent_token:
                await ws.close(code=1008)
                return
            device_id = str(hello.get("device_id") or state.default_device)
            state.agent_ws = ws
            state.agent_device = device_id
            await ws.send_text(json.dumps(hello_ok_message(device_id)))
            LOG.info("Agent 已连接: %s", device_id)
            while True:
                msg = json.loads(await ws.receive_text())
                if msg.get("type") == TYPE_RESPONSE:
                    req_id = str(msg.get("id") or "")
                    fut = state.pending.pop(req_id, None)
                    if fut and not fut.done():
                        fut.set_result(msg)
        except WebSocketDisconnect:
            LOG.warning("Agent 已断开")
        except Exception as exc:
            LOG.warning("Agent 连接错误: %s", exc)
        finally:
            if state.agent_ws is ws:
                state.agent_ws = None
                state.agent_device = ""
            for _, fut in list(state.pending.items()):
                if not fut.done():
                    fut.set_exception(RuntimeError("agent disconnected"))
            state.pending.clear()

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
    async def proxy(path: str, req: Request):
        if path == "relay/health":
            return _json_response({"code": 200, "agent_online": state.agent_ws is not None})

        if path not in PUBLIC_PROXY_PATHS and not _check_client_token(req, state):
            return _error_response(ERR_UNAUTHORIZED, "unauthorized", 401)

        if state.agent_ws is None:
            return _error_response(ERR_AGENT_OFFLINE, "relay agent offline", 503)

        req_id = new_request_id()
        query = req.url.query
        body = await _body_for_request(req)
        headers = {k: v for k, v in req.headers.items()}
        msg = request_message(
            req.method,
            "/" + path,
            query=query,
            headers=headers,
            body=body,
            timeout_ms=int(state.request_timeout * 1000),
            request_id=req_id,
        )

        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        state.pending[req_id] = fut
        try:
            async with state.send_lock:
                await state.agent_ws.send_text(json.dumps(msg))
            resp = await asyncio.wait_for(fut, timeout=state.request_timeout)
        except asyncio.TimeoutError:
            state.pending.pop(req_id, None)
            resp = _error_response(ERR_REQUEST_TIMEOUT, "request timeout", 504)
            return _set_client_cookie(resp, state) if _should_set_client_cookie(req, state) else resp
        except Exception as exc:
            state.pending.pop(req_id, None)
            LOG.warning("转发失败: %s", exc)
            resp = _error_response(ERR_INTERNAL, str(exc), 502)
            return _set_client_cookie(resp, state) if _should_set_client_cookie(req, state) else resp

        status = int(resp.get("status") or 502)
        body = resp.get("body")
        resp_headers = resp.get("headers") or {}
        content_type = resp_headers.get("content-type", "")
        if isinstance(body, (dict, list)):
            out = _json_response(body, status)
        else:
            out = Response(content=str(body or ""), status_code=status, media_type=content_type or None)
        return _set_client_cookie(out, state) if _should_set_client_cookie(req, state) else out

    return app


def main(argv=None) -> int:
    require_optional_dependency("fastapi", "relay-server")
    require_optional_dependency("uvicorn", "relay-server")
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper()), format="%(asctime)s %(levelname)s %(message)s")
    import uvicorn

    state = RelayState(
        client_token=args.client_token,
        agent_token=args.agent_token,
        default_device=args.default_device,
        request_timeout=args.timeout,
    )
    app = create_app(state)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    main()
