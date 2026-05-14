"""公网 Relay 中转服务。"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any

from . import __version__
from .relay_protocol import (
    DEFAULT_RELAY_PORT,
    DEFAULT_RELAY_TIMEOUT,
    get_relay_token,
    new_request_id,
    now_ms,
    token_matches,
)


try:
    from aiohttp import WSMsgType, web
except ImportError:
    WSMsgType = None
    web = None


INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>voice-input relay</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;background:#f5f5f7;color:#1d1d1f}.wrap{max-width:680px;margin:0 auto;padding:20px}.card{background:#fff;border:1px solid #e5e5ea;border-radius:18px;padding:18px;margin:14px 0;box-shadow:0 8px 30px rgba(0,0,0,.06)}h1{font-size:24px;margin:8px 0 4px}label{font-size:13px;color:#666;display:block;margin:12px 0 6px}input,select,textarea,button{box-sizing:border-box;width:100%;font-size:16px;border-radius:12px;border:1px solid #d1d1d6;padding:12px}textarea{min-height:180px;resize:vertical}button{background:#007aff;color:#fff;border:0;font-weight:700;margin-top:14px}.row{display:grid;grid-template-columns:1fr 1fr;gap:10px}.hint{font-size:12px;color:#777;line-height:1.5}.toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:#222;color:#fff;padding:10px 14px;border-radius:999px;display:none}.toast.show{display:block}
</style>
</head>
<body><div class="wrap"><h1>voice-input Relay</h1><div class="hint">公网中转页面，只负责把文本转发到已连接的桌面客户端。</div><div class="card"><label>Relay Token</label><input id="token" type="password" autocomplete="off"><label>目标设备 ID（单设备可留空）</label><input id="target" autocomplete="off" placeholder="huawei-cloud-desktop"><div class="row"><div><label>动作</label><select id="action"><option value="paste_terminal">paste_terminal</option><option value="paste">paste</option><option value="paste_enter">paste_enter</option><option value="copy">copy</option></select></div><div><label>恢复剪贴板</label><select id="restore"><option value="true">是</option><option value="false">否</option></select></div></div><label>文本</label><textarea id="text" placeholder="在手机上使用语音输入法输入..."></textarea><button id="send">发送到电脑</button></div><div class="card"><button id="refresh">刷新在线设备</button><pre id="devices" class="hint"></pre></div></div><div class="toast" id="toast"></div><script>
const $=id=>document.getElementById(id);const LS=k=>localStorage.getItem('vi_relay_'+k)||'';const SET=(k,v)=>localStorage.setItem('vi_relay_'+k,v);['token','target','action','restore'].forEach(id=>{$(id).value=LS(id)||$(id).value;$(id).addEventListener('input',()=>SET(id,$(id).value));});function toast(m){const t=$('toast');t.textContent=m;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),2200)}async function devices(){const r=await fetch('/relay/devices',{headers:{'X-Relay-Token':$('token').value}});$('devices').textContent=JSON.stringify(await r.json(),null,2)}$('refresh').onclick=()=>devices().catch(e=>toast(e.message));$('send').onclick=async()=>{const b=$('send');b.disabled=true;b.textContent='发送中...';try{const payload={text:$('text').value,target_device_id:$('target').value,action:$('action').value,restore_clipboard:$('restore').value==='true',device_id:'phone_relay_web',timestamp:Date.now()};const r=await fetch('/relay/input',{method:'POST',headers:{'Content-Type':'application/json','X-Relay-Token':$('token').value},body:JSON.stringify(payload)});const j=await r.json().catch(()=>null);if(r.ok){toast('发送成功');$('text').value=''}else toast('失败: '+(j&&j.message?j.message:r.status))}catch(e){toast('网络错误: '+e.message)}finally{b.disabled=false;b.textContent='发送到电脑'}};devices().catch(()=>{});
</script></body></html>"""


@dataclass
class RelayState:
    token: str
    timeout: float = DEFAULT_RELAY_TIMEOUT
    devices: dict[str, web.WebSocketResponse] = field(default_factory=dict)
    pending: dict[str, asyncio.Future] = field(default_factory=dict)


async def _json_response(payload: dict, status: int = 200):
    return web.json_response(payload, status=status, headers={"Access-Control-Allow-Origin": "*"})


def _require_auth(request, state: RelayState) -> bool:
    return token_matches(get_relay_token(request.headers), state.token)


async def index(request):
    return web.Response(text=INDEX_HTML, content_type="text/html")


