# 跨设备语音输入传输系统

将手机端的语音识别结果，通过局域网实时传送到电脑（Windows / Linux / macOS），自动写入剪贴板并可粘贴到当前光标位置。支持任意手机语音输入法（如豆包、讯飞、搜狗、Gboard 等）。

**v2.2.2 新特性**：命令模式、SQLite 持久化存储、用户配置目录自动初始化、发送历史增强（类型区分/筛选/再发/填入）、消息面板吸底体验。

## 工作原理

```
手机（语音输入法）→ 局域网 HTTP → 电脑端服务 → 剪贴板 → 可选自动粘贴
```

手机浏览器打开电脑端服务提供的网页，在文本框里用语音输入法输入文字，点击发送或启用自动发送，文本即刻传到电脑剪贴板并可自动粘贴。

## 平台支持

| 平台 | 仅复制 | 自动粘贴 | 备注 |
|---|---|---|---|
| **Windows** | ✅ | ✅ | 无需管理员权限 |
| **macOS** | ✅ | ✅ | 无需特殊权限 |
| **Linux (Xorg)** | ✅ | ✅ | 需要 `sudo` |
| **Linux (Wayland)** | ✅ | ⚠️ 可能受限 | 建议使用「仅复制」模式 |

## 安装

### 方式一：pip 安装（推荐）

```bash
# 安装基础版（仅复制到剪贴板，不含自动粘贴）
pip install .

# 安装完整版（含自动粘贴 + 生产部署 + YAML 配置）
pip install ".[all]"

# 安装 Relay Agent（目标电脑/云桌面使用）
pip install ".[relay-agent]"

# 安装 Relay Server（公网中转服务器/Termux/VPS 使用）
pip install ".[relay-server]"
```

### 方式二：直接运行

```bash
pip install -r requirements.txt
```

## 快速开始

```bash
# Windows
voice-input -p 8080

# Linux（自动粘贴需要 root）
sudo voice-input -p 8080

# 指定端口 + Token
voice-input -p 9090 -t my-secret-token

# 使用配置文件
voice-input -c config.yaml

# python -m 方式
python -m voice_input -p 8080

# 兼容旧入口
python voice_server.py -p 8080
```

### 发送消息到手机端

```bash
# 直接发送文本（支持 Markdown）
voice-input-send "你好，这是一条测试消息"

# 从文件发送
voice-input-send -f output.md -s cascade

# 管道输入
echo "## 任务完成" | voice-input-send

# 指定服务器和 Token
voice-input-send "消息" --server http://192.168.1.100:8080 -t $VOICE_INPUT_TOKEN
```

环境变量自动读取：`VOICE_INPUT_TOKEN`（鉴权）、`VOICE_INPUT_SERVER`（服务器地址，默认 http://localhost:8080）

### Relay 公网转发模式（测试中）

Relay 模式用于华为云桌面、公司内网、NAT、Termux 家用服务器、Ubuntu VPS 等非局域网场景。手机端仍使用原页面/PWA，只需要把「连接设置」里的服务器地址从局域网地址改成公网 Relay 地址。

```text
手机浏览器/PWA
  -> Relay Server（公网中转）
  -> Relay Agent（目标电脑主动连接）
  -> 本地 voice-input 服务
```

1. 目标电脑启动本地服务：

```bash
voice-input -H 127.0.0.1 -p 8080 -t local-token
```

2. 公网服务器启动 Relay Server：

```bash
voice-input-relay-server \
  --host 127.0.0.1 \
  --port 8787 \
  --client-token client-token \
  --agent-token agent-token
```

3. 目标电脑启动 Relay Agent：

```bash
voice-input-relay-agent \
  --relay wss://relay.example.com/relay/agent \
  --relay-token agent-token \
  --device default \
  --local http://127.0.0.1:8080 \
  --local-token local-token
```

4. 手机端连接设置：

```text
服务器地址: https://relay.example.com
Token: client-token
```

详细手动测试、Termux + Nginx、Ubuntu VPS + Nginx/Caddy 配置见：`docs/relay-manual-test.md`。

