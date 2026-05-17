# 公网 Relay 转发模式设计方案

## 背景与目标

当前项目主要面向局域网使用：手机浏览器访问电脑端 `voice-input` 服务，将语音输入文本通过 HTTP 发送到电脑，再由电脑端完成剪贴板写入、自动粘贴、快捷按键、命令执行、消息回传等操作。

新增场景：当电脑运行在华为云桌面、公司内网、校园网、移动网络、NAT 后方或其他非局域网环境时，手机无法直接访问电脑端局域网地址。希望通过一个公网转发服务实现类似局域网下的体验。

核心目标：

- 手机端操作习惯尽量不变：仍然打开一个地址并使用原有网页。
- 原有本地 `voice-input` 功能不被侵入或破坏。
- 转发能力作为可选模块添加，不强制所有用户安装新依赖。
- 转发服务可以单独部署、单独安装。
- 支持通过 Nginx/Caddy 等常见 Web 服务器反向代理。
- 支持部署在不同服务端作为公网中转，包括 Ubuntu VPS、家用服务器、Termux + 公网 IP + Nginx 等环境。

## 总体结论

推荐采用「公网 Relay Server + 本地 Relay Agent + 原 voice-input 服务」三段式架构。

```text
手机浏览器 / PWA
    |
    | HTTPS
    v
公网 Relay Server
    |
    | WSS 长连接 / RPC
    v
Relay Agent（运行在目标电脑或云桌面）
    |
    | HTTP localhost
    v
原 voice-input 服务
```

不要直接把本地 `voice-input` 暴露到公网。原因是它具备自动粘贴、模拟按键、Shell 命令、命令模式等高权限能力，直接暴露公网风险过高。

Relay Agent 由内网/云桌面主动连接公网 Relay Server，可以绕过 NAT、云桌面入站限制和无公网 IP 的问题。

## 模块边界设计

Relay 功能应作为完全可选模块，避免侵入原有功能。

### 原有核心模块保持不变

原有命令保持：

```bash
voice-input
voice-input-send
```

原有 Flask 服务、手机页面、局域网模式、SQLite 历史、消息面板、命令模式都继续独立工作。

Relay 只通过本地 HTTP API 调用原服务，例如：

```text
http://127.0.0.1:8080/input
http://127.0.0.1:8080/key
http://127.0.0.1:8080/messages
http://127.0.0.1:8080/history
http://127.0.0.1:8080/commands/*
```

这样即使 Relay 代码出错，也不会影响局域网模式。

### 新增模块建议

建议新增文件：

```text
voice_input/
  relay_protocol.py      # Relay RPC 协议、消息格式、错误码
  relay_agent.py         # 本地 Agent：连接公网 Relay，转发到本地 voice-input
  relay_server.py        # 公网 Relay Server：接收手机请求，转发给 Agent
```

可选拆分：

```text
voice_input/relay/
  __init__.py
  protocol.py
  agent.py
  server.py
```

更推荐第二种包目录结构，便于未来扩展。

### 新增命令建议

```toml
[project.scripts]
voice-input = "voice_input.cli:main"
voice-input-send = "voice_input.send:main"
voice-input-relay-agent = "voice_input.relay.agent:main"
voice-input-relay-server = "voice_input.relay.server:main"
```

Relay 命令是可选功能入口，不改变原命令行为。

## 依赖与安装策略

当前 `pyproject.toml` 的基础依赖是：

```toml
dependencies = [
    "flask>=2.2",
    "pyclip>=0.7",
    "keyboard>=0.13",
]

[project.optional-dependencies]
production = ["waitress>=2.1"]
config = ["pyyaml>=6.0"]
all = ["waitress>=2.1", "pyyaml>=6.0"]
```

Relay 不应加入基础依赖，否则会让普通局域网用户额外安装 WebSocket/ASGI 相关包，影响安装速度和兼容性。

### 推荐 optional dependencies

建议改成：

```toml
[project.optional-dependencies]
production = ["waitress>=2.1"]
config = ["pyyaml>=6.0"]
relay-agent = [
    "httpx>=0.26",
    "websockets>=12.0",
]
relay-server = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "websockets>=12.0",
]
relay = [
    "httpx>=0.26",
    "websockets>=12.0",
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
]
all = [
    "waitress>=2.1",
    "pyyaml>=6.0",
    "httpx>=0.26",
    "websockets>=12.0",
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
]
```

