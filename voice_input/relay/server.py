"""Relay Server CLI 入口。

支持多 agent 路由：
- 默认开放模式：任何 token 都能注册 agent，token 即路由 key
- Allowlist 模式：仅准入预配置的 token（CLI / 环境变量 / 文件）

token 在内存中以 sha256 哈希形式存储，日志和路由 key 都不暴露明文。
"""

import argparse
import asyncio
import hashlib
import hmac
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response

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

ENV_ALLOWLIST = "VOICE_INPUT_RELAY_ALLOWLIST"
ENV_ALLOWLIST_FILE = "VOICE_INPUT_RELAY_ALLOWLIST_FILE"


# ---------------------------------------------------------------------------
# 状态结构
# ---------------------------------------------------------------------------


@dataclass
class AgentSession:
    """单个已注册 agent 的连接状态。"""

    ws: Any
    device_id: str = "default"
    token_hash: str = ""
    pending: Dict[str, asyncio.Future] = field(default_factory=dict)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass
class RelayState:
    """Relay 全局状态。

    allowlist_hashes 为空集合时进入开放模式：任何 token 都可注册。
    """

    allowlist_hashes: Set[str] = field(default_factory=set)
    default_device: str = "default"
    request_timeout: float = 30.0
    agents: Dict[str, AgentSession] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Token 工具
# ---------------------------------------------------------------------------


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _check_allowlist(token: str, state: RelayState) -> bool:
    """开放模式下任何非空 token 通过；allowlist 模式下仅匹配项通过。"""
    if not token:
        return False
    if not state.allowlist_hashes:
        return True
    target = _hash_token(token)
    for allowed in state.allowlist_hashes:
        if hmac.compare_digest(target, allowed):
            return True
    return False


def _extract_token(req: Any) -> str:
    return (
        req.headers.get("x-auth-token")
        or req.query_params.get("token")
        or req.cookies.get(RELAY_TOKEN_COOKIE)
        or ""
    )


def _route_session(token: str, state: RelayState) -> Optional[AgentSession]:
    if not token:
        return None
    return state.agents.get(_hash_token(token))


def _load_allowlist(cli_file: str) -> Set[str]:
    """合并 CLI / 环境变量来源，返回 token 哈希集合。"""

    tokens: Set[str] = set()

    def _add(token: str) -> None:
        token = token.strip()
        if token and not token.startswith("#"):
            tokens.add(token)

    # 环境变量：逗号分隔
    env_list = os.getenv(ENV_ALLOWLIST, "")
    for item in env_list.split(","):
        _add(item)

    # 环境变量：文件路径
    env_file = os.getenv(ENV_ALLOWLIST_FILE, "")
    if env_file:
        try:
            with open(env_file, "r", encoding="utf-8") as fh:
                for line in fh:
                    _add(line)
        except OSError as exc:
            raise SystemExit(f"读取 allowlist 文件失败 ({env_file}): {exc}") from exc

    # CLI 文件（优先级最高）
    if cli_file:
        try:
            with open(cli_file, "r", encoding="utf-8") as fh:
                for line in fh:
                    _add(line)
        except OSError as exc:
            raise SystemExit(f"读取 allowlist 文件失败 ({cli_file}): {exc}") from exc

    return {_hash_token(t) for t in tokens}


# ---------------------------------------------------------------------------
# 响应工具
# ---------------------------------------------------------------------------


def _json_response(payload: Any, status: int = 200):
    return JSONResponse(payload, status_code=status)


def _error_response(code: str, message: str, status: int):
    return _json_response(
        {"code": status, "error": {"code": code, "message": message}, "message": message},
        status,
    )


def _should_set_cookie(req: Any) -> bool:
    """只有当 token 通过 query 参数传入时才写 cookie，避免覆盖。"""
    return bool(req.query_params.get("token"))


