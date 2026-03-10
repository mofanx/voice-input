"""Flask 应用与路由定义"""

import io
import csv
import json
import os
import platform
import time
import logging
import threading
from collections import deque

from flask import Flask, request, jsonify, render_template, Response

from .config import AppConfig
from .utils import get_local_ip, get_client_ip, is_ip_allowed, is_token_valid


_PASTE_DELAY = 0.08  # 剪贴板写入后等待时间（秒），确保 X11 剪贴板同步完成
_RESTORE_DELAY = 0.15  # 粘贴操作后等待时间（秒），确保目标程序完成读取剪贴板


def _do_keyboard_action(action: str, text: str, press_enter: bool = False):
    """执行键盘操作（跨平台），在 copy 之后调用"""
    try:
        import keyboard
    except ImportError:
        logging.warning("keyboard 模块未安装，跳过自动粘贴（文本已复制到剪贴板）")
        return
    except Exception as e:
        logging.warning(f"keyboard 模块加载失败: {e}")
        return

    try:
        time.sleep(_PASTE_DELAY)
        is_windows = platform.system() == "Windows"
        if action == "paste":
            keyboard.press_and_release("ctrl+v")
            logging.info("已执行粘贴操作")
        elif action == "paste_terminal":
            if is_windows:
                keyboard.press_and_release("ctrl+v")
            else:
                keyboard.press_and_release("ctrl+shift+v")
            logging.info("已执行终端粘贴操作")
        elif action == "type":
            keyboard.write(text)
            logging.info("已执行键入操作")
            
        if press_enter and action in ("paste", "paste_terminal", "type"):
            time.sleep(_PASTE_DELAY)  # 等待粘贴操作完成
            keyboard.press_and_release("enter")
            logging.info("已执行回车操作")
    except Exception as e:
        logging.warning(f"自动粘贴失败（文本已复制到剪贴板）: {e}")


def _save_clipboard() -> bytes | None:
    """保存当前剪贴板内容，失败返回 None"""
    try:
        import pyclip
        return pyclip.paste()
    except Exception:
        return None


def _restore_clipboard(old_content: bytes | None):
    """恢复剪贴板内容"""
    if old_content is None:
        return
    try:
        import pyclip
        time.sleep(_RESTORE_DELAY)
        pyclip.copy(old_content)
        logging.info("已恢复原有剪贴板内容")
    except Exception as e:
        logging.warning(f"恢复剪贴板失败: {e}")