### 安装方式设计

普通局域网用户：

```bash
pip install voice-input
```

只安装 Agent 的用户，例如华为云桌面内运行：

```bash
pip install "voice-input[relay-agent]"
```

只部署公网 Relay Server 的云服务器：

```bash
pip install "voice-input[relay-server]"
```

单机开发或全部功能：

```bash
pip install "voice-input[all]"
```

### 是否需要单独包

短期不建议拆成多个 PyPI 包。理由：

- 当前项目体量还不大。
- optional dependencies 已经能解决安装体积问题。
- 单仓库更容易保持协议和版本一致。

长期如果 Relay Server 成为独立服务，可考虑拆分：

```text
voice-input            # 原核心功能 + agent
voice-input-relay      # relay server 独立包
```

但第一阶段不建议过早拆包。

## Termux 作为 Relay Server 的定位

Termux 在本方案中的优先定位不是运行完整桌面控制端，也不是主要作为 Agent，而是可以作为 **Relay Server / 中转服务** 来使用。

实际场景示例：

```text
手机浏览器
  -> 公网域名 / 公网 IP
  -> 家中 Nginx
  -> Termux 上运行的 voice-input-relay-server
  -> 华为云桌面 / Ubuntu / Windows 上的 relay-agent
  -> 目标机器本地 voice-input
```

这种定位是合理的，尤其当 Termux 设备已经具备以下条件时：

- 有公网 IP 或可被公网访问的入口。
- 已运行 Nginx/Caddy 等反向代理。
- 可以长期保持在线。
- 可以通过 `tmux`、`termux-wake-lock`、Termux:Boot 等方式提升后台稳定性。

因此，Relay Server 应设计为可部署在多种服务端环境：

- Ubuntu VPS。
- 家用 Linux 服务器。
- Termux 设备。
- 其他可运行 Python ASGI 服务的主机。

Termux 作为 Relay Server 时只做公网 HTTPS/WSS 转发，不负责剪贴板、按键模拟或 Shell 执行，因此不受 Android 对全局键盘和剪贴板权限限制的主要影响。

### Termux 运行完整 voice-input

不推荐作为主要目标。

原因：

- `keyboard` 在 Android/Termux 中通常不能正常模拟系统按键。
- 剪贴板、自动粘贴、全局键盘事件受 Android 权限限制。
- 原项目目标是控制桌面系统，不是控制手机本机。

因此，Termux 不应作为完整 `voice-input` 桌面控制端的主要支持对象。

### Termux 运行 Relay Server

推荐作为可支持部署方式之一。

部署形态：

```text
Nginx/Caddy -> voice-input-relay-server -> WebSocket Agent 连接池
```

注意事项：

- Termux 设备需要尽量保持常驻运行。
- Android 后台限制可能影响长期稳定性，需要配合 `termux-wake-lock`、电池优化白名单、前台会话或 Termux:Boot。
- 建议由 Nginx/Caddy 负责 HTTPS 证书和公网入口，Termux 内部 Relay Server 只监听 `127.0.0.1:8787`。
- Relay Server 不保存敏感数据，Termux 设备丢失或重启时只影响在线连接，不应丢失历史记录。

### Termux 运行 Relay Agent

可作为有限支持，但不是主要目标。

如果 Termux 中的 Agent 只是把 Relay 请求转发到某个可访问的本地/内网 HTTP 服务，则理论上可行。但如果 Termux 同时运行原 `voice-input`，自动粘贴、按键模拟等能力仍然受限。

### Termux 安装依赖建议

Termux 作为 Relay Server 时应只安装 Server 依赖：

```bash
pip install "voice-input[relay-server]"
```

当前项目基础依赖包含 `keyboard`，这对 Termux 并不理想。为了让 Termux Server 安装更干净，未来可以进一步拆分基础依赖，把桌面控制相关依赖移到可选项：

```toml
dependencies = [
    "flask>=2.2",
    "pyclip>=0.7",
]

[project.optional-dependencies]
input-control = ["keyboard>=0.13"]
```

但这会影响现有安装假设，需要谨慎迁移。

第一阶段可以先保持基础依赖不变，但 Relay Server 代码本身不应 import `keyboard`、`pyclip` 等桌面控制依赖，避免运行期受影响。后续再优化 packaging，让 `voice-input[relay-server]` 在 Termux 中更轻量。