启动后终端会输出：
```
============================================================
  跨设备语音输入传输系统 v2.2.2
============================================================
  服务地址:  http://192.168.1.100:8080
  手机页面:  http://192.168.1.100:8080/
  Token:     未启用
============================================================
```

**手机端操作**：手机浏览器打开「手机页面」地址，在文本框里用语音输入法输入文字，点发送即可。

> **PWA 提示**：Chrome / Edge 浏览器会出现「添加到主屏幕」横幅，点击后可将网页安装为应用，获得全屏、无浏览器工具栏的原生体验。iOS Safari 可点击分享按钮 → 添加到主屏幕。

## 命令行参数

### `voice-input`

```
用法: voice-input [选项]

选项:
  -V, --version           显示版本
  -c, --config FILE       YAML 配置文件路径
  -H, --host ADDR         监听地址 (默认 0.0.0.0)
  -p, --port PORT         监听端口 (默认 8080)
  --allowed-ips CIDR      IP 白名单，逗号分隔
  -t, --token TOKEN       鉴权 Token
  --require-token         强制启用 Token（未设 --token 时自动生成）
  --no-auto-paste         默认仅复制，不自动粘贴
  --history-size N        历史记录条数 (默认 50)
  --production            使用 waitress 生产服务器
  --workers N             工作线程数 (默认 4)
  --log-level LEVEL       日志级别 (debug/info/warning/error)
```

### `voice-input-relay-server`

```text
用法: voice-input-relay-server [选项]

选项:
  --host ADDR             监听地址，默认 127.0.0.1
  --port PORT             监听端口，默认 8787
  --client-token TOKEN    手机端访问 Relay 使用的 token
  --agent-token TOKEN     Agent 注册 Relay 使用的 token
  --default-device ID     默认设备 ID
  --timeout SECONDS       转发请求超时时间
  --log-level LEVEL       日志级别 (debug/info/warning/error)
```

### `voice-input-relay-agent`

```text
用法: voice-input-relay-agent [选项]

选项:
  --relay URL             Relay WebSocket 地址，例如 wss://relay.example.com/relay/agent
  --relay-token TOKEN     Agent 连接 Relay 使用的 token
  --device ID             设备 ID，默认 default
  --local URL             本地 voice-input 地址，默认 http://127.0.0.1:8080
  --local-token TOKEN     本地 voice-input token
  --timeout SECONDS       本地请求超时时间
  --reconnect SECONDS     断线重连间隔
  --log-level LEVEL       日志级别 (debug/info/warning/error)
```

## 配置文件

支持 YAML 格式，参见 `config.example.yaml`：

```yaml
port: 8080
allowed_ips:
  - "192.168.0.0/16"
  - "10.0.0.0/8"
  - "127.0.0.0/8"
  - "localhost"
token: "your-secret-token"
require_token: true
auto_paste: true
history_size: 100
db_path: ""  # 留空则使用用户配置目录下的 voice_input.db

# 命令模式配置
command_mode_enabled: true
command_prefix: "/"
command_file: "commands.yaml"
gauto_path: "gauto"
command_require_confirm_risks: ["shutdown", "reboot", "rm -rf", "kill"]

# Shell 命令模式配置
shell_enabled: true
shell_prefix: ":"
shell_confirm: true

log_level: "info"
```

**优先级**：命令行参数 > 环境变量 > 配置文件 > 默认值

### 环境变量

所有配置都可通过 `VOICE_INPUT_` 前缀的环境变量设置：

| 环境变量 | 说明 |
|---|---|
| `VOICE_INPUT_PORT` | 端口 |
| `VOICE_INPUT_HOST` | 监听地址 |
| `VOICE_INPUT_TOKEN` | Token |
| `VOICE_INPUT_REQUIRE_TOKEN` | 是否强制 Token (`1`/`true`) |
| `VOICE_INPUT_ALLOWED_IPS` | IP 白名单（逗号分隔） |
| `VOICE_INPUT_AUTO_PASTE` | 默认自动粘贴 (`1`/`true`) |
| `VOICE_INPUT_HISTORY_SIZE` | 历史条数 |
| `VOICE_INPUT_DB_PATH` | SQLite 数据库路径 |
| `VOICE_INPUT_COMMAND_MODE_ENABLED` | 启用命令模式 |
| `VOICE_INPUT_COMMAND_PREFIX` | 命令前缀（默认 `/`） |
| `VOICE_INPUT_COMMAND_FILE` | 命令定义文件路径 |
| `VOICE_INPUT_SHELL_ENABLED` | 启用 Shell 命令模式 |
| `VOICE_INPUT_SHELL_PREFIX` | Shell 前缀（默认 `:`） |
| `VOICE_INPUT_LOG_LEVEL` | 日志级别 |

