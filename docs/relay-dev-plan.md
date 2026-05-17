# Relay 转发模式开发计划

本文档用于跟踪公网 Relay 转发模式的开发进度。方案依据：`docs/relay-design.md`。

## 总体目标

在不侵入原有局域网模式的前提下，新增可选 Relay 模块，使手机端可以把原来的局域网服务地址替换为公网 Relay 地址，从而在华为云桌面、公司内网、NAT、Termux 家用服务器、Ubuntu VPS 等非局域网环境中继续使用原有语音输入体验。

核心原则：

- 原 `voice-input` 局域网模式保持不变。
- Relay 功能作为可选模块添加。
- 第一阶段不做管理界面、不做设备控制台、不做配对页面。
- Relay Server 只做 HTTPS/WSS 转发，不执行桌面控制，不保存敏感数据。
- 手机端继续使用原页面，只在「连接设置」中填写公网 Relay 地址。
- Termux 作为 Relay Server 是正式考虑的部署场景之一。

## 进度总览

| 阶段 | 状态 | 目标 |
|---|---|---|
| Phase 0 | ✅ 已完成 | 依赖与模块边界准备 |
| Phase 1 | 🚧 进行中 | 单设备 Relay MVP |
| Phase 2 | ⏳ 未开始 | 稳定性与错误提示 |
| Phase 3 | ⏳ 未开始 | 安全增强 |
| Phase 4 | ⏳ 未开始 | 部署文档与安装体验 |

状态标记：

- ⏳ 未开始
- 🚧 进行中
- ✅ 已完成
- ⛔ 暂缓

## Phase 0：依赖与模块边界准备

目标：先搭好不会影响原功能的模块和依赖结构。

### 任务清单

- [x] 调整 `pyproject.toml` optional dependencies：
  - [x] 新增 `relay-agent`
  - [x] 新增 `relay-server`
  - [x] 新增 `relay`
  - [x] 更新 `all`
- [x] 新增 Relay CLI 入口：
  - [x] `voice-input-relay-agent`
  - [x] `voice-input-relay-server`
- [x] 新增模块目录：
  - [x] `voice_input/relay/__init__.py`
  - [x] `voice_input/relay/protocol.py`
  - [x] `voice_input/relay/agent.py`
  - [x] `voice_input/relay/server.py`
- [x] 确保新增 Relay 模块不被原 `voice-input` 启动路径 import。
- [x] 确保未安装 Relay 依赖时，原有功能仍可正常启动。

### 验收标准

- [x] `pip install .` 后原 `voice-input`、`voice-input-send` 正常。
- [x] 未安装 Relay 依赖时，导入 `voice_input` 不报错。
- [x] Relay CLI 在缺少依赖时给出清晰提示，而不是影响主程序。

## Phase 1：单设备 Relay MVP

目标：实现最小可用的单设备公网转发。

### 任务清单

#### 1. Relay 协议

- [x] 定义 WebSocket 消息格式：
  - [x] `hello`
  - [x] `hello_ok`
  - [x] `request`
  - [x] `response`
  - [x] `ping`
  - [x] `pong`
  - [x] `error`
- [x] 定义错误码：
  - [x] `AGENT_OFFLINE`
  - [x] `REQUEST_TIMEOUT`
  - [x] `LOCAL_UNREACHABLE`
  - [x] `UNAUTHORIZED`
  - [x] `BAD_REQUEST`
- [x] 定义请求 ID 生成与 pending 请求管理规范。

#### 2. Relay Agent

- [x] 支持连接 `wss://relay.example.com/relay/agent`。
- [x] 支持 `device_id`、`relay_token`、`local_base_url`、`local_token` 参数。
- [x] 建连后发送 `hello` 注册。
- [x] 接收 Relay Server 的 `request` 消息。
- [x] 转发请求到本地 `voice-input`：
  - [x] GET
  - [x] POST
  - [x] PUT
  - [x] DELETE
- [x] 自动注入本地 `X-Auth-Token`。
- [x] 返回本地响应状态码、headers、body。
- [x] 支持自动重连。
- [x] 支持请求超时。
- [x] 支持心跳。

#### 3. Relay Server

- [x] 提供 WebSocket 端点 `/relay/agent`。
- [x] 校验 Agent token。
- [x] 维护单设备在线连接。
- [x] 提供通用 HTTP 转发：
  - [x] `GET /{path:path}`
  - [x] `POST /{path:path}`
  - [x] `PUT /{path:path}`
  - [x] `DELETE /{path:path}`
- [x] 支持转发常用路径：
  - [x] `/`
  - [x] `/status`
  - [x] `/input`
  - [x] `/key`
  - [x] `/message`
  - [x] `/messages`
  - [x] `/history`
  - [x] `/commands/*`
- [x] 校验手机端 Relay token。
- [x] Agent 不在线时返回明确错误。
- [x] 请求超时时返回明确错误。
- [x] Relay Server 不落库、不保存敏感请求内容。

#### 4. 第一阶段前端行为

- [x] 不新增 Relay 管理页面。
- [x] 不新增设备选择页面。
- [ ] 确保手机端可继续使用原页面。
- [ ] 确保在原页面「连接设置」填写公网 Relay 地址后，API 请求能正常转发。
- [x] 可选：支持 `GET /` 代理本地原页面，作为便利入口。

### 验收标准

- [x] 本地启动原服务：`voice-input -H 127.0.0.1 -p 8080 -t local-token`。
- [x] 启动 Relay Server：`voice-input-relay-server --host 127.0.0.1 --port 8787 ...`。
- [x] 启动 Relay Agent：`voice-input-relay-agent --relay ws://127.0.0.1:8787/relay/agent ...`。
- [ ] 手机/浏览器把服务器地址设置为 Relay 地址后，可以正常：
  - [ ] 发送文本到电脑。
  - [ ] 自动粘贴。
  - [ ] 发送快捷按键。
  - [ ] 查看历史。
  - [ ] 查看消息。
  - [ ] 使用命令模式。
