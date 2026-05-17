"""配置管理 - 支持 YAML 配置文件、环境变量、CLI 参数三级合并"""

import os
import secrets
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class AppConfig:
    """应用配置，优先级：CLI 参数 > 环境变量 > 配置文件 > 默认值"""

    # 网络
    host: str = "0.0.0.0"
    port: int = 8080

    # 安全
    allowed_ips: List[str] = field(
        default_factory=lambda: ["192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12", "127.0.0.0/8", "localhost"]
    )
    token: str = ""
    require_token: bool = False

    # 行为
    auto_paste: bool = True
    history_size: int = 50
    max_content_length: int = 10 * 1024  # 10KB
    command_mode_enabled: bool = True
    command_prefix: str = "/"
    command_file: str = ""
    gauto_path: str = "gauto"
    command_require_confirm_risks: List[str] = field(default_factory=lambda: ["high"])
    shell_enabled: bool = True
    shell_prefix: str = ":"
    shell_confirm: bool = False
    shell_danger_patterns: List[str] = field(default_factory=lambda: [
        r"rm\s+-[a-z]*r[a-z]*f", r"rm\s+-[a-z]*f[a-z]*r",
        r"mkfs", r"dd\s+if=", r":\s*\(\s*\)\s*\{",
        r">(\s*)\s*/dev/(s?da|nvme|hd)",
        r"chmod\s+-[a-z]*R.*777", r"chown\s+-[a-z]*R.*root",
        r"mv\s+.+\s+/dev/null",
    ])

    # 持久化
    db_path: str = ""

    # 生产部署
    workers: int = 1
    log_level: str = "info"

    def __post_init__(self):
        if self.require_token and not self.token:
            self.token = secrets.token_urlsafe(18)


def _parse_bool(val: str) -> bool:
    return val.strip().lower() in {"1", "true", "yes", "on"}


def load_from_yaml(path: str) -> dict:
    """从 YAML 文件加载配置"""
    try:
        import yaml
    except ImportError:
        raise ImportError(
            "需要 PyYAML 来读取配置文件，请执行: pip install pyyaml"
        )
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


def load_from_env() -> dict:
    """从环境变量加载配置（VOICE_INPUT_ 前缀）"""
    mapping = {
        "VOICE_INPUT_HOST": "host",
        "VOICE_INPUT_PORT": "port",
        "VOICE_INPUT_ALLOWED_IPS": "allowed_ips",
        "VOICE_INPUT_TOKEN": "token",
        "VOICE_INPUT_REQUIRE_TOKEN": "require_token",
        "VOICE_INPUT_AUTO_PASTE": "auto_paste",
        "VOICE_INPUT_HISTORY_SIZE": "history_size",
        "VOICE_INPUT_MAX_CONTENT_LENGTH": "max_content_length",
        "VOICE_INPUT_COMMAND_MODE_ENABLED": "command_mode_enabled",
        "VOICE_INPUT_COMMAND_PREFIX": "command_prefix",
        "VOICE_INPUT_COMMAND_FILE": "command_file",
        "VOICE_INPUT_GAUTO_PATH": "gauto_path",
        "VOICE_INPUT_COMMAND_REQUIRE_CONFIRM_RISKS": "command_require_confirm_risks",
        "VOICE_INPUT_SHELL_ENABLED": "shell_enabled",
        "VOICE_INPUT_SHELL_PREFIX": "shell_prefix",
        "VOICE_INPUT_SHELL_CONFIRM": "shell_confirm",
        "VOICE_INPUT_DB_PATH": "db_path",
        "VOICE_INPUT_WORKERS": "workers",
        "VOICE_INPUT_LOG_LEVEL": "log_level",
    }
    result = {}
    for env_key, cfg_key in mapping.items():
        val = os.environ.get(env_key)
        if val is None:
            continue
        result[cfg_key] = val
    return result


def _coerce(key: str, val):
    """将字符串值转为目标类型"""
    bool_keys = {"require_token", "auto_paste", "command_mode_enabled", "shell_enabled", "shell_confirm"}
    int_keys = {"port", "history_size", "max_content_length", "workers"}
    list_keys = {"allowed_ips", "command_require_confirm_risks", "shell_danger_patterns"}

    if key in bool_keys and isinstance(val, str):
        return _parse_bool(val)
    if key in int_keys and isinstance(val, str):
        return int(val)
    if key in list_keys and isinstance(val, str):
        return [s.strip() for s in val.split(",") if s.strip()]
    return val