### 用户配置目录

首次启动时自动在用户配置目录创建默认 `config.yaml` 和 `commands.yaml`：

| 系统 | 配置目录 |
|---|---|
| Linux | `~/.config/voice-input/` |
| macOS | `~/Library/Application Support/voice-input/` |
| Windows | `%APPDATA%\voice-input\` |

**配置优先级**：命令行参数 > 环境变量 > 当前目录 `config.yaml` > 用户配置目录 `config.yaml` > 默认值。

**注意**：`sudo` 运行时会自动使用 `SUDO_USER` 对应的真实用户目录，而非 root 目录。

## PWA 安装

本项目支持 Progressive Web App（PWA），可将网页安装为桌面 / 主屏幕应用，获得类原生体验：

- 全屏运行（无浏览器地址栏）
- 离线可访问（App Shell 由 Service Worker 缓存）
- 主屏幕图标 + 启动画面
- 深色 / 浅色模式切换（自动跟随系统主题，也可手动切换）

**广泛兼容性**：服务端自动生成 192×192 和 512×512 PNG 图标（纯 Python，无额外依赖），同时提供 SVG 图标，确保 Android Chrome/Edge、Samsung Internet、iOS Safari 等主流浏览器均可正常安装。

### Android（Chrome / Edge）

1. 手机浏览器访问服务地址，页面顶部出现「添加到主屏幕」横幅，点击安装
2. 或浏览器菜单 → 「添加到主屏幕」/ 「安装应用」

### iOS（Safari）

1. Safari 访问服务地址
2. 点击底部分享按钮（方块+箭头图标）
3. 选择「添加到主屏幕」

> **注意**：PWA 安装需要通过 HTTP（局域网）或 HTTPS 访问，不支持直接打开本地文件。

## 手机端功能

网页端针对手机屏幕优化，支持以下功能：

- **深色 / 浅色模式**：头部🌙/☀️按钮切换，默认跟随系统主题，偏好自动保存
- **连接设置**：手动设置服务器地址（留空则使用当前页面地址），实时显示连接状态
- **Token 配置**：Token 输入框常驻，方便 PWA 安装后切换服务器时重新配置
- **发送模式**：仅复制 / 自动粘贴（Ctrl+V）/ 终端粘贴（Ctrl+Shift+V）
- **自动发送**：开启后，语音输入停顿后自动发送，停顿时间可通过滑块自定义（0.5 - 5 秒）
- **发送后清空**：发送成功后自动清空输入框，方便连续输入
- **发送后回车**：粘贴完成后自动模拟回车键（开启时自动关闭「自动发送」）
- **恢复剪贴板**：粘贴后自动恢复电脑原有剪贴板内容（仅复制模式下无效）
- **发送历史**：默认关闭，开启后支持：
  - 关键词搜索 + 按日期筛选 + 按类型筛选（文本/命令/Shell）
  - 类型区分显示：蓝色 `文本`、绿色 `命令`、橙色 `Shell` 标签
  - 单条操作：填入输入框 / 再次发送 / 复制 / 删除
  - 全选 / 反选 / 删除选中 / 清空全部
  - 游标分页：滚动触底自动加载更多
  - 导出为 JSON 或 CSV 文件
- **命令模式**：输入 `/命令名` 执行预设动作，支持语音控制电脑操作：
  - 动作类型：`key`（按键）、`gauto`（执行脚本）、`shell`（Shell 命令）、`platform_shell`（平台特定命令）
  - 匹配模式：`keyword`（关键词模糊）、`exact`（精确）、`regex`（正则）
  - 自动创建命令配置：`commands.yaml`，首次启动自动生成示例命令
  - 命令输出自动推送到消息面板，实时查看执行结果
- **Shell 命令模式**：输入 `:shell命令` 直接在电脑执行 Shell 命令，输出实时反馈
- **快捷操作**：独立于文本发送的扩展功能，支持：
  - 预设按键：← ↑ ↓ → 、Backspace、Delete、Enter、Tab、Esc、Space、鼠标左键、鼠标右键
  - 修饰键构造：可先选中 `Ctrl` / `Shift` / `Alt`，再点击预设按键，组合为 `ctrl+tab`、`ctrl+shift+enter`、`ctrl+1`、`ctrl+alt+tab` 等
  - 自定义按键 / 组合键（如 `ctrl+c`、`alt+tab`、`shift+enter`）
  - 修饰键也可与自定义输入框内容叠加组合，例如先勾选 `Ctrl` + `Alt`，再在输入框中填写 `tab`，即可发送 `ctrl+alt+tab`
  - 发送后清空：提供独立开关，发送成功后自动清空快捷操作输入框，便于连续发送不同组合键
  - 可配置发送次数（1–100）和发送间隔（50–5000 ms）
- **消息接收**：支持从电脑端（大模型、脚本、API）回传消息到手机端，实现类似对话聊天的体验：
  - 固定高度滚动容器，类聊天应用体验
  - 自动吸底：新消息到达时自动滚动到底部（上翻查看历史时停止吸底）
  - 触顶加载旧消息：滚动到顶部自动加载更早的消息，保持视口位置
  - 自动渲染 Markdown 语法（标题、列表、代码块、表格、链接等）
  - 3 秒自动轮询新消息，新消息徽章提示
  - 关键词搜索 + 日期筛选
  - 批量选择（全选 / 反选）+ 批量删除
  - 单条复制（复制原始 Markdown 源码）
  - 导出为 JSON、CSV 或 Markdown
  - 「↑ 继续发送」按钮快速跳回输入框，方便多轮交互
- **折叠卡片**：连接设置、发送模式、消息接收等卡片均支持折叠/展开，状态自动保存
- **设置持久化**：服务器地址、Token、主题、模式、开关、延迟时间等自动保存到浏览器 localStorage
- **响应式布局**：自适应不同手机屏幕尺寸，支持竖屏与横屏

## 生产部署

### 使用 waitress

```bash
# Windows
voice-input --production --workers 4 -t my-token

