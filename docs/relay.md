# 公网 Relay 转发

适用于手机和桌面端不在同一局域网、桌面端没有公网地址的场景，例如华为云桌面办公环境。

## 架构

```text
手机页面 -> 公网 Relay 服务 -> WebSocket 反连桌面客户端 -> 本地剪贴板/粘贴/命令模式
```

Relay 服务只做转发，不执行剪贴板、键盘或 Shell 操作。桌面端收到转发消息后复用本机 `voice-input` 的完整输入处理逻辑。

## 安装可选依赖

```bash
pip install "voice-input[relay]"
```

源码目录中可以使用：

```bash
pip install -e ".[relay]"
```

## 公网服务器启动 Relay

Ubuntu VPS / Termux 均可运行：

```bash
voice-input-relay --host 0.0.0.0 --port 8090 --token your-relay-token
```

也支持环境变量：

```bash
export VOICE_INPUT_RELAY_TOKEN="your-relay-token"
voice-input-relay --host 0.0.0.0 --port 8090
```

公网接口：

- `GET /`：简化手机页面
- `GET /health`：健康检查
- `GET /relay/health`：Relay 健康检查
- `GET /relay/devices`：查看在线桌面设备
- `POST /relay/input`：发送文本
- `GET /relay/ws`：桌面端 WebSocket 反连

健康检查示例：

```bash
curl https://voice.example.com/health
```

返回示例：

```json
{
  "code": 200,
  "status": "ok",
  "version": "2.2.1",
  "online_devices": 1,
  "pending_requests": 0
}
```

## 桌面端反连

方式一：独立客户端

```bash
voice-input-relay-client \
  --server https://voice.example.com \
  --token your-relay-token \
  --device-id huawei-cloud-desktop
```

方式二：随主服务启动

```bash
voice-input --production \
  --relay-enabled \
  --relay-server-url https://voice.example.com \
  --relay-token your-relay-token \
  --relay-device-id huawei-cloud-desktop
```

也可以写入 `config.yaml`：

```yaml
relay_enabled: true
relay_server_url: "https://voice.example.com"
relay_token: "your-relay-token"
relay_device_id: "huawei-cloud-desktop"
relay_reconnect_interval: 3.0
relay_verify_tls: true
```

## 手机端使用

打开公网 Relay 页面：

```text
https://voice.example.com/
```

填写：

- Relay Token
- 目标设备 ID，单设备可留空
- 动作：`copy` / `paste` / `paste_enter` / `paste_terminal`

也可以打开现有完整手机页面，在“连接设置”中选择“公网转发 Relay”，填写 Relay 地址、Token 和目标设备 ID。

## Nginx 反代示例

```nginx
location / {
    proxy_pass http://127.0.0.1:8090;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

## Ubuntu VPS systemd 示例

创建环境变量文件：

```bash
sudo install -d -m 755 /etc/voice-input
sudo tee /etc/voice-input/relay.env >/dev/null <<'EOF'
VOICE_INPUT_RELAY_TOKEN=your-relay-token
VOICE_INPUT_RELAY_HOST=127.0.0.1
VOICE_INPUT_RELAY_PORT=8090
VOICE_INPUT_RELAY_LOG_LEVEL=info
EOF
```

创建服务文件：

```bash
sudo tee /etc/systemd/system/voice-input-relay.service >/dev/null <<'EOF'
[Unit]
Description=voice-input Relay Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=/etc/voice-input/relay.env
ExecStart=/usr/local/bin/voice-input-relay
Restart=always
RestartSec=3
User=www-data
Group=www-data

[Install]
WantedBy=multi-user.target
EOF
```

启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now voice-input-relay
sudo systemctl status voice-input-relay
```

如果 `voice-input-relay` 不在 `/usr/local/bin`，先确认路径：

```bash
which voice-input-relay
```

然后修改 `ExecStart`。

## Termux 示例

安装：

```bash
pkg update
pkg install python
pip install "voice-input[relay]"
```

启动：

```bash
export VOICE_INPUT_RELAY_TOKEN="your-relay-token"
voice-input-relay --host 0.0.0.0 --port 8090
```

若希望保持后台运行，可使用 `tmux`：

```bash
pkg install tmux
tmux new -s voice-relay
voice-input-relay --host 0.0.0.0 --port 8090 --token your-relay-token
```

Termux 设备通常仍需要路由器端口映射或上层公网入口；如果没有公网入口，更适合作为临时中转或配合内网穿透服务使用。

## 认证

手机端和桌面端使用同一个 Relay Token。只有 Token 匹配时，Relay 才允许注册设备、查看在线设备或转发消息。

HTTP 请求可使用任一请求头：

```text
X-Relay-Token: your-relay-token
X-Auth-Token: your-relay-token
Authorization: Bearer your-relay-token
```
