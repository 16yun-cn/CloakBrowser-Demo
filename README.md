# CloakBrowser Demo — 自动化对话 + 验证码自动识别

基于 [CloakBrowser](https://github.com/CloakHQ/CloakBrowser)（隐身指纹浏览器）的自动化 Demo。

**核心功能：**
- 使用隐身 Chromium 打开 (`doubao.com`)
- 自动输入问句并提交
- **自动识别图形验证码**（拖拽式九宫格）并通过 LLM + 拟人化操作解决
- 每次运行生成独立 session 目录，包含截图和 JSON 报告

> CloakBrowser 是一个在 C++ 源码级别修改了 58 处指纹的 Chromium，能通过 Cloudflare Turnstile、reCAPTCHA v3（评分 0.9）、FingerprintJS 等反爬检测。本 Demo 在此基础上增加了验证码自动求解能力。

---

## 目录

- [快速开始（5 分钟）](#快速开始5-分钟)
- [环境要求](#环境要求)
- [安装步骤](#安装步骤)
- [配置说明](#配置说明)
- [运行](#运行)
- [验证码自动求解](#验证码自动求解)
- [产物说明](#产物说明)
- [诊断与调试](#诊断与调试)
- [常见问题](#常见问题)

---

## 快速开始（5 分钟）

```bash
# 1. 克隆项目
git clone <repo-url> && cd CloakBrowser-Demo

# 2. 安装 uv（如果没有）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. 安装依赖（自动创建虚拟环境）
uv sync

# 4. 创建配置文件
cp config.template.toml config.toml

# 5. 编辑 config.toml，填入你的代理信息（必填！）
#    重点修改 [proxy] 部分的 server、username、password

# 6. 运行
make run
```

运行后浏览器窗口会自动打开，导航到豆包，输入预设问句，等待回复，然后截图退出。

---

## 环境要求

| 要求 | 说明 |
|------|------|
| 操作系统 | macOS (arm64/x86_64) 或 Linux (x86_64/arm64) |
| Python | 3.10+（推荐 3.12） |
| 包管理器 | [uv](https://docs.astral.sh/uv/) |
| 代理 | 必须！豆包对国内 IP 会触发验证码；推荐住宅代理 |
| 磁盘空间 | ~500MB（CloakBrowser 二进制 + 依赖） |
| 内存 | 浏览器运行时约 200-300MB |

### 代理要求

豆包 (`doubao.com`) 对数据中心的 IP 会频繁触发验证码。推荐使用**住宅代理**。本 Demo 默认使用亿牛云爬虫代理，配合 [portunnel](https://github.com/16yun-cn/portunnel-realase) 使用：

```bash
# 安装 portunnel
git clone https://github.com/16yun-cn/portunnel-realase
cd portunnel-realase
# 按照 portunnel 文档配置并启动，默认转发到 127.0.0.1:6152
```

其他代理（如 Bright Data、Oxylabs、IPRoyal）也可以直接配置在 `config.toml` 中。

---

## 安装步骤

### 1. 安装 uv

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# 或者用 pip
pip install uv
```

### 2. 克隆项目

```bash
git clone <repo-url>
cd CloakBrowser-Demo
```

### 3. 安装依赖

```bash
uv sync
```

这一步会自动：
- 创建 `.venv` 虚拟环境
- 安装 `cloakbrowser`（本地代码）、`playwright`、`hatchling` 等依赖
- 下载 Playwright 的 Chromium 浏览器依赖（系统级库）

如果下载 Playwright 浏览器依赖时提示缺少系统库：

```bash
# Linux (Debian/Ubuntu)
uv run playwright install-deps chromium

# macOS
# 通常不需要额外操作
```

### 4. 首次运行 — 自动下载 CloakBrowser 二进制

```bash
uv run python -c "from cloakbrowser import ensure_binary; ensure_binary()"
```

CloakBrowser 的隐身 Chromium 二进制（~200MB）会在首次运行时自动下载到 `~/.cloakbrowser/`，后续运行直接使用缓存。

### 5. 创建配置文件

```bash
cp config.template.toml config.toml
```

然后用任意编辑器打开 `config.toml`，填入你的配置（见下一节）。

---

## 配置说明

配置文件 `config.toml` 包含以下段落：

### `[target]` — 目标网站

```toml
[target]
url = "https://www.doubao.com"
```

### `[proxy]` — 代理设置

```toml
[proxy]
server = "http://127.0.0.1:6152"    # 代理地址（亿牛云 portunnel 默认端口）
username = "your-username"           # 代理用户名
password = "your-password"           # 代理密码
enabled = "true"                     # 设为 "false" 关闭代理
```

> **注意：** 填写代理时去掉 `<>` 尖括号。`enabled = "false"` 可用于调试（但豆包在国内 IP 下大概率触发验证码）。

### `[dialog]` — 对话内容

```toml
[dialog]
prompt = "你好，请用一句话介绍你自己。"
```

可以改成任意问句。

### `[captcha]` — 验证码自动求解

```toml
[captcha]
enabled = true                                       # 是否启用验证码求解
llm_server = "http://192.168.2.60:8001"              # LLM 服务器地址（llama.cpp）
llm_model = "qwen3.5-35b-a3b"                        # LLM 模型名称
max_retries = 3                                      # 最大重试次数
bypass_proxy = true                                  # 验证码图片 CDN 绕过代理直连
```

> **LLM 服务器：** 需要在本地或内网运行一个 llama.cpp server（支持视觉的多模态模型）。如果使用其他 LLM API，需修改 `captcha/recognizer.py`。

### `[fingerprint]` — 浏览器指纹

```toml
[fingerprint]
seed = 42069                          # 指纹种子（相同种子 = 相同指纹）
platform = "macos"                    # 操作系统（macos / windows / linux）
brand = "Chrome"                      # 浏览器品牌
brand_version = "146"                 # 浏览器版本号
platform_version = "15.0.0"           # 操作系统版本
gpu_vendor = "Intel Inc."             # GPU 厂商
gpu_renderer = "Intel Iris OpenGL Engine"  # GPU 渲染器
hardware_concurrency = 8              # CPU 核心数
device_memory = 8                     # 设备内存 (GB)
screen_width = 1440                   # 屏幕宽度
screen_height = 900                   # 屏幕高度
timezone = "Asia/Shanghai"            # 时区
locale = "zh-CN"                      # 语言
storage_quota_mb = 5000               # 存储配额
webrtc_ip_mode = "auto"               # WebRTC IP 模式
noise = "false"                       # 禁用画布/WebGL 噪声注入（推荐）
```

> **重要：** `noise = "false"` 可以避免验证码系统检测到画布指纹噪声。`screen_width/height` 需要与你的显示器匹配，避免分辨率不一致被检测。

### `[session]` — 会话设置

```toml
[session]
base_dir = "./.runtime/sessions"     # session 输出根目录
session_name = ""                     # session 名称前缀（留空用时间戳）
headless = false                      # 是否无头模式（true=不显示窗口）
humanize = true                       # 是否启用拟人化鼠标/键盘
navigation_timeout_ms = 90000         # 页面导航超时（毫秒）
response_timeout_ms = 120000          # 回复等待超时（毫秒）
```

---

## 运行

### 基本运行

```bash
make run
```

### 使用自定义配置文件

```bash
make run CONFIG=./my-other-config.toml
```

### 查看最新产物

```bash
make latest     # 最新 session 目录路径
make report     # 最新 JSON 报告内容
make sessions   # 列出所有 session 目录
```

### 编译检查（不实际运行）

```bash
make check
```

### 清理

```bash
make clean-runtime   # 删除所有 session 产物
```

---

## 验证码自动求解

### 工作流程

```
页面加载 → 检测验证码窗口
         → 等待九宫格图片加载（最多 15s）
         → 图片加载失败？→ 点击刷新 → 重新等待
         → 截图 → 发送给 LLM 识别
         → LLM 返回：类别（如"动物"）+ 正确格子位置（如 [0,0],[0,1]...）
         → 计算每个格子的像素坐标
         → 拟人化拖拽（Bézier 曲线鼠标轨迹）
         → 点击提交
         → 验证验证码已消失
```

### LLM 要求

需要运行一个支持视觉（图片输入）的多模态 LLM。推荐方案：

```bash
# 下载 Qwen2.5-VL 模型（支持视觉）
# 启动 llama.cpp server
./llama-server \
  -m qwen2.5-vl-7b-instruct-Q4_K_M.gguf \
  --host 0.0.0.0 --port 8001 \
  -ngl 99
```

项目中的 LLM 调用代码在 `captcha/recognizer.py`，如果使用 OpenAI 兼容 API（如 vLLM、Ollama），只需修改 `_send_to_llm` 函数。

### 诊断工具

如果验证码一直失败，使用诊断脚本：

```bash
# 基础指纹信号检查
uv run python scripts/diag_fingerprint.py noise

# 验证码 API 拦截（看验证码 JS 检查了什么）
uv run python scripts/diag_fingerprint.py intercept
```

详见 `docs/captcha-diagnosis.md`。

---

## 产物说明

每次运行会在 `.runtime/sessions/<时间戳>/` 下生成：

```
.runtime/sessions/20260528-143021/
├── profile/                  # 浏览器持久化 profile
├── doubao-before.png         # 发送前截图
├── doubao-after.png          # 回复后截图
├── captcha-screenshot.png    # 验证码截图（如有）
└── doubao-run.json           # JSON 运行报告
```

### JSON 报告示例

```json
{
  "status": "ok",
  "session_id": "20260528-143021",
  "final_url": "https://www.doubao.com/chat/...",
  "title": "豆包 - AI对话",
  "prompt": "你好，请用一句话介绍你自己。",
  "response_excerpt": "我是豆包，字节跳动开发的AI助手...",
  "duration_seconds": 45.32
}
```

---

## 诊断与调试

### 查看 CloakBrowser 二进制状态

```bash
uv run python -c "from cloakbrowser import binary_info; print(binary_info())"
```

### 测试代理连通性

```bash
curl -x http://127.0.0.1:6152 -I https://www.doubao.com
```

### 关闭代理调试

编辑 `config.toml`：
```toml
[proxy]
enabled = "false"
```

### 手动测试验证码识别

```bash
uv run python scripts/test_captcha_recognizer.py
```

---

## 常见问题

### Q: 运行时提示 "ModuleNotFoundError: No module named 'cloakbrowser'"

```bash
uv sync   # 确保依赖已安装
```

### Q: 浏览器窗口闪退

确保：
- 配置文件 `config.toml` 存在且格式正确
- 代理服务正在运行（如果启用了代理）
- `uv sync` 已执行

### Q: 验证码一直失败

先确认 LLM 服务可用：
```bash
curl http://192.168.2.60:8001/health
```

然后运行诊断：
```bash
uv run python scripts/diag_fingerprint.py noise
```

常见原因：
1. **代理不通** — 验证码 CDN 被阻断
2. **指纹被检测** — 尝试换 `fingerprint.seed` 或改为 `platform = "windows"`
3. **LLM 模型不支持视觉** — 确认是多模态模型

### Q: macOS 上验证码比 Linux 更容易失败

macOS 版 CloakBrowser 只有 26 个 C++ 补丁（vs Linux 58 个），部分指纹信号可能被检测。推荐在 Linux (Docker) 上运行：

```bash
docker run --rm cloakhq/cloakbrowser cloaktest
```

### Q: 如何在 Docker 中运行

```bash
# 构建镜像
docker build -t cloakbrowser-demo .

# 运行（挂载配置）
docker run --rm \
  -v $(pwd)/config.toml:/app/config.toml \
  -v $(pwd)/.runtime:/app/.runtime \
  cloakbrowser-demo
```

---

## 项目结构

```
CloakBrowser-Demo/
├── captcha/                 # 验证码自动求解模块
│   ├── __init__.py          # solve_captcha() 主流程
│   ├── recognizer.py        # LLM 识别
│   └── drag_captcha.py      # DOM 定位 + 拖拽执行
├── scripts/
│   ├── diag_fingerprint.py  # 指纹诊断脚本
│   └── test_captcha_recognizer.py  # 识别器单元测试
├── docs/
│   └── captcha-diagnosis.md # 指纹排查文档
├── config.template.toml     # 配置模板
├── run_doubao.py            # 主程序入口
├── Makefile                 # 常用命令
├── pyproject.toml           # uv 项目配置
└── README.md
```