# Linux
sudo voice-input --production --workers 4 -t my-token
```

### systemd 服务（Linux）

创建 `/etc/systemd/system/voice-input.service`：

```ini
[Unit]
Description=Voice Input Server
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/voice-input --production -c /etc/voice-input/config.yaml
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now voice-input
sudo systemctl status voice-input
```

## API 接口

| 路径 | 方法 | 鉴权 | 说明 |
|---|---|---|---|
| `/` | GET | 无 | 手机端输入页面 |
| `/status` | GET | 无 | 服务状态 |
| `/manifest.json` | GET | 无 | PWA 清单 |
| `/sw.js` | GET | 无 | Service Worker |
| `/icon.svg` | GET | 无 | 应用图标（SVG） |
| `/icon-192.png` | GET | 无 | 应用图标 192×192 |
| `/icon-512.png` | GET | 无 | 应用图标 512×512 |
| `/history` | GET | ✅ | 发送历史列表（`?limit=20&before_id=xxx` 游标分页） |
| `/history/<id>` | DELETE | ✅ | 删除单条历史 |
| `/history` | DELETE | ✅ | 清空全部历史（body `{"ids":[1,2]}` 批量删除） |
| `/history/export` | GET | ✅ | 导出历史（?format=json 或 csv） |
| `/input` | POST | ✅ | 接收文本/命令/Shell |
| `/key` | POST | ✅ | 发送按键 / 鼠标点击 |
| `/commands` | GET | ✅ | 命令列表 |
| `/commands` | POST | ✅ | 新增命令 |
| `/commands/<id>` | GET | ✅ | 获取命令详情 |
| `/commands/<id>` | PUT | ✅ | 更新命令 |
| `/commands/<id>` | DELETE | ✅ | 删除命令 |
| `/commands/reload` | POST | ✅ | 重新加载命令文件 |
| `/commands/test` | POST | ✅ | 测试命令匹配 |
| `/commands/execute` | POST | ✅ | 执行指定命令 |
| `/message` | POST | ✅ | 推送消息到手机端 |
| `/messages` | GET | ✅ | 消息列表（`?since=xxx` 增量 / `?before_id=xxx` 翻页） |
| `/messages/<id>` | DELETE | ✅ | 删除单条消息 |
| `/messages` | DELETE | ✅ | 批量删除消息 |
| `/messages/export` | GET | ✅ | 导出消息 |

所有接口均支持 CORS（`Access-Control-Allow-Origin: *`），方便 PWA 在跨域场景下访问自定义服务器地址。

### POST /input

```json
{
  "text": "要发送的文本",
  "action": "paste",
  "device_id": "phone_web",
  "timestamp": 1700000000000,
  "restore_clipboard": false,
  "press_enter": false
}
```

**action 取值**：
- `copy` — 仅复制到剪贴板
- `paste` — 复制 + Ctrl+V
- `paste_terminal` — 复制 + Ctrl+Shift+V（Linux）；Windows 下等同 paste
- `type` — 逐字键入

**附加参数**：
- `restore_clipboard`：布尔值，是否在粘贴后恢复电脑原有剪贴板内容（仅 `action` 非 `copy` 时有效）
- `press_enter`：布尔值，是否在粘贴后自动模拟回车键（仅 `action` 非 `copy` 时有效）

**鉴权**：Token 可通过 `X-Auth-Token` Header、`?token=` Query 参数或 Body 中 `token` 字段传递。

### POST /key

```json
{
  "key": "up",
  "count": 1,
  "interval": 100
}
```

**key 取值**：
- 方向键：`up` / `down` / `left` / `right`
- 功能键：`enter` / `tab` / `escape` / `space` / `backspace` / `delete`
- 鼠标：`click`（左键点击）、`right_click`（右键点击），Linux 下使用 `ydotool`
- 组合键：`ctrl+c`、`alt+tab`、`ctrl+shift+t` 等（使用 `keyboard` 库语法）

**常见别名兼容**：
- `windows` / `cmd` / `command` / `meta` / `super` 会自动转换为 `win`（通过 scan code 125 发送，确保 Linux 下可用）
- `ctl` / `control` 会自动转换为 `ctrl`
- `option` / `opt` 会自动转换为 `alt`
- `esc` -> `escape`，`del` -> `delete`，`return` -> `enter`
- 因此你可以直接输入：`win+d`、`cmd+d`、`meta+d`、`ctl+esc`、`option+tab`

**前端组合方式**：
- 可先点击 `Ctrl` / `Shift` / `Alt` / `Win` 修饰键按钮，再点击预设按键
- 也可先选择修饰键，再在自定义输入框中输入 `tab`、`d`、`1`、`enter` 等基础键名
- 前端会自动拼接为标准组合字符串，例如：`win+d`、`ctrl+alt+tab`、`ctrl+1`、`ctrl+shift+enter`

**参数**：
- `count`：执行次数（1–100，默认 1）
- `interval`：每次间隔毫秒数（50–5000，默认 100）

### 消息接收 API

#### 推送消息

```
POST /message
Content-Type: application/json

