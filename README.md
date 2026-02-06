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

## 手机端功能

网页端针对手机屏幕优化，支持以下功能：

- **发送模式**：仅复制 / 自动粘贴（Ctrl+V）/ 终端粘贴（Ctrl+Shift+V）
- **自动发送**：开启后，语音输入停顿后自动发送，停顿时间可通过滑块自定义（0.5 - 5 秒）
- **发送后清空**：发送成功后自动清空输入框，方便连续输入
- **发送历史**：默认关闭，开启后支持：
  - 关键词搜索
  - 按日期筛选
  - 单条删除 / 清空全部
  - 导出为 JSON 或 CSV 文件
- **设置持久化**：Token、模式、开关、延迟时间等自动保存到浏览器 localStorage
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

| 路径 | 方法 | 说明 |
|---|---|---|
| `/` | GET | 手机端输入页面 |
| `/status` | GET | 服务状态 |
| `/history` | GET | 发送历史列表 |
| `/history/<id>` | DELETE | 删除单条历史 |
| `/history` | DELETE | 清空全部历史 |
| `/history/export` | GET | 导出历史（?format=json 或 csv） |
| `/input` | POST | 接收文本 |

### POST /input

```json
{
  "text": "要发送的文本",
  "action": "paste",
  "device_id": "phone_web",
  "timestamp": 1700000000000
}
```

**action 取值**：
- `copy` — 仅复制到剪贴板
- `paste` — 复制 + Ctrl+V
- `paste_terminal` — 复制 + Ctrl+Shift+V（Linux）；Windows 下等同 paste
- `type` — 逐字键入

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
