"""配置管理 - 支持 YAML 配置文件、环境变量、CLI 参数三级合并"""

import os
import secrets
from dataclasses import dataclass, field
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
    bool_keys = {"require_token", "auto_paste"}
    int_keys = {"port", "history_size", "max_content_length", "workers"}
    list_keys = {"allowed_ips"}

    if key in bool_keys and isinstance(val, str):
        return _parse_bool(val)
    if key in int_keys and isinstance(val, str):
        return int(val)
    if key in list_keys and isinstance(val, str):
        return [s.strip() for s in val.split(",") if s.strip()]
    return val


def build_config(
    cli_args: Optional[dict] = None,
    config_file: Optional[str] = None,
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

    # 类型转换
    coerced = {k: _coerce(k, v) for k, v in merged.items()}

    return AppConfig(**coerced)