{
  "content": "消息内容，支持 **Markdown** 语法",
  "source": "cascade"
}
```

- `content`（必填）：消息内容，支持完整 Markdown 语法
- `source`（可选）：来源标识，默认 `"api"`

#### 获取消息列表

```
GET /messages                    ← 最近 50 条消息
GET /messages?since=5            ← ID > 5 的新消息（用于轮询）
GET /messages?before_id=100      ← ID < 100 的更早消息（翻页）
GET /messages?limit=30           ← 指定返回条数
```

#### 删除消息

```
DELETE /messages/<id>      ← 删除单条
DELETE /messages           ← 清空全部
DELETE /messages           ← body {"ids":[1,2,3]} 批量删除
```

#### 导出消息

```
GET /messages/export?format=json
GET /messages/export?format=csv
```

#### 快速示例（curl）

```bash
# 发送 Markdown 消息
curl -X POST http://localhost:8080/message \
  -H "Content-Type: application/json" \
  -d '{"content": "## 任务完成\n\n- [x] 功能A\n- [ ] 功能B", "source": "cascade"}'

# 查看消息
curl http://localhost:8080/messages
```

## 常见问题

### 自动粘贴不生效

- **Linux**：`keyboard` 库需要 root 权限，请用 `sudo` 运行
- **Linux Wayland**：模拟按键可能不稳定，建议切换到 Xorg 会话，或使用「仅复制」模式后手动 Ctrl+V
- **Windows**：通常无需特殊权限，如仍不生效请以管理员身份运行
- 确保发送时电脑端目标输入框处于焦点状态

### 手机连不上

- 确保手机和电脑在同一局域网 / Wi-Fi
- 检查防火墙：
  - Linux：`sudo ufw allow 8080/tcp`
  - Windows：在「Windows Defender 防火墙」中放行对应端口
- 检查 IP 白名单配置是否包含手机所在网段

### PWA 安装后无法连接

- PWA 安装时使用的是安装时的服务器地址（存储在 localStorage）
- 如服务器 IP 变动，打开 PWA 后在「连接设置」中更新服务器地址即可
- 连接状态指示灯：🟡 检测中 / 🟢 已连接 / 🔴 连接失败

### PWA 页面内容未更新

- Service Worker 使用 stale-while-revalidate 策略，页面会在后台自动更新
- 更新完成后页面顶部会弹出提示，下次打开 PWA 即使用新版本
- 也可在浏览器开发者工具 → Application → Service Workers → 点击「Update」强制更新

### 快捷操作的鼠标点击无效

- **Linux**：需要安装 `ydotool`：`sudo apt install ydotool`
- **Linux**：当前实现会通过 `sudo ydotool` 执行点击，请确保当前运行环境允许该命令正常执行
- **Linux Wayland**：不同桌面环境兼容性不同，如无效请确认 `ydotoold` 服务状态和权限配置
- **Windows**：无需额外安装，通过 `ctypes` 直接调用 Win32 API

### 打包发布

```bash
pip install build
python -m build