def create_app(config: AppConfig) -> Flask:
    """应用工厂：根据配置创建 Flask 实例"""

    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    app = Flask(__name__, template_folder=template_dir)
    app.config["MAX_CONTENT_LENGTH"] = config.max_content_length

    # 存储配置到 app 上下文
    app.voice_config = config
    app.voice_history = deque(maxlen=config.history_size)
    app.voice_history_lock = threading.Lock()
    app.voice_history_counter = 0

    # 预热 keyboard / pyclip，强制完成底层设备初始化
    # keyboard 在 Linux 上首次按键时才创建 /dev/uinput 虚拟设备，
    # 内核注册该设备需要数百毫秒，期间发送的按键事件会丢失。
    # 因此在启动时做一次空按键，等待设备就绪后再提供服务。
    try:
        import pyclip
        pyclip.paste()  # 预热剪贴板后端
        logging.info("pyclip 模块已预热")
    except Exception:
        pass
    try:
        import keyboard
        if platform.system() != "Windows":
            keyboard.press_and_release("shift")
            time.sleep(0.5)  # 等待内核注册 uinput 虚拟设备
        logging.info("keyboard 模块已预热（uinput 设备已就绪）")
    except Exception:
        pass

    # ==================== 认证辅助 ====================

    def _check_auth():
        """对敏感路由执行 IP 白名单 + Token 校验，返回错误响应或 None"""
        cfg = app.voice_config
        client_ip = get_client_ip(request)
        if not is_ip_allowed(client_ip, cfg.allowed_ips):
            logging.warning(f"IP未授权访问: {client_ip}")
            return (
                jsonify({"code": 403, "message": "IP not allowed",
                         "error_detail": "Your IP address is not in the whitelist"}),
                403,
            )
        # 对于非 POST 请求（GET/DELETE），data 为 None，token 仅从 header/query 取
        data = None
        if request.is_json:
            try:
                data = request.get_json(silent=True)
            except Exception:
                pass
        if not is_token_valid(request, data, cfg.token, cfg.require_token):
            logging.warning(f"Token校验失败: {client_ip}")
            return (
                jsonify({"code": 401, "message": "Unauthorized",
                         "error_detail": "Invalid or missing token"}),
                401,
            )
        return None

    # ==================== 路由 ====================

    @app.route("/", methods=["GET"])
    def index():
        local_ip = get_local_ip()
        cfg = app.voice_config
        return render_template(
            "index.html",
            server_ip=local_ip,
            port=cfg.port,
            require_token=bool(cfg.token) or cfg.require_token,
            auto_paste=cfg.auto_paste,
            platform_name=platform.system(),
        )

    @app.route("/status", methods=["GET"])
    def status():
        local_ip = get_local_ip()
        cfg = app.voice_config
        return jsonify(
            {
                "code": 200,
                "message": "service running",
                "version": "1.0.3",
                "server_ip": local_ip,
                "port": cfg.port,
                "platform": platform.system(),
                "require_token": bool(cfg.token) or cfg.require_token,
                "auto_paste": cfg.auto_paste,
                "history_size": cfg.history_size,
                "timestamp": int(time.time() * 1000),
            }
        )

    @app.route("/history", methods=["GET"])
    def get_history():
        auth_err = _check_auth()
        if auth_err:
            return auth_err
        with app.voice_history_lock:
            items = list(app.voice_history)
        return jsonify(
            {
                "code": 200,
                "message": "success",
                "items": items,
                "timestamp": int(time.time() * 1000),
            }
        )

    @app.route("/history/<int:item_id>", methods=["DELETE"])
    def delete_history_item(item_id):
        auth_err = _check_auth()
        if auth_err:
            return auth_err
        with app.voice_history_lock:
            before = len(app.voice_history)
            app.voice_history = deque(
                (item for item in app.voice_history if item.get("id") != item_id),
                maxlen=config.history_size,
            )
            removed = before - len(app.voice_history)
        return jsonify({"code": 200, "message": "success", "removed": removed})

    @app.route("/history", methods=["DELETE"])
    def clear_history():
        auth_err = _check_auth()
        if auth_err:
            return auth_err
        with app.voice_history_lock:
            count = len(app.voice_history)
            app.voice_history.clear()
        return jsonify({"code": 200, "message": "success", "cleared": count})

    @app.route("/history/export", methods=["GET"])
    def export_history():
        auth_err = _check_auth()
        if auth_err:
            return auth_err
        fmt = request.args.get("format", "json")
        with app.voice_history_lock:
            items = list(app.voice_history)

        if fmt == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["id", "time", "text", "action", "device_id", "client_ip"])
            for item in items:
                t = time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(item["server_time"] / 1000)
                )
                writer.writerow(
                    [
                        item.get("id", ""),
                        t,
                        item.get("text", ""),
                        item.get("action", ""),
                        item.get("device_id", ""),
                        item.get("client_ip", ""),
                    ]
                )
            return Response(
                output.getvalue(),
                mimetype="text/csv",
                headers={"Content-Disposition": "attachment; filename=voice_history.csv"},
            )
        else:
            return Response(
                json.dumps(items, ensure_ascii=False, indent=2),
                mimetype="application/json",
                headers={
                    "Content-Disposition": "attachment; filename=voice_history.json"
                },
            )

    @app.route("/input", methods=["POST"])
    def handle_input():
        cfg = app.voice_config

        # 1. IP + Token 认证
        auth_err = _check_auth()
        if auth_err:
            return auth_err
        client_ip = get_client_ip(request)

        # 2. JSON 解析
        try:
            data = request.get_json(force=True)
        except Exception as e:
            logging.error(f"JSON解析失败: {e}")
            return (
                jsonify(
                    {
                        "code": 400,
                        "message": "Invalid JSON format",
                        "error_detail": "Request body must be valid JSON",
                    }
                ),
                400,
            )

        # 3. 必需字段
        if not data or "text" not in data:
            logging.error("缺少必需字段 'text'")
            return (
                jsonify(
                    {
                        "code": 400,
                        "message": "Missing required field: text",
                        "error_detail": 'The "text" field is required',
                    }
                ),
                400,
            )

        # 5. 解析字段
        text = str(data["text"])
        timestamp = data.get("timestamp", int(time.time() * 1000))
        device_id = data.get("device_id", "unknown")
        action = data.get("action", "paste" if cfg.auto_paste else "copy")
        restore_clipboard = bool(data.get("restore_clipboard", False))
        press_enter = bool(data.get("press_enter", False))

        # 6. 时间戳偏差警告
        current_time = int(time.time() * 1000)
        if abs(current_time - timestamp) > 30000:
            logging.warning(f"时间戳偏差过大: {current_time - timestamp}ms")

        # 7. 执行剪贴板和键盘操作
        try:
            import pyclip

            # 仅在需要恢复且不是"仅复制"模式时保存原剪贴板
            need_restore = restore_clipboard and action != "copy"
            old_clipboard = _save_clipboard() if need_restore else None

            pyclip.copy(text)

            with app.voice_history_lock:
                app.voice_history_counter += 1
                app.voice_history.appendleft(
                    {
                        "id": app.voice_history_counter,
                        "server_time": current_time,
                        "client_ip": client_ip,
                        "device_id": device_id,
                        "action": action,
                        "text": text,
                    }
                )

            logging.info(
                f"已复制到剪贴板 (长度: {len(text)}, 设备: {device_id}, "
                f"IP: {client_ip}, action: {action})"
            )

            if action in ("paste", "paste_terminal", "type"):
                _do_keyboard_action(action, text, press_enter)

            # 恢复原有剪贴板内容
            if need_restore:
                _restore_clipboard(old_clipboard)

            return jsonify(
                {
                    "code": 200,
                    "message": "success",
                    "server_time": current_time,
                    "processed_text_length": len(text),
                    "action": action,
                    "device_id": device_id,
                    "clipboard_restored": need_restore,
                }
            )

        except Exception as e:
            logging.error(f"服务器内部错误: {e}")
            return (
                jsonify(
                    {
                        "code": 500,
                        "message": "Internal server error",
                        "error_detail": str(e),
                    }
                ),
                500,
            )

    # ==================== CORS ====================

    @app.before_request
    def handle_options_preflight():
        if request.method == "OPTIONS":
            resp = app.make_response("")
            resp.status_code = 204
            return resp

    @app.after_request
    def add_cors_headers(resp):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Auth-Token"
        resp.headers["Access-Control-Max-Age"] = "86400"
        return resp

    # ==================== PWA 静态资源 ====================

    _ICON_SVG = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 192 192'>
  <rect width='192' height='192' rx='38' fill='#007aff'/>
  <rect x='78' y='38' width='36' height='70' rx='18' fill='white'/>
  <path d='M54 94c0 23.2 18.8 42 42 42s42-18.8 42-42'
        stroke='white' stroke-width='9' fill='none' stroke-linecap='round'/>
  <line x1='96' y1='136' x2='96' y2='155'
        stroke='white' stroke-width='9' stroke-linecap='round'/>
  <line x1='76' y1='155' x2='116' y2='155'
        stroke='white' stroke-width='9' stroke-linecap='round'/>
