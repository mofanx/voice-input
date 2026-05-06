"""命令模式：规则匹配与动作执行"""

import copy
import logging
import os
import platform
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple


DEFAULT_COMMANDS = [
    {
        "id": "app_switch_next",
        "name": "切换下一个应用",
        "enabled": True,
        "category": "desktop",
        "match": {"type": "keyword", "patterns": ["切换应用", "下一个应用", "下一个窗口", "alt tab", "切到下一个"]},
        "action": {"type": "key", "key": "alt+tab"},
        "risk": "low",
        "confirm": False,
    },
    {
        "id": "app_switch_prev",
        "name": "切换上一个应用",
        "enabled": True,
        "category": "desktop",
        "match": {"type": "keyword", "patterns": ["上一个应用", "上一个窗口", "切到上一个"]},
        "action": {"type": "key", "key": "shift+alt+tab"},
        "risk": "low",
        "confirm": False,
    },
    {
        "id": "window_list",
        "name": "列出窗口",
        "enabled": True,
        "category": "window",
        "match": {"type": "keyword", "patterns": ["列出窗口", "显示窗口", "查看窗口", "当前窗口列表"]},
        "action": {"type": "gauto", "args": ["list"]},
        "risk": "low",
        "confirm": False,
    },
    {
        "id": "window_switch",
        "name": "切换窗口",
        "enabled": True,
        "category": "window",
        "match": {"type": "regex", "patterns": [r"切换到第?(\d+)个?窗口", r"切换窗口(\d+)", r"打开第?(\d+)个?窗口"]},
        "action": {"type": "gauto_template", "template": ["switch", "{1}"]},
        "risk": "low",
        "confirm": False,
    },
    {
        "id": "window_activate_by_title",
        "name": "激活窗口",
        "enabled": True,
        "category": "window",
        "match": {"type": "regex", "patterns": [r"切换到(.+)", r"激活(.+)"]},
        "action": {"type": "gauto_template", "template": ["activate", "{1}"]},
        "risk": "low",
        "confirm": False,
    },
    {
        "id": "window_close",
        "name": "关闭窗口",
        "enabled": True,
        "category": "window",
        "match": {"type": "regex", "patterns": [r"关闭窗口(.+)", r"关掉窗口(.+)", r"关闭第?(\d+)个?窗口"]},
        "action": {"type": "gauto_template", "template": ["kill", "{1}"]},
        "risk": "medium",
        "confirm": True,
    },
    {
        "id": "app_list",
        "name": "列出应用",
        "enabled": True,
        "category": "app",
        "match": {"type": "keyword", "patterns": ["列出应用", "查看应用列表", "应用列表"]},
        "action": {"type": "gauto", "args": ["list-apps"]},
        "risk": "low",
        "confirm": False,
    },
    {
        "id": "app_search",
        "name": "搜索应用",
        "enabled": True,
        "category": "app",
        "match": {"type": "regex", "patterns": [r"搜索应用(.+)", r"查找应用(.+)", r"找应用(.+)"]},
        "action": {"type": "gauto_template", "template": ["list-apps", "--search", "{1}"]},
        "risk": "low",
        "confirm": False,
    },
    {
        "id": "app_launch",
        "name": "启动应用",
        "enabled": True,
        "category": "app",
        "match": {"type": "regex", "patterns": [r"启动(.+)", r"打开应用(.+)", r"运行(.+)"]},
        "action": {"type": "gauto_template", "template": ["launch", "{1}"]},
        "risk": "low",
        "confirm": False,
    },
    {
        "id": "open_terminal",
        "name": "打开终端",
        "enabled": True,
        "category": "app",
        "match": {"type": "keyword", "patterns": ["打开终端", "启动终端", "打开命令行", "terminal"]},
        "action": {"type": "key", "key": "ctrl+alt+t"},
        "risk": "low",
        "confirm": False,
    },
    {
        "id": "system_lock",
        "name": "锁屏",
        "enabled": True,
        "category": "system",
        "match": {"type": "keyword", "patterns": ["锁屏", "锁定屏幕", "锁定电脑", "电脑锁屏"]},
        "action": {"type": "platform_shell", "commands": {"Linux": ["loginctl", "lock-session"], "Darwin": ["pmset", "displaysleepnow"], "Windows": ["rundll32.exe", "user32.dll,LockWorkStation"]}},
        "risk": "medium",
        "confirm": False,
    },
    {
        "id": "system_suspend",
        "name": "挂起",
        "enabled": True,
        "category": "system",
        "match": {"type": "keyword", "patterns": ["睡眠", "挂起", "电脑睡眠", "让电脑休眠"]},
        "action": {"type": "platform_shell", "commands": {"Linux": ["systemctl", "suspend"], "Darwin": ["pmset", "sleepnow"], "Windows": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"]}},
        "risk": "high",
        "confirm": True,
    },
    {
        "id": "system_reboot",
        "name": "重启",
        "enabled": True,
        "category": "system",
        "match": {"type": "keyword", "patterns": ["重启", "重启电脑", "重新启动"]},
        "action": {"type": "platform_shell", "commands": {"Linux": ["systemctl", "reboot"], "Darwin": ["osascript", "-e", "tell app \"System Events\" to restart"], "Windows": ["shutdown", "/r", "/t", "0"]}},
        "risk": "high",
        "confirm": True,
    },
    {
        "id": "system_poweroff",
        "name": "关机",
        "enabled": True,
        "category": "system",
        "match": {"type": "keyword", "patterns": ["关机", "关闭电脑", "电脑关机", "关掉电脑"]},
        "action": {"type": "platform_shell", "commands": {"Linux": ["systemctl", "poweroff"], "Darwin": ["osascript", "-e", "tell app \"System Events\" to shut down"], "Windows": ["shutdown", "/s", "/t", "0"]}},
        "risk": "high",
        "confirm": True,
    },
    {
        "id": "volume_up",
        "name": "音量增大",
        "enabled": True,
        "category": "media",
        "match": {"type": "keyword", "patterns": ["音量增大", "大点声", "声音大一点", "调高音量"]},
        "action": {"type": "platform_shell", "commands": {"Linux": ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%+"], "Darwin": ["osascript", "-e", "set volume output volume ((output volume of (get volume settings)) + 5)"], "Windows": []}},
        "risk": "low",
        "confirm": False,
    },
    {
        "id": "volume_down",
        "name": "音量减小",
        "enabled": True,
        "category": "media",
        "match": {"type": "keyword", "patterns": ["音量减小", "小点声", "声音小一点", "调低音量"]},
        "action": {"type": "platform_shell", "commands": {"Linux": ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%-"], "Darwin": ["osascript", "-e", "set volume output volume ((output volume of (get volume settings)) - 5)"], "Windows": []}},
        "risk": "low",
        "confirm": False,
    },
    {
        "id": "volume_mute_toggle",
        "name": "静音切换",
        "enabled": True,
        "category": "media",
        "match": {"type": "keyword", "patterns": ["静音", "取消静音", "切换静音", "关闭声音"]},
        "action": {"type": "platform_shell", "commands": {"Linux": ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"], "Darwin": ["osascript", "-e", "set volume with output muted not (output muted of (get volume settings))"], "Windows": []}},
        "risk": "low",
        "confirm": False,
    },
    {
        "id": "edit_copy",
        "name": "复制",
        "enabled": True,
        "category": "edit",
        "match": {"type": "keyword", "patterns": ["复制", "拷贝"]},
        "action": {"type": "key", "key": "ctrl+c"},
        "risk": "low",
        "confirm": False,
    },
    {
        "id": "edit_paste",
        "name": "粘贴",
        "enabled": True,
        "category": "edit",
        "match": {"type": "keyword", "patterns": ["粘贴", "贴上"]},
        "action": {"type": "key", "key": "ctrl+v"},
        "risk": "low",
        "confirm": False,
    },
    {
        "id": "edit_save",
        "name": "保存",
        "enabled": True,
        "category": "edit",
        "match": {"type": "keyword", "patterns": ["保存", "保存文件"]},
        "action": {"type": "key", "key": "ctrl+s"},
        "risk": "low",
        "confirm": False,
    },
    {
        "id": "browser_new_tab",
        "name": "新建标签页",
        "enabled": True,
        "category": "browser",
        "match": {"type": "keyword", "patterns": ["新建标签", "新建标签页", "打开新标签"]},
        "action": {"type": "key", "key": "ctrl+t"},
        "risk": "low",
        "confirm": False,
    },
    {
        "id": "browser_close_tab",
        "name": "关闭标签页",
        "enabled": True,
        "category": "browser",
        "match": {"type": "keyword", "patterns": ["关闭标签", "关闭标签页", "关掉标签"]},
        "action": {"type": "key", "key": "ctrl+w"},
        "risk": "medium",
        "confirm": False,
    },
    {
        "id": "browser_refresh",
        "name": "刷新页面",
        "enabled": True,
        "category": "browser",
        "match": {"type": "keyword", "patterns": ["刷新", "刷新页面", "重新加载"]},
        "action": {"type": "key", "key": "ctrl+r"},
        "risk": "low",
        "confirm": False,
    },
]


@dataclass
class CommandResult:
    matched: bool
    command: Optional[Dict[str, Any]] = None
    captures: Tuple[str, ...] = ()
    executed: bool = False
    requires_confirmation: bool = False
    output: str = ""
    error: str = ""


@dataclass
class ShellResult:
    cmd: str = ""
    executed: bool = False
    requires_confirmation: bool = False
    dangerous: bool = False
    danger_reason: str = ""
    output: str = ""
    error: str = ""


class CommandEngine:
    def __init__(
        self,
        commands: Optional[List[Dict[str, Any]]] = None,
        gauto_path: str = "gauto",
        command_file: str = "",
        enabled: bool = False,
        require_confirm_risks: Optional[List[str]] = None,
        key_executor: Optional[Callable[[str], None]] = None,
    ):
        self.commands = commands if commands is not None else copy.deepcopy(DEFAULT_COMMANDS)
        self.gauto_path = gauto_path
        self.command_file = command_file
        self.enabled = enabled
        self.require_confirm_risks = set(require_confirm_risks or ["high"])
        self.key_executor = key_executor

    @classmethod
    def from_config(cls, cfg, key_executor: Optional[Callable[[str], None]] = None):
        commands = load_commands_from_file(getattr(cfg, "command_file", ""))
        return cls(
            commands=commands,
            gauto_path=getattr(cfg, "gauto_path", "gauto"),
            command_file=getattr(cfg, "command_file", ""),
            enabled=getattr(cfg, "command_mode_enabled", False),
            require_confirm_risks=getattr(cfg, "command_require_confirm_risks", ["high"]),
            key_executor=key_executor,
        )

    def list_commands(self) -> List[Dict[str, Any]]:
        return copy.deepcopy(self.commands)

    def reload(self) -> int:
        commands = load_commands_from_file(self.command_file)
        self.commands = commands if commands is not None else copy.deepcopy(DEFAULT_COMMANDS)
        return len(self.commands)

    def add_command(self, command: Dict[str, Any]) -> Dict[str, Any]:
        normalized = normalize_command(command)
        command_id = normalized["id"]
        if self.get_command(command_id) is not None:
            raise ValueError(f"Command already exists: {command_id}")
        self.commands.append(normalized)
        self.save()
        return copy.deepcopy(normalized)

    def update_command(self, command_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
        idx = self._find_index(command_id)
        if idx < 0:
            raise KeyError(command_id)
        updated = deep_merge(copy.deepcopy(self.commands[idx]), patch)
        updated["id"] = command_id
        normalized = normalize_command(updated)
        self.commands[idx] = normalized
        self.save()
        return copy.deepcopy(normalized)

    def delete_command(self, command_id: str) -> bool:
        idx = self._find_index(command_id)
        if idx < 0:
            return False
        del self.commands[idx]
        self.save()
        return True

    def get_command(self, command_id: str) -> Optional[Dict[str, Any]]:
        idx = self._find_index(command_id)
        if idx < 0:
            return None
        return copy.deepcopy(self.commands[idx])

    def save(self):
        save_commands_to_file(self.command_file, self.commands)

    def _find_index(self, command_id: str) -> int:
        target = str(command_id or "").strip()
        for idx, command in enumerate(self.commands):
            if str(command.get("id", "")).strip() == target:
                return idx
        return -1

    def match(self, text: str) -> CommandResult:
        normalized = normalize_text(text)
        for command in self.commands:
            if not command.get("enabled", True):
                continue
            ok, captures = match_command(normalized, command.get("match") or {})
            if ok:
                return CommandResult(matched=True, command=copy.deepcopy(command), captures=captures)
        return CommandResult(matched=False)

    def execute(self, text: str, confirmed: bool = False, dry_run: bool = False) -> CommandResult:
        result = self.match(text)
        if not result.matched or not result.command:
            return result
        command = result.command
        risk = str(command.get("risk", "low")).lower()
        needs_confirm = bool(command.get("confirm")) or risk in self.require_confirm_risks
        if needs_confirm and not confirmed:
            result.requires_confirmation = True
            return result
        if dry_run:
            return result
        try:
            result.output = self._execute_action(command.get("action") or {}, result.captures)
            result.executed = True
        except Exception as exc:
            result.error = str(exc)
            logging.error(f"命令执行失败: {command.get('id')}: {exc}")
        return result

    def _execute_action(self, action: Dict[str, Any], captures: Tuple[str, ...]) -> str:
        action_type = action.get("type")
        if action_type == "key":
            key = str(action.get("key", "")).strip()
            if not key:
                raise ValueError("Missing key")
            if self.key_executor:
                self.key_executor(key)
                return ""
            return run_process([self._resolve_gauto_path(), "key", key])
        if action_type == "gauto":
            return run_process([self._resolve_gauto_path()] + [str(x) for x in action.get("args", [])])
        if action_type == "gauto_template":
            args = [render_template_arg(str(x), captures) for x in action.get("template", [])]
            return run_process([self._resolve_gauto_path()] + args)
        if action_type == "shell":
            command = action.get("command") or []
            return run_process(expand_command([str(x) for x in command]))
        if action_type == "platform_shell":
            commands = action.get("commands") or {}
            command = commands.get(platform.system()) or commands.get("default") or []
            if not command:
                raise RuntimeError(f"当前系统不支持该命令: {platform.system()}")
            return run_process(expand_command([str(x) for x in command]))
        raise ValueError(f"Unsupported action type: {action_type}")

    def _resolve_gauto_path(self) -> str:
        expanded = os.path.expandvars(os.path.expanduser(self.gauto_path))
        if os.path.isabs(expanded):
            return expanded
        return shutil.which(expanded) or expanded


_TRAILING_PUNCT = re.compile(r'[，。、；：？！,.;:?!]+$')

def normalize_text(text: str) -> str:
    s = " ".join(str(text or "").strip().lower().split())
    return _TRAILING_PUNCT.sub("", s).rstrip()


def strip_command_prefix(text: str, prefix: str = "/") -> str:
    raw = str(text or "").strip()
    if raw.startswith(prefix):
        return raw[len(prefix):].strip()
    return raw


def strip_shell_prefix(text: str, prefix: str = ":") -> str:
    raw = str(text or "").strip()
    if raw.startswith(prefix):
        return raw[len(prefix):].strip()
    return raw


def is_dangerous_shell_command(cmd: str, patterns: List[str]) -> Tuple[bool, str]:
    for pattern in patterns:
        if re.search(pattern, cmd, re.IGNORECASE):
            return True, pattern
    return False, ""


_DESKTOP_ENV_KEYS = (
    "DBUS_SESSION_BUS_ADDRESS", "DISPLAY", "WAYLAND_DISPLAY",
    "XDG_RUNTIME_DIR", "XDG_SESSION_TYPE",
)


def _get_desktop_env() -> dict:
    """补全桌面环境变量，解决 Flask 进程继承不到 D-Bus 的问题"""
    env = os.environ.copy()
    uid = os.getuid()

    # 优先用 systemd 用户会话的标准路径（现代 Linux 固定存在）
    if not env.get("DBUS_SESSION_BUS_ADDRESS"):
        std_bus = f"/run/user/{uid}/bus"
        if os.path.exists(std_bus):
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={std_bus}"

    if not env.get("XDG_RUNTIME_DIR"):
        xdg = f"/run/user/{uid}"
        if os.path.isdir(xdg):
            env["XDG_RUNTIME_DIR"] = xdg

    # 若仍缺 DISPLAY/WAYLAND_DISPLAY，从 /proc 同 uid 进程中探测
    missing = [k for k in ("DISPLAY", "WAYLAND_DISPLAY") if not env.get(k)]
    if missing:
        try:
            for pid in os.listdir("/proc"):
                if not pid.isdigit():
                    continue
                try:
                    if os.stat(f"/proc/{pid}").st_uid != uid:
                        continue
                    with open(f"/proc/{pid}/environ", "rb") as f:
                        raw = f.read()
                    pairs = {
                        kv[:s].decode(errors="replace"): kv[s + 1:].decode(errors="replace")
                        for kv in raw.split(b"\x00")
                        if (s := kv.find(b"=")) > 0
                    }
                    for k in missing:
                        if k in pairs and not env.get(k):
                            env[k] = pairs[k]
                    if all(env.get(k) for k in missing):
                        break
                except (PermissionError, FileNotFoundError, ProcessLookupError):
                    continue
        except Exception as exc:
            logging.debug(f"_get_desktop_env /proc 探测失败: {exc}")
    return env


def exec_shell_command(
    cmd: str,
    danger_patterns: List[str],
    confirmed: bool = False,
    need_confirm: bool = True,
) -> ShellResult:
    result = ShellResult(cmd=cmd)
    dangerous, reason = is_dangerous_shell_command(cmd, danger_patterns)
    if dangerous:
        result.dangerous = True
        result.danger_reason = reason
        result.error = f"危险命令已拦截，pattern: {reason}"
        logging.warning(f"Shell 危险命令拦截: {cmd!r} matched {reason!r}")
        return result
    if need_confirm and not confirmed:
        result.requires_confirmation = True
        return result
    try:
        env = _get_desktop_env()
        sudo_user = os.environ.get("SUDO_USER")
        if os.getuid() == 0 and sudo_user:
            uid_result = subprocess.run(["id", "-u", sudo_user], capture_output=True, text=True)
            real_uid = uid_result.stdout.strip()
            dbus_addr = f"unix:path=/run/user/{real_uid}/bus"
            xdg_dir = f"/run/user/{real_uid}"
            env_prefix = (
                f"DBUS_SESSION_BUS_ADDRESS={dbus_addr} "
                f"XDG_RUNTIME_DIR={xdg_dir} "
                f"WAYLAND_DISPLAY=wayland-0 "
            )
            actual_cmd = f"sudo -u {sudo_user} -H sh -c '{env_prefix}{cmd}'"
        else:
            actual_cmd = cmd
        completed = subprocess.run(
            actual_cmd, shell=True, timeout=15, capture_output=True, text=True,
            env=env
        )
        result.output = (completed.stdout or "").strip()
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            result.error = stderr or f"exit code {completed.returncode}"
        else:
            result.executed = True
    except subprocess.TimeoutExpired:
        result.error = "命令执行超时（15s）"
    except Exception as exc:
        result.error = str(exc)
        logging.error(f"Shell 执行失败: {cmd!r}: {exc}")
    return result


def match_command(text: str, match: Dict[str, Any]) -> Tuple[bool, Tuple[str, ...]]:
    match_type = str(match.get("type", "keyword")).lower()
    patterns = match.get("patterns") or []
    if match_type == "keyword":
        lower = text.lower()
        for pattern in patterns:
            if str(pattern).lower() in lower:
                return True, ()
        return False, ()
    if match_type == "exact":
        lower = text.lower()
        for pattern in patterns:
            if lower == str(pattern).strip().lower():
                return True, ()
        return False, ()
    if match_type == "regex":
        for pattern in patterns:
            m = re.search(str(pattern), text, re.IGNORECASE)
            if m:
                return True, tuple(str(x).strip() for x in m.groups())
        return False, ()
    return False, ()


def render_template_arg(value: str, captures: Tuple[str, ...]) -> str:
    rendered = value
    for idx, capture in enumerate(captures, start=1):
        rendered = rendered.replace("{" + str(idx) + "}", capture)
    return os.path.expandvars(os.path.expanduser(rendered))


def expand_command(command: List[str]) -> List[str]:
    return [os.path.expandvars(os.path.expanduser(x)) for x in command]


def run_process(command: List[str]) -> str:
    if not command or not command[0]:
        raise ValueError("Empty command")
    env = _get_desktop_env()
    sudo_user = os.environ.get("SUDO_USER")
    if os.getuid() == 0 and sudo_user:
        uid_result = subprocess.run(["id", "-u", sudo_user], capture_output=True, text=True)
        real_uid = uid_result.stdout.strip()
        env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{real_uid}/bus"
        env["XDG_RUNTIME_DIR"] = f"/run/user/{real_uid}"
        cmd_str = subprocess.list2cmdline(command)
        actual = ["sudo", "-u", sudo_user, "-H", "sh", "-c",
                  f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{real_uid}/bus "
                  f"XDG_RUNTIME_DIR=/run/user/{real_uid} "
                  f"WAYLAND_DISPLAY=wayland-0 {cmd_str}"]
        completed = subprocess.run(actual, timeout=15, capture_output=True, text=True, env=env)
    else:
        completed = subprocess.run(command, timeout=15, capture_output=True, text=True, env=env)
    output = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode != 0:
        raise RuntimeError(output.strip() or f"Command failed: {completed.returncode}")
    return output.strip()


def load_commands_from_file(path: str) -> Optional[List[Dict[str, Any]]]:
    if not path:
        return None
    expanded = os.path.expandvars(os.path.expanduser(path))
    if not os.path.exists(expanded):
        logging.warning(f"命令文件不存在，使用内置命令: {expanded}")
        return None
    try:
        import yaml
    except ImportError:
        logging.warning("PyYAML 未安装，无法读取外部命令文件，使用内置命令")
        return None
    with open(expanded, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if isinstance(data, list):
        return data
    commands = data.get("commands")
    if isinstance(commands, list):
        return commands
    logging.warning(f"命令文件格式无效，使用内置命令: {expanded}")
    return None


def save_commands_to_file(path: str, commands: List[Dict[str, Any]]):
    if not path:
        raise ValueError("command_file 未配置，无法保存命令")
    expanded = os.path.expandvars(os.path.expanduser(path))
    parent = os.path.dirname(expanded)
    if parent:
        os.makedirs(parent, exist_ok=True)
    try:
        import yaml
    except ImportError:
        raise RuntimeError("PyYAML 未安装，无法保存命令文件")
    with open(expanded, "w", encoding="utf-8") as f:
        yaml.safe_dump({"commands": commands}, f, allow_unicode=True, sort_keys=False)


def normalize_command(command: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(command, dict):
        raise ValueError("Command must be an object")
    normalized = copy.deepcopy(command)
    command_id = str(normalized.get("id", "")).strip()
    if not command_id:
        raise ValueError("Command id is required")
    if not re.match(r"^[A-Za-z0-9_.-]+$", command_id):
        raise ValueError("Command id 只能包含字母、数字、下划线、点和短横线")
    normalized["id"] = command_id
    normalized["name"] = str(normalized.get("name") or command_id).strip()
    normalized["enabled"] = bool(normalized.get("enabled", True))
    normalized["category"] = str(normalized.get("category") or "custom").strip()
    normalized["risk"] = str(normalized.get("risk") or "low").strip().lower()
    normalized["confirm"] = bool(normalized.get("confirm", False))
    match = normalized.get("match")
    if not isinstance(match, dict):
        raise ValueError("Command match is required")
    match_type = str(match.get("type") or "keyword").strip().lower()
    if match_type not in {"keyword", "exact", "regex"}:
        raise ValueError(f"Unsupported match type: {match_type}")
    patterns = match.get("patterns")
    if not isinstance(patterns, list) or not patterns:
        raise ValueError("Command match.patterns must be a non-empty list")
    normalized["match"] = {
        "type": match_type,
        "patterns": [str(x) for x in patterns if str(x).strip()],
    }
    if not normalized["match"]["patterns"]:
        raise ValueError("Command match.patterns must contain valid values")
    action = normalized.get("action")
    if not isinstance(action, dict):
        raise ValueError("Command action is required")
    action_type = str(action.get("type") or "").strip()
    if action_type not in {"key", "gauto", "gauto_template", "shell", "platform_shell"}:
        raise ValueError(f"Unsupported action type: {action_type}")
    normalized["action"] = copy.deepcopy(action)
    normalized["action"]["type"] = action_type
    return normalized


def deep_merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in patch.items():
        if key == "id":
            continue
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = deep_merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def shell_result_to_dict(result: ShellResult) -> Dict[str, Any]:
    return {
        "cmd": result.cmd,
        "executed": result.executed,
        "requires_confirmation": result.requires_confirmation,
        "dangerous": result.dangerous,
        "danger_reason": result.danger_reason,
        "output": result.output,
        "error": result.error,
    }


def command_result_to_dict(result: CommandResult) -> Dict[str, Any]:
    command = result.command or {}
    return {
        "matched": result.matched,
        "command_id": command.get("id"),
        "command_name": command.get("name"),
        "category": command.get("category"),
        "risk": command.get("risk"),
        "executed": result.executed,
        "requires_confirmation": result.requires_confirmation,
        "output": result.output,
        "error": result.error,
    }