## Nginx 反向代理兼容性

Relay Server 必须支持 WebSocket，因此 Nginx 需要正确转发 Upgrade 头。

### 推荐路径

```text
https://relay.example.com/              # 手机网页和 HTTP API
https://relay.example.com/d/{device}/   # 多设备访问入口
wss://relay.example.com/relay/agent     # Agent WebSocket
```

### Nginx 示例配置

```nginx
server {
    listen 443 ssl http2;
    server_name relay.example.com;

    ssl_certificate /etc/letsencrypt/live/relay.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/relay.example.com/privkey.pem;

    client_max_body_size 10m;

    location / {
        proxy_pass http://127.0.0.1:8787;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

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
}
```

### Caddy 示例配置

```caddyfile
relay.example.com {
    reverse_proxy 127.0.0.1:8787
}
```

Caddy 默认支持 WebSocket，配置更简单。

## Relay 协议设计

Relay Server 和 Agent 之间建议使用 WebSocket 上的 JSON-RPC 风格协议。

### Agent 注册

Agent 建连后发送：

```json
{
  "type": "hello",
  "protocol": 1,
  "device_id": "huawei-desktop",
  "token": "relay-agent-token",
  "local_base_url": "http://127.0.0.1:8080",
  "capabilities": ["http-proxy", "stream-output"]
}
```

Server 返回：

```json
{
  "type": "hello_ok",
  "device_id": "huawei-desktop",
  "server_time": 1710000000000
}
```

### HTTP 转发请求

Relay Server 收到手机端请求后，发送给 Agent：

```json
{
  "type": "request",
  "id": "req_abc123",
  "method": "POST",
  "path": "/input",
  "query": "",
  "headers": {
    "content-type": "application/json"
  },
  "body": {
    "text": "你好",
    "action": "paste"
  },
  "timeout_ms": 30000
}
```

Agent 转发本地服务并返回：

```json
{
  "type": "response",
  "id": "req_abc123",
  "status": 200,
  "headers": {
    "content-type": "application/json"
  },
  "body": {
    "code": 200,
    "message": "ok"
  }
}
```

### 错误响应

```json
{
  "type": "response",
  "id": "req_abc123",
  "status": 502,
  "error": {
    "code": "LOCAL_UNREACHABLE",
    "message": "local voice-input service is not reachable"
  }
}
```

### 心跳

```json
{"type": "ping", "ts": 1710000000000}
{"type": "pong", "ts": 1710000000000}
```

## 路由设计

### 单设备模式

适合个人用户。

```text
https://relay.example.com/
```

如果只有一个 Agent 在线，Relay 自动把所有请求转发给该 Agent。

### 多设备模式

适合多个云桌面/电脑。

```text
https://relay.example.com/d/huawei-desktop/
https://relay.example.com/d/home-pc/
```

API 路由：

```text
POST /d/{device_id}/input
GET  /d/{device_id}/messages
GET  /d/{device_id}/history
POST /d/{device_id}/key
```

### 兼容原前端路径

为了最大限度复用原前端，Relay 可以在返回 `index.html` 时注入或改写 base path。

更简单的第一版做法：

- 单设备模式下完全保留原路径 `/input`、`/messages` 等。
- 多设备模式作为第二阶段实现。

## 前端策略

### 第一阶段：无管理界面，纯透明转发

第一阶段不要做任何 Relay 管理界面，也不要做设备控制台、配对页面或壳页面。

Relay Server 的职责只有一个：**透明转发**。

用户仍然使用原来的 `voice-input` 页面。区别只是把页面里的服务器地址从局域网地址换成公网转发地址：

```text
原局域网地址：
http://192.168.1.100:8080

公网转发地址：
https://relay.example.com
```

如果使用 PWA，也仍然可以安装原页面；页面内的连接设置继续填写 Relay 公网地址即可。

Relay 不维护单独前端，而是把请求透明转发给 Agent，再由 Agent 转发到本地 `voice-input` 服务。

对于页面入口可以采用两种简单方式：

1. **Relay 代理原页面**：手机访问 `https://relay.example.com/`，Relay 把 `GET /` 转发到本地 `voice-input` 的 `/`，返回原始页面。
2. **用户直接使用已有页面/PWA**：在原页面「连接设置」里把服务器地址改为 `https://relay.example.com`。