# 生成的包在 dist/ 目录
# dist/voice_input-2.2.2-py3-none-any.whl
# dist/voice_input-2.2.2.tar.gz
```

## 项目结构

```
db_voice_input/
├── pyproject.toml          # 打包配置
├── requirements.txt        # 依赖清单
├── README.md               # 本文档
├── config.example.yaml     # 配置文件示例
├── commands.example.yaml   # 命令定义示例
├── .gitignore              # Git 忽略规则
├── voice_server.py         # 兼容旧入口
├── .windsurf/workflows/    # Windsurf skill 工作流
│   └── send-message.md     # 消息回传 skill（供大模型调用）
└── voice_input/            # Python 包
    ├── __init__.py         # 包信息与版本
    ├── __main__.py         # python -m 入口
    ├── cli.py              # 命令行解析与启动
    ├── send.py             # 消息发送 CLI（voice-input-send）
    ├── config.py           # 配置管理（YAML/环境变量/CLI 三级合并）
    ├── storage.py          # SQLite 持久化（历史/消息存储）
    ├── commands.py         # 命令模式（匹配/执行）
    ├── server.py           # Flask 应用与路由
    ├── utils.py            # 工具函数
    └── templates/
        └── index.html      # 手机端 UI（响应式 + Markdown 渲染）
```

### 数据存储

- **配置文件**：用户配置目录下的 `config.yaml`（首次启动自动生成）
- **命令定义**：用户配置目录下的 `commands.yaml`（首次启动从示例复制）
- **发送历史 & 消息**：SQLite 数据库 `voice_input.db`（持久化存储，非内存）

## License

MIT
