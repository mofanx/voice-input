"""Flask 应用与路由定义"""

import io
import csv
import json
import math
import os
import platform
import struct
import subprocess
import time
import logging
import threading
import zlib
from collections import deque

from flask import Flask, request, jsonify, render_template, Response

from .commands import (
    CommandEngine, command_result_to_dict, strip_command_prefix,
    exec_shell_command, shell_result_to_dict, strip_shell_prefix,
)
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


def _make_icon_png(size: int) -> bytes:
    """生成麦克风图标 PNG（纯 Python，无外部依赖）"""
    BG = (0, 122, 255, 255)
    FG = (255, 255, 255, 255)
    TR = (0, 0, 0, 0)
    cr = size * 0.198
    cx = size / 2.0
    mic_hw = size * 0.094
    mic_top = size * 0.198
    mic_bot = size * 0.565
    mic_r = mic_hw
    arc_r = size * 0.219
    arc_cy = size * 0.490
    arc_w = size * 0.047
    pole_top = size * 0.708
    pole_bot = size * 0.807
    pole_hw = size * 0.024
    base_cy = size * 0.807
    base_hw = size * 0.104
    base_hh = size * 0.024

    rows = bytearray()
    for y in range(size):
        rows.append(0)
        for x in range(size):
            in_bg = True
            if x < cr and y < cr:
                if (x - cr) ** 2 + (y - cr) ** 2 > cr * cr:
                    in_bg = False
            elif x >= size - cr and y < cr:
                if (x - size + 1 + cr) ** 2 + (y - cr) ** 2 > cr * cr:
                    in_bg = False
            elif x < cr and y >= size - cr:
                if (x - cr) ** 2 + (y - size + 1 + cr) ** 2 > cr * cr:
                    in_bg = False
            elif x >= size - cr and y >= size - cr:
                if (x - size + 1 + cr) ** 2 + (y - size + 1 + cr) ** 2 > cr * cr:
                    in_bg = False
            if not in_bg:
                rows.extend(TR)
                continue
            fg = False
            dx = x - cx
            if abs(dx) <= mic_hw:
                if mic_top + mic_r <= y <= mic_bot - mic_r:
                    fg = True
                elif y < mic_top + mic_r:
                    if dx * dx + (y - mic_top - mic_r) ** 2 <= mic_r * mic_r:
                        fg = True
                elif y > mic_bot - mic_r:
                    if dx * dx + (y - mic_bot + mic_r) ** 2 <= mic_r * mic_r:
                        fg = True
            if not fg and y >= arc_cy:
                dist = math.sqrt(dx * dx + (y - arc_cy) ** 2)
                if abs(dist - arc_r) <= arc_w:
                    fg = True
            if not fg and pole_top <= y <= pole_bot and abs(dx) <= pole_hw:
                fg = True
            if not fg and abs(y - base_cy) <= base_hh and abs(dx) <= base_hw:
                fg = True
            rows.extend(FG if fg else BG)

    def _chunk(ctype, data):
        c = ctype + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(rows), 9)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", idat)
        + _chunk(b"IEND", b"")
    )


# ---- 按键别名 & scan code 映射 ----
# keyboard 库在 Linux 上对 "windows" 键名解析不稳定，
# 因此对特殊键直接使用 scan code 来 press/release。
# Linux scan codes: Super_L=125, Super_R=126
_KEY_ALIAS = {
    "ctl": "ctrl",
    "control": "ctrl",
    "cmd": "win",
    "command": "win",
    "windows": "win",
    "winkey": "win",
    "super": "win",
    "meta": "win",
    "option": "alt",
    "opt": "alt",
    "esc": "escape",
    "del": "delete",
    "return": "enter",
}

# 需要用 scan code 发送的特殊键（名称 -> Linux scan code）
_SCANCODE_MAP = {
    "win": 125,        # Super_L / Windows 键
}


def _normalize_key(name: str) -> str:
    """单个键名规范化"""
    lower = name.strip().lower()
    return _KEY_ALIAS.get(lower, lower)