def _set_token_cookie(resp: Any, token: str) -> Any:
    if token:
        resp.set_cookie(
            RELAY_TOKEN_COOKIE,
            token,
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


# ---------------------------------------------------------------------------
# 落地页（未带 token 访问根路径时显示）
# ---------------------------------------------------------------------------


_LANDING_HTML = """<!doctype html>
<html lang=\"zh-CN\">
<head>
<meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>voice-input Relay</title>
<style>
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:420px;margin:48px auto;padding:0 20px;color:#222;line-height:1.5}
  h1{font-size:20px;margin:0 0 8px}
  p{color:#666;margin:8px 0 24px;font-size:14px}
  form{display:flex;gap:8px}
  input{flex:1;padding:10px 12px;border:1px solid #ccc;border-radius:6px;font-size:14px}
  button{padding:10px 16px;border:none;border-radius:6px;background:#1677ff;color:#fff;font-size:14px;cursor:pointer}
  button:hover{background:#0958d9}
  .err{color:#d4380d;font-size:13px;margin-bottom:12px}
</style>
</head>
<body>
<h1>voice-input Relay</h1>
<p>请输入您本地 voice-input 服务的 Token，进入对应的语音输入页面。</p>
__ERROR__
<form onsubmit=\"go(event)\">
  <input id=\"t\" name=\"token\" placeholder=\"输入 Token\" autofocus required>
  <button type=\"submit\">进入</button>
</form>
<script>
function go(e){e.preventDefault();var t=document.getElementById('t').value.trim();if(t)location.href='/?token='+encodeURIComponent(t);}
</script>
</body>
</html>"""


def _landing_response(error: str = ""):
    err_html = f'<div class="err">{error}</div>' if error else ""
    return HTMLResponse(_LANDING_HTML.replace("__ERROR__", err_html))


# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="voice-input Relay Server (multi-agent router)")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=8787, help="监听端口，默认 8787")
    parser.add_argument(
        "--allowlist-file",
        default="",
        help=(
            "Token allowlist 文件路径，每行一个 token，# 开头视为注释；"
            "未提供时回退环境变量 VOICE_INPUT_RELAY_ALLOWLIST / VOICE_INPUT_RELAY_ALLOWLIST_FILE，"
            "全部为空则进入开放路由模式（任何 token 均可注册）"
        ),
    )
    parser.add_argument("--default-device", default="default", help="默认设备 ID")
    parser.add_argument("--timeout", type=float, default=30.0, help="转发请求超时时间（秒）")
    parser.add_argument(
        "--log-level", default="info", choices=["debug", "info", "warning", "error"], help="日志级别"
    )
    return parser


# ---------------------------------------------------------------------------
# FastAPI 应用
# ---------------------------------------------------------------------------


def create_app(state: RelayState):
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
        token_hash = ""
        try:
            raw = await ws.receive_text()
            try:
                hello = json.loads(raw)
            except Exception:
                await ws.close(code=1003)
                return
            if hello.get("type") != TYPE_HELLO:
                await ws.close(code=1008)
                return

            token = str(hello.get("token") or "")
            if not token:
                LOG.warning("Agent 注册失败: 缺少 token")
                await ws.close(code=1008)
                return
            if not _check_allowlist(token, state):
                LOG.warning("Agent 注册失败: token 不在 allowlist")
                await ws.close(code=1008)
                return

            token_hash = _hash_token(token)
            device_id = str(hello.get("device_id") or state.default_device)

            # 同 token 重复注册：踢掉旧的，新连接接管
            old = state.agents.get(token_hash)
            if old is not None and old.ws is not ws:
                LOG.info("Agent 重复注册，替换旧连接: token=%s***", token_hash[:8])
                for fut in list(old.pending.values()):
                    if not fut.done():
                        fut.set_exception(RuntimeError("agent replaced"))
                old.pending.clear()
                try:
                    await old.ws.close(code=1012, reason="replaced by new connection")
                except Exception:
                    pass

            session = AgentSession(ws=ws, device_id=device_id, token_hash=token_hash)
            state.agents[token_hash] = session

            await ws.send_text(json.dumps(hello_ok_message(device_id)))
            LOG.info(
                "Agent 已连接: device=%s token=%s*** total=%d",
                device_id,
                token_hash[:8],
                len(state.agents),
            )

            while True:
                msg = json.loads(await ws.receive_text())
                if msg.get("type") == TYPE_RESPONSE:
                    req_id = str(msg.get("id") or "")
                    fut = session.pending.pop(req_id, None)
                    if fut and not fut.done():
                        fut.set_result(msg)
        except WebSocketDisconnect:
            LOG.info("Agent 已断开: token=%s***", token_hash[:8] if token_hash else "?")
        except Exception as exc:
            LOG.warning("Agent 连接错误: %s", exc)
        finally:
            cur = state.agents.get(token_hash) if token_hash else None
            if cur is not None and cur.ws is ws:
                state.agents.pop(token_hash, None)
                for fut in list(cur.pending.values()):
                    if not fut.done():
                        fut.set_exception(RuntimeError("agent disconnected"))
                cur.pending.clear()

    @app.api_route(
        "/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
    )
    async def proxy(path: str, req: Request):
        # 健康检查：暴露在线 agent 数量
        if path == "relay/health":
            return _json_response({"code": 200, "agents_online": len(state.agents)})

        token = _extract_token(req)

        # 未带 token 访问根路径 → 落地页（仅对 GET 生效）
        if not token and path == "" and req.method == "GET":
            return _landing_response()

        # allowlist 模式下校验 token 合法性
        if not _check_allowlist(token, state):
            if path == "" and req.method == "GET":
                return _landing_response("Token 无效或未在准入名单")
            return _error_response(ERR_UNAUTHORIZED, "unauthorized", 401)

        # token 合法但没匹配到对应 agent
        session = _route_session(token, state)
        if session is None:
            if path == "" and req.method == "GET":
                return _landing_response("对应电脑未连接 Relay，请检查本地 voice-input 是否在运行")
            return _error_response(ERR_AGENT_OFFLINE, "relay agent offline", 503)

        # 转发请求
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
        session.pending[req_id] = fut
        try:
            async with session.send_lock:
                await session.ws.send_text(json.dumps(msg))
            resp = await asyncio.wait_for(fut, timeout=state.request_timeout)
        except asyncio.TimeoutError:
            session.pending.pop(req_id, None)
            out = _error_response(ERR_REQUEST_TIMEOUT, "request timeout", 504)
            return _set_token_cookie(out, token) if _should_set_cookie(req) else out
        except Exception as exc:
            session.pending.pop(req_id, None)
            LOG.warning("转发失败: %s", exc)
            out = _error_response(ERR_INTERNAL, str(exc), 502)
            return _set_token_cookie(out, token) if _should_set_cookie(req) else out

        status = int(resp.get("status") or 502)
        body = resp.get("body")
        resp_headers = resp.get("headers") or {}
        content_type = resp_headers.get("content-type", "")
        if isinstance(body, (dict, list)):
            out = _json_response(body, status)
        else:
            out = Response(content=str(body or ""), status_code=status, media_type=content_type or None)
        return _set_token_cookie(out, token) if _should_set_cookie(req) else out

    return app


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    require_optional_dependency("fastapi", "relay-server")
    require_optional_dependency("uvicorn", "relay-server")
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    allowlist_hashes = _load_allowlist(args.allowlist_file)
    if allowlist_hashes:
        LOG.info("Allowlist 模式：已加载 %d 个准入 token", len(allowlist_hashes))
    else:
        LOG.info("开放路由模式：任何 token 均可注册（生产环境建议配置 allowlist）")

    state = RelayState(
        allowlist_hashes=allowlist_hashes,
        default_device=args.default_device,
        request_timeout=args.timeout,
    )
    app = create_app(state)

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    main()
