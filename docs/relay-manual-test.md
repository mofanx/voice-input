# Relay 转发模式手动测试与使用说明

本文档用于在正式合并到 `README.md` 前，手动验证 Relay 转发模式是否可用。

适用场景：

- 华为云桌面 / 公司内网 / NAT 后方电脑作为目标电脑。
- Termux + 公网 IP + Nginx 作为中转服务器。
- Ubuntu VPS + Nginx/Caddy 作为中转服务器。
- 手机端仍使用原 `voice-input` 页面，只把「连接设置」里的服务器地址改成公网 Relay 地址。

## 组件说明

Relay 模式包含三部分：

```text
手机浏览器 / PWA
  -> Relay Server（公网中转）
  -> Relay Agent（运行在目标电脑/云桌面）
  -> 本地 voice-input 服务
```

### 1. 本地 voice-input 服务

运行在真正需要接收语音输入、执行粘贴/按键/命令的目标电脑上。

建议只监听本机：

```bash
voice-input -H 127.0.0.1 -p 8080 -t local-token
```

### 2. Relay Agent

运行在目标电脑上，主动连接公网 Relay Server，并把请求转发到本机 `voice-input`。

```bash
voice-input-relay-agent \
  --relay wss://relay.example.com/relay/agent \
  --relay-token agent-token \
  --device default \
  --local http://127.0.0.1:8080 \
  --local-token local-token
```

### 3. Relay Server

运行在公网可访问的服务器上，例如 Ubuntu VPS、家用服务器、Termux。

```bash
voice-input-relay-server \
  --host 127.0.0.1 \
  --port 8787 \
  --client-token client-token \
  --agent-token agent-token
```

通常由 Nginx/Caddy 反代到公网 HTTPS。

## 安装方式

### 普通目标电脑：安装原功能 + Agent

```bash
pip install -e ".[relay-agent]"
```

如果你本地已经是开发仓库，也可以直接在项目根目录运行：

```bash
python -m voice_input.relay.agent --help
```

### 公网中转服务器：只安装 Relay Server 依赖

```bash
pip install -e ".[relay-server]"
```

如果是从 PyPI 安装，后续可以使用：

```bash
pip install "voice-input[relay-server]"
```

### 开发环境：安装全部 Relay 依赖

```bash
pip install -e ".[relay]"
```

## 本机三进程快速测试

适合先在同一台电脑上验证功能闭环。

### 终端 1：启动本地 voice-input

```bash
voice-input -H 127.0.0.1 -p 8080 -t local-token
```

如果使用源码方式：

```bash
python -m voice_input -H 127.0.0.1 -p 8080 -t local-token
```

### 终端 2：启动 Relay Server

```bash
voice-input-relay-server \
  --host 127.0.0.1 \
  --port 8787 \
  --client-token client-token \
  --agent-token agent-token \
  --log-level debug
```

源码方式：

```bash
python -m voice_input.relay.server \
  --host 127.0.0.1 \
  --port 8787 \
  --client-token client-token \
  --agent-token agent-token \
  --log-level debug
```

### 终端 3：启动 Relay Agent

```bash
voice-input-relay-agent \
  --relay ws://127.0.0.1:8787/relay/agent \
  --relay-token agent-token \
  --device default \
  --local http://127.0.0.1:8080 \
  --local-token local-token \
  --log-level debug
```

源码方式：

```bash
python -m voice_input.relay.agent \
  --relay ws://127.0.0.1:8787/relay/agent \
  --relay-token agent-token \
  --device default \
  --local http://127.0.0.1:8080 \
  --local-token local-token \
  --log-level debug
```

### 验证 Relay 健康状态

```bash
curl http://127.0.0.1:8787/relay/health
```

期望返回：

```json
{
  "code": 200,
  "agent_online": true
}
```

### 验证 `/status` 转发

```bash
curl -H "X-Auth-Token: client-token" \
  http://127.0.0.1:8787/status
```

期望返回本地 `voice-input` 的状态信息。

### 验证消息推送

```bash
curl -X POST http://127.0.0.1:8787/message \
  -H "X-Auth-Token: client-token" \
  -H "Content-Type: application/json" \
  -d '{"content":"relay test","source":"manual"}'
```

然后查看消息列表：

```bash
curl -H "X-Auth-Token: client-token" \
  http://127.0.0.1:8787/messages
```

期望能看到 `relay test`。

### 验证发送输入

谨慎测试，因为这会真的触发目标电脑剪贴板/粘贴行为。

建议先使用 `copy`：

```bash
curl -X POST http://127.0.0.1:8787/input \
  -H "X-Auth-Token: client-token" \
  -H "Content-Type: application/json" \
  -d '{"text":"来自 Relay 的测试文本","action":"copy","timestamp":1710000000000}'
```

如果确认无误，再测试 `paste`：

```bash
curl -X POST http://127.0.0.1:8787/input \
  -H "X-Auth-Token: client-token" \
  -H "Content-Type: application/json" \
  -d '{"text":"来自 Relay 的粘贴测试","action":"paste","timestamp":1710000000000}'
```

## 手机端使用方式

第一阶段不做 Relay 管理界面，手机端继续使用原页面。

### 方式 A：继续使用原 PWA / 原页面

打开原 `voice-input` 页面后，在「连接设置」里把服务器地址改成 Relay 地址。

本机测试时：

```text
http://127.0.0.1:8787
```

公网使用时：

```text
https://relay.example.com
```

Token 填写：

```text
client-token
```

之后正常点击「发送」即可。

注意：