def _normalize_key_combo(key: str) -> str:
    """将完整组合键字符串中的每个部分规范化"""
    parts = [_normalize_key(p) for p in str(key or "").split("+") if p.strip()]
    return "+".join(parts)


def _press_key(keyboard_module, name: str, action: str = "press"):
    """按下或释放单个键，优先用 scan code，否则用键名"""
    sc = _SCANCODE_MAP.get(name)
    if sc is not None:
        if action == "press":
            keyboard_module.press(sc)
        elif action == "release":
            keyboard_module.release(sc)
        else:
            keyboard_module.press(sc)
            time.sleep(0.05)
            keyboard_module.release(sc)
    else:
        if action == "press":
            keyboard_module.press(name)
        elif action == "release":
            keyboard_module.release(name)
        else:
            keyboard_module.press_and_release(name)


def _press_combo(keyboard_module, normalized_key: str):
    """发送组合键：手动按下修饰键 → 触发主键 → 逆序释放修饰键"""
    parts = [p for p in normalized_key.split("+") if p]
    if not parts:
        raise ValueError("Empty key combo")

    if len(parts) == 1:
        _press_key(keyboard_module, parts[0], "tap")
        return

    modifiers = parts[:-1]
    main_key = parts[-1]
    pressed = []
    try:
        for mod in modifiers:
            _press_key(keyboard_module, mod, "press")
            pressed.append(mod)
        time.sleep(0.02)
        _press_key(keyboard_module, main_key, "tap")
        time.sleep(0.02)
    finally:
        for mod in reversed(pressed):
            try:
                _press_key(keyboard_module, mod, "release")
            except Exception:
                pass


def _do_key_press(key: str, count: int = 1, interval: float = 0.1):
    """执行键盘按键操作"""
    try:
        import keyboard
    except ImportError:
        logging.warning("keyboard 模块未安装，跳过按键操作")
        return
    normalized_key = _normalize_key_combo(key)
    for i in range(count):
        _press_combo(keyboard, normalized_key)
        logging.info(f"已执行按键: {key} -> {normalized_key} ({i + 1}/{count})")
        if i < count - 1:
            time.sleep(interval)