APP_NAME = "voice-input"


def _real_home() -> Path:
    """返回真实用户的 home 目录，sudo 时使用 SUDO_USER 而非 root"""
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and os.getuid() == 0:
        import pwd
        try:
            return Path(pwd.getpwnam(sudo_user).pw_dir)
        except KeyError:
            pass
    return Path.home()


def get_user_config_dir() -> Path:
    """返回跨平台的用户配置目录，sudo 运行时指向原始用户目录而非 root"""
    home = _real_home()
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME", "")
        # sudo 时 XDG_CONFIG_HOME 可能指向 root，忽略它
        if xdg and not (os.getuid() == 0 and os.environ.get("SUDO_USER")):
            base = Path(xdg)
        else:
            base = home / ".config"
    return base / APP_NAME


def find_config_file(explicit: Optional[str] = None) -> Optional[str]:
    """按优先级查找配置文件，返回找到的路径或 None"""
    # 1. CLI 显式指定
    if explicit:
        return explicit
    # 2. 环境变量
    env_cfg = os.environ.get("VOICE_INPUT_CONFIG")
    if env_cfg:
        return env_cfg
    # 3. 当前工作目录
    cwd_cfg = Path.cwd() / "config.yaml"
    if cwd_cfg.exists():
        return str(cwd_cfg)
    # 4. 用户配置目录
    user_cfg = get_user_config_dir() / "config.yaml"
    if user_cfg.exists():
        return str(user_cfg)
    return None


def init_user_config() -> Path:
    """首次运行时在用户配置目录生成默认配置和命令文件，返回配置目录路径"""
    config_dir = get_user_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)

    config_file = config_dir / "config.yaml"
    commands_file = config_dir / "commands.yaml"

    # 找 example 文件（与本模块同级的上级目录）
    pkg_dir = Path(__file__).parent.parent
    config_example = pkg_dir / "config.example.yaml"
    commands_example = pkg_dir / "commands.example.yaml"

    if not config_file.exists():
        if config_example.exists():
            shutil.copy(config_example, config_file)
        else:
            config_file.write_text(
                f"# voice-input 配置文件\n# 完整说明见: https://github.com/mofanx/voice-input\n\n"
                f"command_file: {commands_file}\n",
                encoding="utf-8",
            )
        # 将 command_file 改写为绝对路径，避免工作目录变化后找不到
        try:
            import yaml
            raw = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
            cf = raw.get("command_file", "")
            if cf and not Path(cf).is_absolute():
                raw["command_file"] = str(config_dir / cf)
                config_file.write_text(
                    yaml.dump(raw, allow_unicode=True, default_flow_style=False),
                    encoding="utf-8",
                )
        except Exception:
            pass
        print(f"[voice-input] 已创建默认配置: {config_file}")

    if not commands_file.exists():
        if commands_example.exists():
            shutil.copy(commands_example, commands_file)
            print(f"[voice-input] 已创建默认命令文件: {commands_file}")

    return config_dir


def build_config(
    cli_args: Optional[dict] = None,
    config_file: Optional[str] = None,
    config_dir: Optional[Path] = None,
) -> AppConfig:
    """三级合并构建最终配置"""
    merged: dict = {}

    # 1. 配置文件
    if config_file:
        merged.update(load_from_yaml(config_file))

    # 2. 环境变量覆盖
    merged.update(load_from_env())

    # 3. CLI 参数覆盖（过滤 None 值）
    if cli_args:
        for k, v in cli_args.items():
            if v is not None:
                merged[k] = v

    fallback_config_dir = config_dir or get_user_config_dir()
    fallback_config_dir.mkdir(parents=True, exist_ok=True)

    # command_file 为空时，自动指向用户配置目录的 commands.yaml
    if not merged.get("command_file"):
        candidate = fallback_config_dir / "commands.yaml"
        if candidate.exists():
            merged["command_file"] = str(candidate)

    # db_path 为空时，自动指向用户配置目录的 voice_input.db
    if not merged.get("db_path"):
        merged["db_path"] = str(fallback_config_dir / "voice_input.db")

    # 类型转换
    coerced = {k: _coerce(k, v) for k, v in merged.items()}

    return AppConfig(**coerced)