第一阶段优先保证第 2 种方式稳定可用，第 1 种作为便利入口。

优点：

- 前端零分叉。
- 原操作习惯最大程度保留。
- 原有 PWA、消息面板、历史面板都继续使用。
- 不需要实现任何 Relay UI。
- 不需要在 Relay 端维护前端状态。

缺点：

- 如果依赖 Relay 代理 `GET /`，Agent 不在线时页面打不开。
- 如果使用已有页面/PWA，只要页面已打开或已安装，即使 Agent 临时离线，也可以显示连接失败并等待恢复。
- 静态资源和页面代理属于便利功能，不应成为第一阶段核心复杂度来源。

### 第二阶段：可选状态页，而不是管理界面

第二阶段如有需要，可以增加一个非常轻量的只读状态页，但仍不建议做复杂管理界面。

可选状态页只显示：

- 显示设备在线状态。
- 显示 Relay 服务健康状态。
- 显示当前默认设备。

不在 Relay 端做：

- 命令管理。
- 历史管理。
- 消息管理。
- Shell 执行界面。
- 复杂账号系统。

这些功能继续留在原 `voice-input` 页面和本地服务中。

## 安全设计

公网 Relay 场景必须比局域网更谨慎。

### Token 分层

建议至少两类 token：

```text
relay_agent_token    # Agent 连接 Relay 使用
relay_client_token   # 手机访问 Relay 使用
local_token          # Agent 访问本地 voice-input 使用
```

不要把 `local_token` 暴露给手机端。

Agent 在转发本地请求时自动注入本地 token：

```http
X-Auth-Token: local_token
```

### 本地服务绑定 localhost

Relay 模式下建议启动本地服务：

```bash
voice-input -H 127.0.0.1 -p 8080 -t local-token
```

不要把原服务监听到公网网卡。

### Relay 不落库敏感内容

Relay Server 默认只维护：

- 在线设备表
- pending 请求表
- 最小访问日志

不保存：

- 输入文本
- 剪贴板内容
- 命令输出
- 历史记录
- 消息正文

历史和消息仍然保存在本地 `voice_input.db`。

### 高风险能力保护

公网模式建议默认更保守：

- Shell 模式默认关闭，或必须显式开启。
- 高风险命令二次确认。
- Agent 可设置允许转发的路径白名单。

示例白名单：

```yaml
relay_allowed_paths:
  - /status
  - /input
  - /key
  - /message
  - /messages
  - /history
  - /commands
```

### 请求限制

Relay Server 应支持：

- 单请求超时。
- 单设备最大并发请求数。
- 请求体大小限制。
- IP 简单限流。

## 配置设计

### Agent 配置

```yaml
relay_agent:
  enabled: true
  relay_url: "wss://relay.example.com/relay/agent"
  relay_token: "agent-token"
  device_id: "huawei-desktop"
  local_base_url: "http://127.0.0.1:8080"
  local_token: "local-token"
  reconnect_interval: 3
  request_timeout: 30
```

### Server 配置

```yaml
relay_server:
  host: "127.0.0.1"
  port: 8787
  client_token: "phone-access-token"
  agent_tokens:
    huawei-desktop: "agent-token"
  default_device: "huawei-desktop"
  request_timeout: 30
  max_body_size: 10485760
```

### CLI 示例

启动本地服务：

```bash
voice-input -H 127.0.0.1 -p 8080 -t local-token
```

启动 Agent：

```bash
voice-input-relay-agent \
  --relay wss://relay.example.com/relay/agent \
  --relay-token agent-token \
  --device huawei-desktop \
  --local http://127.0.0.1:8080 \
  --local-token local-token
```

启动 Relay Server：

```bash
voice-input-relay-server \
  --host 127.0.0.1 \
  --port 8787 \
  --client-token phone-access-token
```

手机访问：

```text
https://relay.example.com/?token=phone-access-token
```

或在页面 Token 输入框中填写 `phone-access-token`。

## 兼容性注意事项

### Python 版本

当前项目要求 `>=3.8`。Relay 依赖应尽量选择兼容 Python 3.8 的版本。

需要注意：

- 新版 FastAPI/Starlette/httpx 未来可能提升最低 Python 版本。
- 可以在实现时设置较宽但安全的版本范围。

建议第一版：