- [ ] Relay Server 停止或 Agent 断开时，前端得到清晰错误。

## Phase 2：稳定性与错误提示

目标：让 MVP 在真实网络环境下更稳定。

### 任务清单

- [ ] Agent 指数退避重连。
- [ ] Server 清理断开的 Agent 连接。
- [ ] pending 请求超时自动清理。
- [ ] 更清晰的 JSON 错误响应。
- [ ] 支持请求体大小限制。
- [ ] 支持基础健康检查：`GET /relay/health`。
- [ ] 日志分级：info/debug/warning/error。
- [ ] 可选只读状态端点：`GET /relay/status`。

### 验收标准

- [ ] Agent 断网后恢复网络可自动重连。
- [ ] Agent 重启后 Relay Server 自动恢复转发。
- [ ] 大请求和超时请求不会导致 pending 泄漏。
- [ ] Nginx 反代 WebSocket 长连接稳定。

## Phase 3：安全增强

目标：降低公网暴露带来的风险。

### 任务清单

- [ ] Token 分层：
  - [ ] `relay_agent_token`
  - [ ] `relay_client_token`
  - [ ] `local_token`
- [ ] 路径白名单：
  - [ ] `/status`
  - [ ] `/input`
  - [ ] `/key`
  - [ ] `/message`
  - [ ] `/messages`
  - [ ] `/history`
  - [ ] `/commands`
- [ ] 请求方法白名单。
- [ ] 简单 IP 限流或请求频率限制。
- [ ] 公网模式下 Shell/高风险命令额外提醒或配置开关。
- [ ] 审计日志开关：只记录元信息，不记录正文。

### 验收标准

- [ ] 未授权手机请求被拒绝。
- [ ] 未授权 Agent 无法注册。
- [ ] 非白名单路径无法转发。
- [ ] Relay 日志不包含输入文本、命令输出、剪贴板内容。

## Phase 4：部署文档与安装体验

目标：让 Ubuntu VPS、Termux + Nginx、家用服务器都能按文档部署。

### 任务清单

- [ ] README 增加 Relay 模式简短入口。
- [ ] 新增部署文档：
  - [ ] Ubuntu VPS 部署。
  - [ ] Termux + Nginx 部署。
  - [ ] Caddy 部署。
  - [ ] systemd 服务。
- [ ] 提供 Nginx WebSocket 反代配置。
- [ ] 提供 Caddy 配置。
- [ ] 可选：Dockerfile。
- [ ] 优化 Termux 安装体验：
  - [ ] 确认 `voice-input[relay-server]` 安装可行。
  - [ ] 如果基础依赖阻碍 Termux，评估拆分 `keyboard` 到可选依赖。

### 验收标准

- [ ] Ubuntu VPS 可按文档部署成功。
- [ ] Termux + Nginx 可按文档部署成功。
- [ ] 手机通过公网 HTTPS 地址可正常使用原页面和原操作流程。

## 测试计划

### 单元测试

- [ ] Relay 协议消息序列化/反序列化。
- [ ] 错误码生成。
- [ ] pending 请求超时处理。
- [ ] 路径白名单匹配。

### 集成测试

- [x] Relay Server + Agent + 本地 Flask test client。
- [x] `/status` 转发短单元测试（Fake Agent）。
- [ ] `/input` 转发。
- [x] `/messages` GET/POST 转发。
- [ ] `/history` GET/DELETE 转发。
- [ ] `/commands/test` 转发。
- [ ] Agent 断开重连。

### 手工测试

- [x] 本机三进程测试：voice-input + relay-server + relay-agent（`/status`、`/message`、`/messages` 已通过；`/input` 受本机剪贴板后端阻塞影响，留待真实桌面手测）。
- [ ] Nginx 反代测试。
- [ ] Termux Relay Server 测试。
- [ ] Ubuntu VPS Relay Server 测试。
- [ ] 手机 PWA 填写公网 Relay 地址测试。

## 当前决策记录

- [x] Relay 采用 Server + Agent 三段式架构。
- [x] Relay Server 只转发，不执行桌面控制。
- [x] 第一阶段只做单设备。
- [x] 第一阶段不做管理界面。
- [x] 手机端继续使用原页面，通过连接设置填写公网 Relay 地址。
- [x] Termux 作为 Relay Server 是正式支持目标之一。
- [x] Relay 依赖通过 optional dependencies 添加，不进入基础依赖。

## 当前进度

截至当前进度：

- [x] 方案文档完成：`docs/relay-design.md`
- [x] 开发计划完成：`docs/relay-dev-plan.md`
- [x] Phase 0 完成：依赖、CLI 入口、Relay 模块骨架与协议基础。
- [x] Phase 1 主要代码完成：Agent/Server 单设备转发 MVP。
- [x] Phase 1 短测试通过：`/relay/health`、客户端鉴权、Agent 离线错误、WebSocket hello 注册、Fake Agent `/status` 代理闭环。
- [x] Phase 1 本机三进程验证通过：`/status`、`/message`、`/messages`。
- [ ] Phase 1 待验证：真实桌面 `/input` 剪贴板/粘贴测试、原页面公网地址转发测试。

## 下一步建议

优先从 Phase 1 开始：

1. 实现 Relay Agent WebSocket 连接与 hello 注册。
2. 实现 Relay Server `/relay/agent` WebSocket 端点。
3. 实现单设备 pending 请求转发。
4. 打通 `/status`、`/input`、`/messages` 等基础路径。