</svg>"""

    _MANIFEST = json.dumps({
        "name": "语音输入",
        "short_name": "语音输入",
        "description": "跨设备语音输入传输系统",
        "start_url": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#f5f5f7",
        "theme_color": "#007aff",
        "lang": "zh-CN",
        "icons": [
            {"src": "/icon.svg", "sizes": "any",
             "type": "image/svg+xml", "purpose": "any maskable"}
        ]
    }, ensure_ascii=False, indent=2)

    _SW_JS = r"""
const CACHE = 'vi-v1';
const SHELL = ['/', '/manifest.json', '/icon.svg'];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE)
      .then(c => c.addAll(SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => k !== CACHE).map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  // Don't intercept cross-origin requests (user-configured server)
  if (url.origin !== location.origin) return;
  // API paths: always network, never cache
  if (['/input','/history','/status'].some(p =>
        url.pathname === p || url.pathname.startsWith(p + '/'))) return;
  // App shell: stale-while-revalidate
  e.respondWith(
    caches.open(CACHE).then(cache =>
      cache.match(e.request).then(cached => {
        const fresh = fetch(e.request).then(resp => {
          if (resp.ok) cache.put(e.request, resp.clone());
          return resp;
        }).catch(() => cached);
        return cached || fresh;
      })
    )
  );
});
"""

    @app.route("/manifest.json", methods=["GET"])
    def pwa_manifest():
        return Response(_MANIFEST, mimetype="application/manifest+json")

    @app.route("/sw.js", methods=["GET"])
    def pwa_sw():
        return Response(_SW_JS, mimetype="application/javascript",
                        headers={"Service-Worker-Allowed": "/"})

    @app.route("/icon.svg", methods=["GET"])
    def pwa_icon():
        return Response(_ICON_SVG, mimetype="image/svg+xml",
                        headers={"Cache-Control": "public, max-age=86400"})

    # ==================== 错误处理器 ====================

    @app.errorhandler(413)
    def request_entity_too_large(error):
        return (
            jsonify(
                {
                    "code": 413,
                    "message": "Payload too large",
                    "error_detail": f"Exceeds {config.max_content_length} bytes",
                }
            ),
            413,
        )

    return app