async def options_handler(request):
    return web.Response(headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type, X-Relay-Token, X-Auth-Token, Authorization",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    })


async def devices_handler(request):
    state: RelayState = request.app["state"]
    if not _require_auth(request, state):
        return await _json_response({"code": 401, "message": "Unauthorized"}, 401)
    return await _json_response({"code": 200, "devices": sorted(state.devices.keys())})


async def input_handler(request):
    state: RelayState = request.app["state"]
    if not _require_auth(request, state):
        return await _json_response({"code": 401, "message": "Unauthorized"}, 401)
    try:
        data = await request.json()
    except Exception:
        return await _json_response({"code": 400, "message": "Invalid JSON format"}, 400)
    if not isinstance(data, dict) or not data.get("text"):
        return await _json_response({"code": 400, "message": "Missing required field: text"}, 400)

    target = str(data.get("target_device_id") or data.get("device_id_target") or "").strip()
    online = list(state.devices.keys())
    if target:
        ws = state.devices.get(target)
        if ws is None:
            return await _json_response({"code": 404, "message": "Target device offline", "target_device_id": target}, 404)
    else:
        if len(online) != 1:
            return await _json_response({"code": 400, "message": "target_device_id required", "devices": sorted(online)}, 400)
        target = online[0]
        ws = state.devices[target]

    request_id = str(data.get("request_id") or new_request_id())
    payload = dict(data)
    payload.pop("target_device_id", None)
    payload.setdefault("timestamp", now_ms())
    future = asyncio.get_running_loop().create_future()
    state.pending[request_id] = future
    try:
        await ws.send_json({"type": "input", "request_id": request_id, "payload": payload})
        result = await asyncio.wait_for(future, timeout=state.timeout)
        status = int(result.get("status") or result.get("code") or 200)
        if status < 100 or status > 599:
            status = 200
        return await _json_response(result.get("payload") or result, status)
    except asyncio.TimeoutError:
        return await _json_response({"code": 504, "message": "Desktop client timeout", "request_id": request_id}, 504)
    finally:
        state.pending.pop(request_id, None)


async def ws_handler(request):
    state: RelayState = request.app["state"]
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    device_id = ""
    try:
        msg = await ws.receive(timeout=10)
        if msg.type != WSMsgType.TEXT:
            await ws.close(message=b"register required")
            return ws
        try:
            data = json.loads(msg.data)
        except Exception:
            await ws.close(message=b"invalid json")
            return ws
        if data.get("type") != "register" or data.get("role") != "desktop":
            await ws.close(message=b"invalid register")
            return ws
        if not token_matches(str(data.get("token") or ""), state.token):
            await ws.close(message=b"unauthorized")
            return ws
        device_id = str(data.get("device_id") or "").strip()
        if not device_id:
            await ws.close(message=b"device_id required")
            return ws
        old = state.devices.get(device_id)
        if old is not None and not old.closed:
            await old.close(message=b"replaced")
        state.devices[device_id] = ws
        logging.info("Relay desktop connected: %s", device_id)
        await ws.send_json({"type": "registered", "device_id": device_id, "server_time": now_ms(), "version": __version__})
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except Exception:
                    continue
                if data.get("type") == "result":
                    request_id = str(data.get("request_id") or "")
                    future = state.pending.get(request_id)
                    if future and not future.done():
                        future.set_result(data)
            elif msg.type == WSMsgType.ERROR:
                logging.warning("Relay websocket error: %s", ws.exception())
    finally:
        if device_id and state.devices.get(device_id) is ws:
            state.devices.pop(device_id, None)
            logging.info("Relay desktop disconnected: %s", device_id)
    return ws


def create_relay_app(token: str, timeout: float = DEFAULT_RELAY_TIMEOUT):
    if web is None:
        raise RuntimeError("Relay 服务需要 aiohttp，请执行: pip install 'voice-input[relay]' 或 pip install aiohttp")
    app = web.Application(client_max_size=1024 * 1024)
    app["state"] = RelayState(token=token, timeout=timeout)
    app.router.add_get("/", index)
    app.router.add_get("/relay/devices", devices_handler)
    app.router.add_options("/relay/devices", options_handler)
    app.router.add_post("/relay/input", input_handler)
    app.router.add_options("/relay/input", options_handler)
    app.router.add_get("/relay/ws", ws_handler)
    return app


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="voice-input-relay", description="voice-input 公网 WebSocket Relay 中转服务")
    p.add_argument("--host", default=os.environ.get("VOICE_INPUT_RELAY_HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(os.environ.get("VOICE_INPUT_RELAY_PORT", DEFAULT_RELAY_PORT)))
    p.add_argument("--token", default=os.environ.get("VOICE_INPUT_RELAY_TOKEN", ""))
    p.add_argument("--timeout", type=float, default=float(os.environ.get("VOICE_INPUT_RELAY_TIMEOUT", DEFAULT_RELAY_TIMEOUT)))
    p.add_argument("--log-level", choices=["debug", "info", "warning", "error"], default=os.environ.get("VOICE_INPUT_RELAY_LOG_LEVEL", "info"))
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(asctime)s - %(levelname)s - %(message)s")
    if not args.token:
        print("必须设置 Relay Token：--token 或 VOICE_INPUT_RELAY_TOKEN", file=sys.stderr)
        return 2
    app = create_relay_app(args.token, timeout=args.timeout)
    print(f"voice-input relay v{__version__} listening on http://{args.host}:{args.port}")
    web.run_app(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