- 手机端访问 Relay Server 使用 `client-token`。
- Relay Agent 访问本地 `voice-input` 使用 `local-token`。
- 浏览器地址栏可以打开 `https://relay.example.com/?token=client-token` 获取原页面，但页面内连接设置仍建议确认服务器地址为 `https://relay.example.com`，Token 为 `client-token`。
- 本地 `voice-input` 建议只监听 `127.0.0.1`。Relay Agent 会把请求转成本机访问，不需要把本地服务暴露到公网。

### 方式 B：通过 Relay 代理原页面

如果 Agent 在线，也可以尝试直接打开：

```text
https://relay.example.com/
```

Relay 会把 `GET /` 转发到本地 `voice-input` 的 `/`，返回原页面。

注意：第一阶段此方式只是便利入口。如果 Agent 不在线，页面可能打不开。更稳定的测试方式是使用方式 A。

## Ubuntu VPS + Nginx 部署示例

### 1. VPS 启动 Relay Server

```bash
voice-input-relay-server \
  --host 127.0.0.1 \
  --port 8787 \
  --client-token client-token \
  --agent-token agent-token
```

### 2. Nginx 反代配置

```nginx
server {
    listen 443 ssl http2;
    server_name relay.example.com;

    ssl_certificate /etc/letsencrypt/live/relay.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/relay.example.com/privkey.pem;

    client_max_body_size 10m;

    location /relay/agent {
        proxy_pass http://127.0.0.1:8787;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    location / {
        proxy_pass http://127.0.0.1:8787;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

如果本地 `voice-input` 日志中出现公网 IPv6 或公网客户端 IP 的 `IP未授权访问`，通常说明旧版 Relay Agent 把 `X-Forwarded-For` / `X-Real-IP` 继续转发给了本地服务。更新 Agent 后会剥离这些公网代理头，让本地服务看到来自 `127.0.0.1` 的请求。

### 3. 目标电脑启动 Agent

```bash
voice-input-relay-agent \
  --relay wss://relay.example.com/relay/agent \
  --relay-token agent-token \
  --device default \
  --local http://127.0.0.1:8080 \
  --local-token local-token
```

### 4. 手机端填写

服务器地址：

```text
https://relay.example.com
```

Token：

```text
client-token
```

## Termux + Nginx 部署示例

适用于你已经把 Termux 作为家用服务器使用，并且具备公网 IP 或公网入口。

### 1. Termux 安装依赖

```bash
pkg update
pkg install python
pip install -e ".[relay-server]"
```

如果不是源码目录：

```bash
pip install "voice-input[relay-server]"
```

### 2. Termux 启动 Relay Server

```bash
voice-input-relay-server \
  --host 127.0.0.1 \
  --port 8787 \
  --client-token client-token \
  --agent-token agent-token
```

建议配合：

```bash
termux-wake-lock
```

也可以放到 `tmux` 或 Termux:Boot 中长期运行。

### 3. Nginx 反代

如果 Nginx 跑在同一台 Termux 设备或同一网络主机上，反代到：

```text
http://127.0.0.1:8787
```

Nginx 配置同 Ubuntu VPS 示例，重点是 `/relay/agent` 必须支持 WebSocket Upgrade。

## Caddy 部署示例

Caddy 会自动处理 WebSocket Upgrade：

```caddyfile
relay.example.com {
    reverse_proxy 127.0.0.1:8787
}
```

## 常见问题

### 1. `/relay/health` 返回 `agent_online: false`

说明 Relay Server 正常，但 Agent 没连上。

检查：

- Agent 的 `--relay` 地址是否正确。
- 公网是 `wss://`，本机测试是 `ws://`。
- `--relay-token` 是否和 Server 的 `--agent-token` 一致。
- Nginx 是否正确配置 WebSocket Upgrade。

### 2. 请求返回 `401 UNAUTHORIZED`

说明手机端/客户端 token 错误。

检查：

- 页面 Token 是否填写 `client-token`。
- curl 是否带了：

```bash
-H "X-Auth-Token: client-token"
```

### 3. 请求返回 `503 AGENT_OFFLINE`

说明 Relay Server 没有可用 Agent。

检查 Agent 是否正在运行、是否显示连接成功。

### 4. 请求返回 `502 LOCAL_UNREACHABLE`

说明 Agent 连上了 Relay，但访问本地 `voice-input` 失败。

检查：

- 本地 `voice-input` 是否启动。
- Agent 的 `--local` 是否正确。
- Agent 的 `--local-token` 是否和本地 `voice-input -t` 一致。

### 5. Nginx 下 WebSocket 连接失败

重点检查：

```nginx
proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
proxy_read_timeout 3600s;
proxy_send_timeout 3600s;
```

### 6. 手机页面能打开但发送失败

检查页面「连接设置」中的服务器地址是否为 Relay 公网地址，例如：

```text
https://relay.example.com
```

Token 是否为 Relay Server 的 `client-token`，不是本地 `local-token`。

## Token 区分

建议使用三类 token，不要混淆：

| Token | 用途 | 示例 |
|---|---|---|
| `client-token` | 手机/浏览器访问 Relay Server | 页面 Token 输入框 |
| `agent-token` | Relay Agent 连接 Relay Server | `--relay-token` |
| `local-token` | Agent 访问本地 voice-input | `--local-token` |

## 推荐测试顺序

1. 本机三进程测试。
2. curl 测试 `/relay/health`。
3. curl 测试 `/status`。
4. curl 测试 `/message` 和 `/messages`。
5. curl 测试 `/input` 的 `copy` 动作。
6. 手机页面填写 Relay 地址测试。
7. Nginx/Caddy 反代测试。
8. Termux 或 VPS 实际部署测试。

## 当前限制

第一阶段为单设备 MVP：

- 暂不支持多设备选择。
- 暂不做管理页面。
- 暂不做配对页面。
- 暂不在 Relay Server 保存历史或消息。
- 真实历史和消息仍保存在目标电脑本地 `voice_input.db`。

