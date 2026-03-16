"""CLI tool to send messages to the voice-input message receiving endpoint."""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="voice-input-send",
        description="向语音输入系统的消息接收端口发送消息（支持 Markdown）",
    )
    p.add_argument(
        "content", nargs="?",
        help="消息内容（支持 Markdown）；省略时从 stdin 读取",
    )
    p.add_argument("-f", "--file", metavar="FILE", help="从文件读取消息内容")
    p.add_argument(
        "-s", "--source", default="cli",
        help="消息来源标识 (默认: cli)",
    )
    p.add_argument(
        "--server", default=None,
        help="服务器地址 (默认: http://localhost:8080，可通过 VOICE_INPUT_SERVER 环境变量设置)",
    )
    p.add_argument(
        "-t", "--token", default=None,
        help="鉴权 Token (默认从 VOICE_INPUT_TOKEN 环境变量读取)",
    )
    return p.parse_args(argv)


def send_message(content, server=None, token=None, source="cli"):
    """发送消息到服务端，返回 (success: bool, info: str)"""
    server = (server or os.environ.get("VOICE_INPUT_SERVER", "http://localhost:8080")).rstrip("/")
    token = token or os.environ.get("VOICE_INPUT_TOKEN", "")

    url = f"{server}/message"
    payload = json.dumps({"content": content, "source": source}).encode("utf-8")

    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Auth-Token"] = token

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
            return True, f"id={body.get('id')}, len={len(content)}"
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            err = json.loads(raw)
            return False, f"{e.code} - {err.get('message', raw)}"
        except Exception:
            return False, f"{e.code} - {raw}"
    except urllib.error.URLError as e:
        return False, f"连接失败: {e.reason} (server={server})"
    except Exception as e:
        return False, str(e)


def main(argv=None):
    args = parse_args(argv)

    # Determine content
    if args.file:
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            print(f"读取文件失败: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.content:
        content = args.content
    elif not sys.stdin.isatty():
        content = sys.stdin.read()
    else:
        print("请提供消息内容：通过参数、-f 文件、或 stdin 管道", file=sys.stderr)
        sys.exit(1)

    content = content.strip()
    if not content:
        print("消息内容为空", file=sys.stderr)
        sys.exit(1)

    ok, info = send_message(
        content,
        server=args.server,
        token=args.token,
        source=args.source,
    )
    if ok:
        print(f"✓ 消息已发送 ({info})")
    else:
        print(f"✗ 发送失败: {info}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
