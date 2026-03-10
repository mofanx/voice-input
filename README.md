# 跨设备语音输入传输系统

将手机端的语音识别结果，通过局域网实时传送到电脑（Windows / Linux），自动写入剪贴板并可粘贴到当前光标位置。支持任意手机语音输入法（如豆包、讯飞、搜狗、Gboard 等）。

## 工作原理

```
手机（语音输入法）→ 局域网 HTTP → 电脑端服务 → 剪贴板 → 可选自动粘贴
```

手机浏览器打开电脑端服务提供的网页，在文本框里用语音输入法输入文字，点击发送或启用自动发送，文本即刻传到电脑剪贴板并可自动粘贴。

## 平台支持

| 平台 | 仅复制 | 自动粘贴 | 备注 |
|---|---|---|---|
| **Windows** | ✅ | ✅ | 无需管理员权限 |
| **Linux (Xorg)** | ✅ | ✅ | 需要 `sudo` |
| **Linux (Wayland)** | ✅ | ⚠️ 可能受限 | 建议使用「仅复制」模式 |

## 安装

### 方式一：pip 安装（推荐）

```bash
# 安装基础版（仅复制到剪贴板，不含自动粘贴）
pip install .

# 安装完整版（含自动粘贴 + 生产部署 + YAML 配置）
pip install ".[all]"
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

启动后终端会输出：
```
============================================================
  跨设备语音输入传输系统 v2.0.0
============================================================
  服务地址:  http://192.168.1.100:8080
  手机页面:  http://192.168.1.100:8080/
  Token:     未启用
============================================================
```

**手机端操作**：手机浏览器打开「手机页面」地址，在文本框里用语音输入法输入文字，点发送即可。

> **PWA 提示**：Chrome / Edge 浏览器会出现「添加到主屏幕」横幅，点击后可将网页安装为应用，获得全屏、无浏览器工具栏的原生体验。iOS Safari 可点击分享按钮 → 添加到主屏幕。

## 命令行参数

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

## 配置文件

支持 YAML 格式，参见 `config.example.yaml`：

```yaml
port: 8080
allowed_ips:
  - "192.168.0.0/16"
  - "10.0.0.0/8"
token: "your-secret-token"
require_token: true
auto_paste: true
history_size: 50
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
| `VOICE_INPUT_LOG_LEVEL` | 日志级别 |

## PWA 安装

本项目支持 Progressive Web App（PWA），可将网页安装为桌面 / 主屏幕应用，获得类原生体验：

- 全屏运行（无浏览器地址栏）
- 离线可访问（App Shell 由 Service Worker 缓存）
- 主屏幕图标 + 启动画面

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

- **连接设置**：手动设置服务器地址（留空则使用当前页面地址），实时显示连接状态
- **Token 配置**：Token 输入框常驻，方便 PWA 安装后切换服务器时重新配置
- **发送模式**：仅复制 / 自动粘贴（Ctrl+V）/ 终端粘贴（Ctrl+Shift+V）
- **自动发送**：开启后，语音输入停顿后自动发送，停顿时间可通过滑块自定义（0.5 - 5 秒）
- **发送后清空**：发送成功后自动清空输入框，方便连续输入
- **发送后回车**：粘贴完成后自动模拟回车键（开启时自动关闭「自动发送」）
- **恢复剪贴板**：粘贴后自动恢复电脑原有剪贴板内容（仅复制模式下无效）
- **发送历史**：默认关闭，开启后支持：
  - 关键词搜索
  - 按日期筛选
  - 单条删除 / 清空全部
  - 导出为 JSON 或 CSV 文件
- **设置持久化**：服务器地址、Token、模式、开关、延迟时间等自动保存到浏览器 localStorage
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
| `/icon.svg` | GET | 无 | 应用图标 |
| `/history` | GET | ✅ | 发送历史列表 |
| `/history/<id>` | DELETE | ✅ | 删除单条历史 |
| `/history` | DELETE | ✅ | 清空全部历史 |
| `/history/export` | GET | ✅ | 导出历史（?format=json 或 csv） |
| `/input` | POST | ✅ | 接收文本 |

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

### 打包发布

```bash
pip install build
python -m build

# 生成的包在 dist/ 目录
# dist/voice_input-2.0.0-py3-none-any.whl
# dist/voice_input-2.0.0.tar.gz
```

## 项目结构

```
db_voice_input/
├── pyproject.toml          # 打包配置
├── requirements.txt        # 依赖清单
├── README.md               # 本文档
├── config.example.yaml     # 配置文件示例
├── .gitignore              # Git 忽略规则
├── voice_server.py         # 兼容旧入口
└── voice_input/            # Python 包
    ├── __init__.py         # 包信息与版本
    ├── __main__.py         # python -m 入口
    ├── cli.py              # 命令行解析与启动
    ├── config.py           # 配置管理（YAML/环境变量/CLI 三级合并）
    ├── server.py           # Flask 应用与路由
    ├── utils.py            # 工具函数
    └── templates/
        └── index.html      # 手机端 UI（响应式）
```

## License

MIT