def _do_mouse_click(button: str = "left", count: int = 1, interval: float = 0.1):
    """执行鼠标点击（跨平台）"""
    for i in range(count):
        if platform.system() == "Windows":
            try:
                import ctypes
                if button == "right":
                    ctypes.windll.user32.mouse_event(8, 0, 0, 0, 0)
                    ctypes.windll.user32.mouse_event(16, 0, 0, 0, 0)
                else:
                    ctypes.windll.user32.mouse_event(2, 0, 0, 0, 0)
                    ctypes.windll.user32.mouse_event(4, 0, 0, 0, 0)
            except Exception as e:
                logging.warning(f"鼠标点击失败: {e}")
                return
        else:
            try:
                click_code = "0xC1" if button == "right" else "0xC0"
                subprocess.run(["sudo", "ydotool", "click", click_code], timeout=2,
                               capture_output=True)
            except FileNotFoundError:
                logging.warning("ydotool 未安装，无法模拟鼠标点击（sudo apt install ydotool）")
                return
            except Exception as e:
                logging.warning(f"鼠标点击失败: {e}")
                return
        logging.info(f"已执行鼠标{button == 'right' and '右键' or '左键'}点击 ({i + 1}/{count})")
        if i < count - 1:
            time.sleep(interval)


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

    app.voice_messages = deque(maxlen=config.history_size)
    app.voice_messages_lock = threading.Lock()
    app.voice_messages_counter = 0
    app.command_engine = CommandEngine.from_config(config, key_executor=lambda key: _do_key_press(key))

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
                "version": "1.2.1",
                "server_ip": local_ip,
                "port": cfg.port,
                "platform": platform.system(),
                "require_token": bool(cfg.token) or cfg.require_token,
                "auto_paste": cfg.auto_paste,
                "history_size": cfg.history_size,
                "command_mode_enabled": cfg.command_mode_enabled,
                "command_prefix": cfg.command_prefix,
                "shell_enabled": cfg.shell_enabled,
                "shell_prefix": cfg.shell_prefix,
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
        data = request.get_json(silent=True) or {}
        ids = data.get("ids", [])
        with app.voice_history_lock:
            if ids:
                id_set = set(ids)
                before = len(app.voice_history)
                app.voice_history = deque(
                    (item for item in app.voice_history if item.get("id") not in id_set),
                    maxlen=config.history_size,
                )
                removed = before - len(app.voice_history)
            else:
                removed = len(app.voice_history)
                app.voice_history.clear()
        return jsonify({"code": 200, "message": "success", "cleared": removed, "removed": removed})

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
        confirmed = bool(data.get("confirmed", False))
        input_mode = str(data.get("input_mode", "auto")).strip().lower()
        if input_mode not in {"text", "command", "auto"}:
            input_mode = "auto"

        # 6. 时间戳偏差警告
        current_time = int(time.time() * 1000)
        if abs(current_time - timestamp) > 30000:
            logging.warning(f"时间戳偏差过大: {current_time - timestamp}ms")

        _run_shell = False
        _run_command = False
        _command_text = text
        _shell_cmd = ""
        raw_text = text.strip()

        if cfg.shell_enabled and raw_text.startswith(cfg.shell_prefix):
            _run_shell = True
            _shell_cmd = strip_shell_prefix(text, cfg.shell_prefix)
        elif cfg.command_mode_enabled and input_mode == "command":
            _run_command = True
            _command_text = strip_command_prefix(text, cfg.command_prefix)
        elif cfg.command_mode_enabled and input_mode == "auto" and raw_text.startswith(cfg.command_prefix):
            _run_command = True
            _command_text = strip_command_prefix(text, cfg.command_prefix)

        if _run_shell:
            if not _shell_cmd.strip():
                return jsonify({"code": 400, "message": "Shell command is empty",
                                "server_time": current_time, "action": "shell", "device_id": device_id}), 400
            shell_res = exec_shell_command(
                _shell_cmd,
                danger_patterns=cfg.shell_danger_patterns,
                confirmed=confirmed,
                need_confirm=cfg.shell_confirm,
            )
            payload = shell_result_to_dict(shell_res)
            payload.update({"server_time": current_time, "action": "shell", "device_id": device_id})
            if shell_res.dangerous:
                payload["code"] = 403
                payload["message"] = "Dangerous command blocked"
                return jsonify(payload), 403
            if shell_res.requires_confirmation:
                payload["code"] = 202
                payload["message"] = "Shell command requires confirmation"
                return jsonify(payload), 202
            if shell_res.error:
                payload["code"] = 500
                payload["message"] = "Shell execution failed"
                return jsonify(payload), 500
            payload["code"] = 200
            payload["message"] = "success"
            with app.voice_history_lock:
                app.voice_history_counter += 1
                app.voice_history.appendleft({
                    "id": app.voice_history_counter,
                    "server_time": current_time,
                    "client_ip": client_ip,
                    "device_id": device_id,
                    "action": "shell",
                    "text": text,
                    "command_id": None,
                })
            return jsonify(payload)

        if _run_command:
            result = app.command_engine.execute(_command_text, confirmed=confirmed)
            payload = command_result_to_dict(result)
            payload.update({
                "code": 200 if not result.error else 500,
                "message": "success" if not result.error else "Command action failed",
                "server_time": current_time,
                "action": "command",
                "device_id": device_id,
            })
            if result.requires_confirmation:
                payload["code"] = 202
                payload["message"] = "Command requires confirmation"
                return jsonify(payload), 202
            if result.error:
                return jsonify(payload), 500
            if not result.matched:
                return jsonify({
                    "code": 404,
                    "message": "Command not matched",
                    "server_time": current_time,
                    "action": "command",
                    "device_id": device_id,
                }), 404
            with app.voice_history_lock:
                app.voice_history_counter += 1
                app.voice_history.appendleft(
                    {
                        "id": app.voice_history_counter,
                        "server_time": current_time,
                        "client_ip": client_ip,
                        "device_id": device_id,
                        "action": "command",
                        "text": text,
                        "command_id": payload.get("command_id"),
                    }
                )
            return jsonify(payload)

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

    # ==================== Shell Direct API ====================

    @app.route("/shell", methods=["POST"])
    def run_shell():
        auth_err = _check_auth()
        if auth_err:
            return auth_err
        if not app.voice_config.shell_enabled:
            return jsonify({"code": 403, "message": "Shell execution is disabled"}), 403
        data = request.get_json(silent=True) or {}
        cmd = str(data.get("cmd", "")).strip()
        if not cmd:
            return jsonify({"code": 400, "message": "cmd is required"}), 400
        confirmed = bool(data.get("confirmed", False))
        shell_res = exec_shell_command(
            cmd,
            danger_patterns=app.voice_config.shell_danger_patterns,
            confirmed=confirmed,
            need_confirm=app.voice_config.shell_confirm,
        )
        payload = shell_result_to_dict(shell_res)
        if shell_res.dangerous:
            payload.update({"code": 403, "message": "Dangerous command blocked"})
            return jsonify(payload), 403
        if shell_res.requires_confirmation:
            payload.update({"code": 202, "message": "Shell command requires confirmation"})
            return jsonify(payload), 202
        if shell_res.error:
            payload.update({"code": 500, "message": "Shell execution failed"})
            return jsonify(payload), 500
        payload.update({"code": 200, "message": "success"})
        return jsonify(payload)

    # ==================== CORS ====================

    @app.route("/commands", methods=["GET"])
    def list_commands():
        auth_err = _check_auth()
        if auth_err:
            return auth_err
        return jsonify({
            "code": 200,
            "message": "success",
            "enabled": app.voice_config.command_mode_enabled,
            "prefix": app.voice_config.command_prefix,
            "items": app.command_engine.list_commands(),
        })

    @app.route("/commands", methods=["POST"])
    def add_command():
        auth_err = _check_auth()
        if auth_err:
            return auth_err
        data = request.get_json(silent=True) or {}
        try:
            item = app.command_engine.add_command(data)
            return jsonify({"code": 201, "message": "created", "item": item}), 201
        except ValueError as e:
            return jsonify({"code": 400, "message": "Invalid command", "error_detail": str(e)}), 400
        except Exception as e:
            logging.error(f"新增命令失败: {e}")
            return jsonify({"code": 500, "message": "Command save failed", "error_detail": str(e)}), 500

    @app.route("/commands/<command_id>", methods=["GET"])
    def get_command(command_id):
        auth_err = _check_auth()
        if auth_err:
            return auth_err
        item = app.command_engine.get_command(command_id)
        if item is None:
            return jsonify({"code": 404, "message": "Command not found"}), 404
        return jsonify({"code": 200, "message": "success", "item": item})

    @app.route("/commands/<command_id>", methods=["PUT"])
    def update_command(command_id):
        auth_err = _check_auth()
        if auth_err:
            return auth_err
        data = request.get_json(silent=True) or {}
        try:
            item = app.command_engine.update_command(command_id, data)
            return jsonify({"code": 200, "message": "success", "item": item})
        except KeyError:
            return jsonify({"code": 404, "message": "Command not found"}), 404
        except ValueError as e:
            return jsonify({"code": 400, "message": "Invalid command", "error_detail": str(e)}), 400
        except Exception as e:
            logging.error(f"更新命令失败: {e}")
            return jsonify({"code": 500, "message": "Command save failed", "error_detail": str(e)}), 500

    @app.route("/commands/<command_id>", methods=["DELETE"])
    def delete_command(command_id):
        auth_err = _check_auth()
        if auth_err:
            return auth_err
        try:
            removed = app.command_engine.delete_command(command_id)
        except Exception as e:
            logging.error(f"删除命令失败: {e}")
            return jsonify({"code": 500, "message": "Command save failed", "error_detail": str(e)}), 500
        if not removed:
            return jsonify({"code": 404, "message": "Command not found"}), 404
        return jsonify({"code": 200, "message": "success", "removed": 1})

    @app.route("/commands/reload", methods=["POST"])
    def reload_commands():
        auth_err = _check_auth()
        if auth_err:
            return auth_err
        try:
            count = app.command_engine.reload()
            return jsonify({"code": 200, "message": "success", "count": count})
        except Exception as e:
            logging.error(f"重载命令失败: {e}")
            return jsonify({"code": 500, "message": "Command reload failed", "error_detail": str(e)}), 500

    @app.route("/commands/test", methods=["POST"])
    def test_command():
        auth_err = _check_auth()
        if auth_err:
            return auth_err
        data = request.get_json(silent=True) or {}
        text = strip_command_prefix(str(data.get("text", "")), app.voice_config.command_prefix)
        result = app.command_engine.match(text)
        payload = command_result_to_dict(result)
        payload.update({"code": 200, "message": "success"})
        return jsonify(payload)

    @app.route("/commands/execute", methods=["POST"])
    def execute_command():
        auth_err = _check_auth()
        if auth_err:
            return auth_err
        data = request.get_json(silent=True) or {}
        text = strip_command_prefix(str(data.get("text", "")), app.voice_config.command_prefix)
        result = app.command_engine.execute(
            text,
            confirmed=bool(data.get("confirmed", False)),
            dry_run=bool(data.get("dry_run", False)),
        )
        payload = command_result_to_dict(result)
        payload.update({"code": 200, "message": "success"})
        if result.requires_confirmation:
            payload["code"] = 202
            payload["message"] = "Command requires confirmation"
            return jsonify(payload), 202
        if result.error:
            payload["code"] = 500
            payload["message"] = "Command action failed"
            return jsonify(payload), 500
        if not result.matched:
            payload["code"] = 404
            payload["message"] = "Command not matched"
            return jsonify(payload), 404
        return jsonify(payload)

    @app.before_request
    def handle_options_preflight():
        if request.method == "OPTIONS":
            resp = app.make_response("")
            resp.status_code = 204
            return resp

    @app.after_request
    def add_cors_headers(resp):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Auth-Token"
        resp.headers["Access-Control-Max-Age"] = "86400"
        return resp

    # ==================== PWA 静态资源 ====================

    logging.info("正在生成 PWA 图标...")
    _ICON_192 = _make_icon_png(192)
    _ICON_512 = _make_icon_png(512)
    logging.info(f"PWA 图标已生成 (192: {len(_ICON_192)} B, 512: {len(_ICON_512)} B)")

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
        "id": "/",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#f5f5f7",
        "theme_color": "#007aff",
        "lang": "zh-CN",
        "categories": ["utilities", "productivity"],
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192",
             "type": "image/png", "purpose": "any"},
            {"src": "/icon-512.png", "sizes": "512x512",
             "type": "image/png", "purpose": "any"},
            {"src": "/icon-192.png", "sizes": "192x192",
             "type": "image/png", "purpose": "maskable"},
            {"src": "/icon-512.png", "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
            {"src": "/icon.svg", "sizes": "any",
             "type": "image/svg+xml", "purpose": "any"}
        ]
    }, ensure_ascii=False, indent=2)

    _SW_JS = r"""
const CACHE = 'vi-v3';
const SHELL = ['/', '/manifest.json', '/icon.svg', '/icon-192.png', '/icon-512.png'];

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
  if (url.origin !== location.origin) return;
  if (['/input','/history','/status','/key','/message','/messages'].some(p =>
        url.pathname === p || url.pathname.startsWith(p + '/'))) return;
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

    @app.route("/icon-192.png", methods=["GET"])
    def pwa_icon_192():
        return Response(_ICON_192, mimetype="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})

    @app.route("/icon-512.png", methods=["GET"])
    def pwa_icon_512():
        return Response(_ICON_512, mimetype="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})

    # ==================== 快捷按键 ====================

    @app.route("/key", methods=["POST"])
    def handle_key():
        auth_err = _check_auth()
        if auth_err:
            return auth_err

        try:
            data = request.get_json(force=True)
        except Exception:
            return jsonify({"code": 400, "message": "Invalid JSON"}), 400

        key = (data.get("key") or "").strip()
        if not key:
            return jsonify({"code": 400, "message": "Missing key"}), 400

        count = max(1, min(int(data.get("count", 1)), 10000))
        interval = max(0.05, min(float(data.get("interval", 10000)) / 1000, 5.0))

        try:
            if key in ("click", "right_click"):
                _do_mouse_click("right" if key == "right_click" else "left", count, interval)
            else:
                _do_key_press(key, count, interval)
            return jsonify({
                "code": 200, "message": "success",
                "key": key, "count": count
            })
        except Exception as e:
            logging.error(f"按键操作失败: {e}")
            return jsonify({
                "code": 500, "message": "Key action failed",
                "error_detail": str(e)
            }), 500

    # ==================== 消息接收 ====================

    @app.route("/message", methods=["POST"])
    def push_message():
        auth_err = _check_auth()
        if auth_err:
            return auth_err
        try:
            data = request.get_json(force=True)
        except Exception:
            return jsonify({"code": 400, "message": "Invalid JSON"}), 400

        content = str(data.get("content", "")).strip()
        if not content:
            return jsonify({"code": 400, "message": "Missing content"}), 400

        source = str(data.get("source", "api")).strip() or "api"
        current_time = int(time.time() * 1000)

        with app.voice_messages_lock:
            app.voice_messages_counter += 1
            msg = {
                "id": app.voice_messages_counter,
                "content": content,
                "source": source,
                "timestamp": current_time,
                "client_ip": get_client_ip(request),
            }
            app.voice_messages.append(msg)

        logging.info(
            f"收到消息 (id={msg['id']}, source={source}, len={len(content)})"
        )
        return jsonify(
            {"code": 200, "message": "success", "id": msg["id"], "timestamp": current_time}
        )

    @app.route("/messages", methods=["GET"])
    def get_messages():
        auth_err = _check_auth()
        if auth_err:
            return auth_err
        since_id = request.args.get("since", 0, type=int)
        with app.voice_messages_lock:
            items = list(app.voice_messages)
        if since_id:
            items = [m for m in items if m["id"] > since_id]
        return jsonify(
            {
                "code": 200,
                "message": "success",
                "items": items,
                "timestamp": int(time.time() * 1000),
            }
        )

    @app.route("/messages/<int:msg_id>", methods=["DELETE"])
    def delete_message(msg_id):
        auth_err = _check_auth()
        if auth_err:
            return auth_err
        with app.voice_messages_lock:
            before = len(app.voice_messages)
            app.voice_messages = deque(
                (m for m in app.voice_messages if m["id"] != msg_id),
                maxlen=config.history_size,
            )
            removed = before - len(app.voice_messages)
        return jsonify({"code": 200, "message": "success", "removed": removed})

    @app.route("/messages", methods=["DELETE"])
    def clear_messages():
        auth_err = _check_auth()
        if auth_err:
            return auth_err
        data = request.get_json(silent=True) or {}
        ids = data.get("ids", [])
        with app.voice_messages_lock:
            if ids:
                id_set = set(ids)
                before = len(app.voice_messages)
                app.voice_messages = deque(
                    (m for m in app.voice_messages if m["id"] not in id_set),
                    maxlen=config.history_size,
                )
                removed = before - len(app.voice_messages)
            else:
                removed = len(app.voice_messages)
                app.voice_messages.clear()
        return jsonify({"code": 200, "message": "success", "removed": removed})

    @app.route("/messages/export", methods=["GET"])
    def export_messages():
        auth_err = _check_auth()
        if auth_err:
            return auth_err
        fmt = request.args.get("format", "json")
        with app.voice_messages_lock:
            items = list(app.voice_messages)
        if fmt == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["id", "time", "source", "content"])
            for item in items:
                t = time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(item["timestamp"] / 1000)
                )
                writer.writerow(
                    [item.get("id", ""), t, item.get("source", ""), item.get("content", "")]
                )
            return Response(
                output.getvalue(),
                mimetype="text/csv",
                headers={"Content-Disposition": "attachment; filename=messages.csv"},
            )
        else:
            return Response(
                json.dumps(items, ensure_ascii=False, indent=2),
                mimetype="application/json",
                headers={"Content-Disposition": "attachment; filename=messages.json"},
            )

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
