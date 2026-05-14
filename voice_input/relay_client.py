"""桌面端 Relay 反连客户端。"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import platform
import socket
import ssl
import sys
from typing import Any

from . import __version__
from .config import build_config, find_config_file, init_user_config
from .relay_protocol import DEFAULT_RECONNECT_INTERVAL, normalize_ws_url, now_ms
from .server import create_app


try:
    from aiohttp import ClientSession, WSMsgType
except ImportError:
    ClientSession = None
    WSMsgType = None


def default_device_id() -> str:
    host = socket.gethostname() or platform.node() or "desktop"
    return host.replace(" ", "-")


class RelayClient:
    def __init__(self, app, server_url: str, token: str, device_id: str, reconnect_interval: float = DEFAULT_RECONNECT_INTERVAL, verify_tls: bool = True):
        self.app = app
        self.server_url = normalize_ws_url(server_url)
        self.token = token
        self.device_id = device_id
        self.reconnect_interval = reconnect_interval
        self.verify_tls = verify_tls

    async def run_forever(self):
        if ClientSession is None:
            raise RuntimeError("Relay 客户端需要 aiohttp，请执行: pip install 'voice-input[relay]' 或 pip install aiohttp")
        if not self.server_url or not self.token:
            raise RuntimeError("Relay server_url 和 token 不能为空")
        ssl_ctx: Any = None
        if self.server_url.startswith("wss://") and not self.verify_tls:
            ssl_ctx = ssl._create_unverified_context()
        while True:
            try:
                await self._connect_once(ssl_ctx)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logging.warning("Relay 连接失败: %s", e)
            await asyncio.sleep(self.reconnect_interval)

    async def _connect_once(self, ssl_ctx):
        logging.info("连接 Relay: %s", self.server_url)
        async with ClientSession() as session:
            async with session.ws_connect(self.server_url, ssl=ssl_ctx, heartbeat=30) as ws:
                await ws.send_json({
                    "type": "register",
                    "role": "desktop",
                    "device_id": self.device_id,
                    "token": self.token,
                    "client_version": __version__,
                })
                async for msg in ws:
                    if msg.type == WSMsgType.TEXT:
                        await self._handle_message(ws, msg.data)
                    elif msg.type == WSMsgType.ERROR:
                        raise RuntimeError(ws.exception())

    async def _handle_message(self, ws, raw: str):
        try:
            data = json.loads(raw)
        except Exception:
            return
        msg_type = data.get("type")
        if msg_type == "registered":
            logging.info("Relay 注册成功: %s", data.get("device_id"))
            return
        if msg_type != "input":
            return
        request_id = str(data.get("request_id") or "")
        payload = data.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("device_id", "relay")
        payload.setdefault("timestamp", now_ms())
        result_payload, status = self.app.process_input_payload(payload, client_ip="relay")
        await ws.send_json({
            "type": "result",
            "request_id": request_id,
            "ok": 200 <= int(status) < 300,
            "status": status,
            "payload": result_payload,
        })


def _load_config(args):
    cli_dict = {}
    if args.no_auto_paste:
        cli_dict["auto_paste"] = False
    if args.log_level is not None:
        cli_dict["log_level"] = args.log_level
    config_path = find_config_file(args.config)
    config_dir = None
    if config_path is None:
        config_dir = init_user_config()
        config_path = str(config_dir / "config.yaml")
    else:
        from pathlib import Path
        from .config import get_user_config_dir
        path = Path(config_path)
        if path.parent == get_user_config_dir():
            config_dir = path.parent
    return build_config(cli_args=cli_dict, config_file=config_path, config_dir=config_dir)


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="voice-input-relay-client", description="voice-input 桌面端 Relay 反连客户端")
    p.add_argument("-c", "--config", metavar="FILE", help="YAML 配置文件路径")
    p.add_argument("--server", default=os.environ.get("VOICE_INPUT_RELAY_SERVER", ""), help="Relay 服务地址，例如 https://voice.example.com")
    p.add_argument("--token", default=os.environ.get("VOICE_INPUT_RELAY_TOKEN", ""), help="Relay Token")
    p.add_argument("--device-id", default=os.environ.get("VOICE_INPUT_RELAY_DEVICE_ID", ""), help="桌面设备 ID")
    p.add_argument("--reconnect-interval", type=float, default=float(os.environ.get("VOICE_INPUT_RELAY_RECONNECT_INTERVAL", DEFAULT_RECONNECT_INTERVAL)))
    p.add_argument("--no-verify-tls", action="store_true", default=False, help="不校验 HTTPS/WSS 证书")
    p.add_argument("--no-auto-paste", action="store_true", default=False, help="默认不自动粘贴，仅复制到剪贴板")
    p.add_argument("--log-level", choices=["debug", "info", "warning", "error"], default=os.environ.get("VOICE_INPUT_LOG_LEVEL", "info"))
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(asctime)s - %(levelname)s - %(message)s")
    cfg = _load_config(args)
    server_url = args.server or cfg.relay_server_url
    token = args.token or cfg.relay_token
    device_id = args.device_id or cfg.relay_device_id or default_device_id()
    reconnect_interval = args.reconnect_interval or cfg.relay_reconnect_interval
    verify_tls = cfg.relay_verify_tls and not args.no_verify_tls
    app = create_app(cfg)
    print(f"voice-input relay client v{__version__}")
    print(f"  Relay:  {server_url}")
    print(f"  Device: {device_id}")
    return asyncio.run(RelayClient(app, server_url, token, device_id, reconnect_interval, verify_tls).run_forever())


if __name__ == "__main__":
    raise SystemExit(main())