```toml
fastapi>=0.100,<1
uvicorn[standard]>=0.23,<1
httpx>=0.24,<1
websockets>=11,<16
```

### Android / Termux

- Relay Server 逻辑应避免依赖 `keyboard`、`pyclip`。
- Termux 是 Relay Server 的可支持部署环境之一，适合已有公网 IP 和 Nginx/Caddy 的场景。
- 由于项目基础依赖当前包含 `keyboard`，Termux 安装可能仍受影响；长期可考虑拆分桌面控制依赖，让 `relay-server` 安装更轻。
- Termux 运行完整桌面控制端仍不作为主要目标。

### Windows

Agent 使用 WebSocket + HTTP 转发，Windows 兼容性较好。

### Linux / 云桌面

建议本地 `voice-input` 监听 `127.0.0.1`，Agent 与本地服务同机运行。

### macOS

Agent 层兼容性较好；本地自动粘贴能力以原项目支持情况为准。

## 实施路线

### Phase 1：单设备 Relay MVP

目标：最小可用，不改原核心逻辑。

范围：

- 新增 `voice_input/relay/protocol.py`
- 新增 `voice_input/relay/agent.py`
- 新增 `voice_input/relay/server.py`
- 新增 CLI：`voice-input-relay-agent`
- 新增 CLI：`voice-input-relay-server`
- 支持单设备在线。
- 支持通用 HTTP 方法转发：GET/POST/PUT/DELETE。
- 支持 `/`、`/input`、`/key`、`/message`、`/messages`、`/history`、`/commands/*`。
- 支持 Nginx/Caddy 反代。
- Relay 不落库。
- 不做管理界面、不做设备控制台、不做配对页面。
- 手机端继续使用原页面，只需要把连接设置里的服务器地址改成 Relay 公网地址。

### Phase 2：多设备与体验增强

- 支持 `/d/{device_id}`。
- 可选只读状态页显示设备在线状态。
- Agent 自动重连状态显示。
- 更清晰的错误提示。

### Phase 3：安全增强

- 配对码机制。
- 请求路径白名单。
- 请求限流。
- 风险命令公网模式额外确认。
- 审计日志开关。

### Phase 4：安装体验优化

- 拆分更细 optional dependencies。
- 改善 Termux relay-server 安装体验。
- 提供 Dockerfile。
- 提供 systemd 服务样例。
- 提供 Nginx/Caddy 文档。

## 不推荐方案对比

### 直接暴露本地 voice-input 到公网

不推荐。

缺点：

- 安全风险高。
- 云桌面/NAT 常常无法暴露端口。
- HTTPS、鉴权、限流都需要额外配置。

### 只使用 Tailscale/Zerotier

适合个人快速使用，但不适合作为项目内置能力。

优点：

- 几乎不用开发。
- 安全性较好。

缺点：

- 手机需要额外安装客户端。
- 不符合「只把地址换成公网地址」的体验。
- 对非技术用户不够直接。

### Relay Server 直接执行粘贴/命令

不推荐。

Relay Server 应只转发，不应该拥有桌面控制能力。桌面控制必须留在本地目标机器。

## 最终推荐

采用模块化 Relay 方案：

```text
voice-input                    # 原功能，默认安装，默认局域网模式
voice-input[relay-agent]       # 只安装本地 Agent 所需依赖
voice-input[relay-server]      # 只安装公网 Relay Server 所需依赖
voice-input[relay]             # 安装 Relay Agent + Server 全部依赖
voice-input[all]               # 安装所有功能
```

第一版只实现单设备 Relay MVP，并保持以下原则：

- 不修改原 `/input`、`/key`、`/history`、`/messages` 等核心路由语义。
- Relay Agent 只作为本地 HTTP 代理调用原服务。
- Relay Server 只做公网 HTTPS/WSS 转发，不保存敏感数据。
- 基础安装不增加 Relay 依赖。
- Nginx/Caddy 反代作为正式支持场景。
- Termux 作为 Relay Server 是可支持部署场景之一，尤其适合已有公网 IP 和 Nginx 的家用服务器环境。
- Termux 不作为完整桌面控制端的主要目标。
- 第一阶段不做 Relay 管理界面；用户继续在原页面填写公网 Relay 地址。

这样可以最大限度满足非局域网使用需求，同时保持项目原有功能稳定、安装轻量、模块边界清晰。
