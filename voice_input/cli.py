"""命令行入口 - 支持参数与配置文件"""

import argparse
import asyncio
import logging
import platform
import sys
import threading

from . import __version__
from .config import build_config, find_config_file, init_user_config
from .utils import get_local_ip


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="voice-input",
        description="跨设备语音输入传输系统 - 将手机端语音识别文本传送到电脑",
    )
    p.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("-c", "--config", metavar="FILE", help="YAML 配置文件路径")

    # 网络
    net = p.add_argument_group("网络")
    net.add_argument("-H", "--host", metavar="ADDR", help="监听地址 (默认 0.0.0.0)")
    net.add_argument("-p", "--port", type=int, metavar="PORT", help="监听端口 (默认 8080)")
    net.add_argument(
        "--allowed-ips",
        metavar="CIDR",
        help="IP 白名单，逗号分隔 (如 192.168.0.0/16,10.0.0.0/8)",
    )

    # 安全
    sec = p.add_argument_group("安全")
    sec.add_argument("-t", "--token", metavar="TOKEN", help="鉴权 Token")
    sec.add_argument(
        "--require-token",
        action="store_true",
        default=None,
        help="强制启用 Token 鉴权 (未设 --token 时自动生成)",
    )

    # 行为
    beh = p.add_argument_group("行为")
    beh.add_argument(
        "--no-auto-paste",
        action="store_true",
        default=False,
        help="默认不自动粘贴，仅复制到剪贴板",
    )
    beh.add_argument("--history-size", type=int, metavar="N", help="历史记录条数 (默认 50)")

    relay = p.add_argument_group("公网 Relay 转发")
    relay.add_argument("--relay-enabled", action="store_true", default=None, help="启动桌面端 Relay 反连客户端")
    relay.add_argument("--relay-server-url", metavar="URL", help="Relay 服务地址，例如 https://voice.example.com")
    relay.add_argument("--relay-token", metavar="TOKEN", help="Relay 认证 Token")
    relay.add_argument("--relay-device-id", metavar="ID", help="桌面设备 ID")

    # 生产
    prod = p.add_argument_group("生产部署")
    prod.add_argument(
        "--production",
        action="store_true",
        default=False,
        help="使用 waitress 作为生产 WSGI 服务器",
    )
    prod.add_argument("--workers", type=int, metavar="N", help="WSGI 工作线程数 (默认 4)")
    prod.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error"],
        help="日志级别 (默认 info)",
    )

    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    # 将 argparse 结果转为 config dict（None 表示未指定）
    cli_dict = {}
    if args.host is not None:
        cli_dict["host"] = args.host
    if args.port is not None:
        cli_dict["port"] = args.port
    if args.allowed_ips is not None:
        cli_dict["allowed_ips"] = [s.strip() for s in args.allowed_ips.split(",") if s.strip()]
    if args.token is not None:
        cli_dict["token"] = args.token
    if args.require_token is True:
        cli_dict["require_token"] = True
    if args.no_auto_paste:
        cli_dict["auto_paste"] = False
    if args.history_size is not None:
        cli_dict["history_size"] = args.history_size
    if args.relay_enabled is True:
        cli_dict["relay_enabled"] = True
    if args.relay_server_url is not None:
        cli_dict["relay_server_url"] = args.relay_server_url
    if args.relay_token is not None:
        cli_dict["relay_token"] = args.relay_token
    if args.relay_device_id is not None:
        cli_dict["relay_device_id"] = args.relay_device_id
    if args.workers is not None:
        cli_dict["workers"] = args.workers
    if args.log_level is not None:
        cli_dict["log_level"] = args.log_level

    # 查找配置文件：CLI 指定 > 环境变量 > 当前目录 > 用户配置目录
    config_path = find_config_file(args.config)
    config_dir = None
    if config_path is None:
        # 首次运行，自动生成用户配置
        config_dir = init_user_config()
        config_path = str(config_dir / "config.yaml")
    else:
        from pathlib import Path
        _p = Path(config_path)
        # 若配置文件在用户配置目录，传入 config_dir 以便自动定位 commands.yaml
        from .config import get_user_config_dir
        if _p.parent == get_user_config_dir():
            config_dir = _p.parent

    # 构建配置
    cfg = build_config(cli_args=cli_dict, config_file=config_path, config_dir=config_dir)

    # 配置日志
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    # 创建应用
    from .server import create_app

    app = create_app(cfg)

    if cfg.relay_enabled:
        _start_relay_client(app, cfg)

    # 打印启动信息
    local_ip = get_local_ip()
    banner = f"""
{'=' * 60}
  跨设备语音输入传输系统 v{__version__}
{'=' * 60}
  服务地址:  http://{local_ip}:{cfg.port}
  手机页面:  http://{local_ip}:{cfg.port}/
  状态检查:  http://{local_ip}:{cfg.port}/status
  API 接口:  http://{local_ip}:{cfg.port}/input  (POST)
  历史记录:  http://{local_ip}:{cfg.port}/history"""

    if cfg.token:
        banner += f"\n  Token:     {cfg.token}"
    else:
        banner += "\n  Token:     未启用"

    is_windows = platform.system() == "Windows"
    banner += f"""
{'=' * 60}
  提示: 手机和电脑需在同一局域网"""
    if not is_windows:
        banner += "\n  提示: 自动粘贴功能需要 root/sudo 权限 (Linux)"
    banner += f"\n{'=' * 60}"
    print(banner)

    # 启动服务器
    if args.production:
        _run_production(app, cfg)
    else:
        app.run(host=cfg.host, port=cfg.port, debug=False)


def _run_production(app, cfg):
    """使用 waitress 启动生产服务器"""
    try:
        from waitress import serve

        workers = cfg.workers if cfg.workers > 1 else 4
        print(f"  [waitress] threads={workers}")
        serve(app, host=cfg.host, port=cfg.port, threads=workers)
    except ImportError:
        print(
            "waitress 未安装，回退到 Flask 开发服务器。\n"
            "生产环境请执行: pip install waitress",
            file=sys.stderr,
        )
        app.run(host=cfg.host, port=cfg.port, debug=False)


def _start_relay_client(app, cfg):
    try:
        from .relay_client import RelayClient, default_device_id
    except Exception as e:
        print(f"Relay 客户端不可用: {e}", file=sys.stderr)
        return
    if not cfg.relay_server_url or not cfg.relay_token:
        print("Relay 已启用，但 relay_server_url 或 relay_token 为空", file=sys.stderr)
        return
    device_id = cfg.relay_device_id or default_device_id()

    def runner():
        asyncio.run(RelayClient(
            app,
            cfg.relay_server_url,
            cfg.relay_token,
            device_id,
            cfg.relay_reconnect_interval,
            cfg.relay_verify_tls,
        ).run_forever())

    thread = threading.Thread(target=runner, name="voice-input-relay-client", daemon=True)
    thread.start()
    print(f"  Relay:     已启用 -> {cfg.relay_server_url}")
    print(f"  Device ID: {device_id}")


if __name__ == "__main__":
    main()
