"""工具函数"""

import socket
import logging
import hmac
from ipaddress import ip_address, ip_network


def get_local_ip() -> str:
    """获取本机局域网 IP 地址"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception as e:
        logging.error(f"获取本地IP失败: {e}")
        return "127.0.0.1"


def get_client_ip(req) -> str:
    """从请求中提取客户端真实 IP（支持反向代理）"""
    forwarded_for = req.headers.get("X-Forwarded-For", "").strip()
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return req.remote_addr or "0.0.0.0"


def is_ip_allowed(ip: str, allowed_networks: list) -> bool:
    """检查 IP 地址是否在白名单中"""
    try:
        client_ip = ip_address(ip)
        for network in allowed_networks:
            network = (network or "").strip()
            if not network:
                continue
            if client_ip in ip_network(network, strict=False):
                return True
        return False
    except ValueError:
        return False


def is_token_valid(req, data: dict, expected_token: str, require: bool) -> bool:
    """校验请求中的 token"""
    if not expected_token:
        return not require
    header_token = (req.headers.get("X-Auth-Token") or "").strip()
    query_token = (req.args.get("token") or "").strip()
    body_token = ""
    if isinstance(data, dict):
        body_token = str(data.get("token", "")).strip()
    provided = header_token or query_token or body_token
    return bool(provided) and hmac.compare_digest(provided, expected_token)
