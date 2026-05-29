# CAPTCHA 指纹诊断报告

## 测试环境

| 项目 | 值 |
|------|-----|
| 机器 | macOS arm64 (Apple Silicon) |
| CloakBrowser 二进制 | v145.0.7632.109.2 (Chromium 145) |
| 最新可用版本 | v146.0.7680.177.5 |
| macOS 补丁数 | 26 个 (vs Linux/Windows 58 个) |
| LLM 服务器 | llama.cpp @ 192.168.2.60:8001 (qwen3.5-35b-a3b) |
| 代理 | 127.0.0.1:6152 (portunnel) — 测试中不可用 |
| 目标站点 | https://www.doubao.com |

## 问题描述

访问 doubao.com，提交聊天内容后触发图形验证码（拖拽式九宫格）。验证码图片**短暂出现后消失**，显示"图片加载失败，请刷新重试[5202]"。

`config.toml` 中已配置 `noise = "false"`，问题依旧。

## macOS 测试结果

### 基础指纹信号 — ✅ 正常

```
navigator.webdriver        = false          ✅
navigator.plugins          = 5 个           ✅
screen == innerSize        = 1440x900       ✅
window.chrome              = object         ✅
WebGL VENDOR               = Intel Inc.     ✅
WebGL RENDERER             = Intel Iris     ✅
AudioContext.sampleRate    = 48000          ✅
timezone                   = Asia/Shanghai  ✅
```

### Canvas 指纹一致性测试

| 测试 | 参数 | canvas hash |
|------|------|-------------|
| noise=false, seed=42069 | 启动1 | -1363115548 |
| noise=true,  seed=42069 | 启动2 | -1363115548 |
| noise=false, seed=42069 | 启动3 | -1363115548 |

结论：
- `--fingerprint-noise=false` 和 `true` 产生相同 canvas hash — **噪声开关在 macOS v145 上无效果**
- 相同 seed 的 hash 一致 — 指纹是确定性的

### 验证服务连接 — ❌ 失败

即使绕过代理直连，浏览器仍无法访问字节跳动验证服务：

```
mon.zijieapi.com  → net::ERR_CONNECTION_CLOSED
mcs.zijieapi.com  → net::ERR_CONNECTION_CLOSED
vcs.zijieapi.com  → net::ERR_CONNECTION_CLOSED
```

注意：Python `urllib` 直连这些域名**可以成功**，说明是 CloakBrowser 二进制的网络栈问题，不是 DNS/防火墙问题。可能原因：
- CloakBrowser 的 TLS 配置与系统不一致
- 二进制的证书存储路径问题
- macOS 二进制特有的网络层 bug

### 验证码 JS API 拦截

未拦截到任何 canvas/WebGL/Audio API 调用 — 验证码 JS 在初始化阶段就失败了（config 服务不可达），指纹检测 JS 根本没执行。

## 需要在 Linux 上验证的假设

### 假设 1：macOS 26 个补丁不够 (概率最高)

macOS 二进制只有 26 个 C++ 级补丁，Linux 有 58 个。doubao 验证码系统可能检测到 macOS 版本未修补的某个信号。

**验证方式：**
```bash
# 在 Linux 上运行诊断
uv run --with cloakbrowser python scripts/diag_fingerprint.py all
```

对比 Linux 上的行为：
- 如果 Linux 上图片正常加载不消失 → 确认是 macOS 补丁不足
- 如果 Linux 上也消失 → 问题不在补丁数量，继续排查

### 假设 2：TLS 指纹不一致

Chromium 的 TLS 握手特征（JA3/JA4）可能与真实 Chrome 不同，验证码服务端据此拒绝。

**验证方式：**
```bash
# 在 Linux 上用 tcpdump 抓包对比 CloakBrowser vs 真实 Chrome
tcpdump -i any -w captcha-tls.pcap host zijieapi.com
```

### 假设 3：Canvas/WebGL 噪声模式被 ML 检测

即使 `noise=false`，如果底层仍然注入了某种噪声模式（肉眼不可见但 ML 可检测），验证码会判定为篡改。

**验证方式：**
```bash
# 拦截测试会记录所有 canvas.toDataURL / webgl.getParameter 调用
uv run --with cloakbrowser python scripts/diag_fingerprint.py intercept
```

## Linux 测试清单

### 前置准备

```bash
# 1. 安装依赖
pip install cloakbrowser playwright
playwright install-deps chromium

# 2. 确认二进制版本
python -c "from cloakbrowser import binary_info; print(binary_info())"
# 期望看到: version: 146.x, platform: linux-x64

# 3. 准备代理（portunnel 或其他）
# 确保 127.0.0.1:6152 或你配置的代理端口可访问
# 用 curl 验证: curl -x http://127.0.0.1:6152 -I https://www.doubao.com

# 4. 复制配置文件
cp config.template.toml config.toml
# 编辑 config.toml，填入你的代理信息和指纹参数
```

### 配置文件关键设置

```toml
[proxy]
enabled = "true"
server = "http://127.0.0.1:6152"  # 你的代理地址
username = "your-user"
password = "your-pass"

[captcha]
enabled = true
llm_server = "http://192.168.2.60:8001"  # 或你的 LLM 服务器
llm_model = "qwen3.5-35b-a3b"
max_retries = 3
bypass_proxy = true  # CAPTCHA 验证服务绕过代理直连

[fingerprint]
seed = 42069
platform = "linux"        # Linux 上改为 linux
brand = "Chrome"
brand_version = "146"
# ... 其他指纹参数保持不变
noise = "false"
```

### 逐项测试

```bash
# 测试 1: 基础指纹信号检查
uv run --with cloakbrowser python scripts/diag_fingerprint.py noise
# 检查：webdriver=false, plugins=5+, screen==inner

# 测试 2: 验证码 DOM 监控（关键测试！)
# 这个测试会导航→输入→提交→监控验证码状态 25 秒
# 观察输出中的 "loaded" 数量和 "err" 状态

# 测试 3: 噪声注入对比
uv run --with cloakbrowser python scripts/diag_fingerprint.py noise-true
# 对比 noise=false 和 noise=true 的 canvas hash 是否不同

# 测试 4: 原生 Chromium 对比
uv run --with cloakbrowser python scripts/diag_fingerprint.py stock
# 需要额外: pip install playwright
# 对比无隐身补丁的 Chromium 是否表现不同

# 测试 5: API 拦截
uv run --with cloakbrowser python scripts/diag_fingerprint.py intercept
# 查看验证码 JS 调用了哪些指纹 API
```

### 判断标准

| 观察 | 含义 |
|------|------|
| `loaded=9` 且 `err=False` | ✅ 图片加载成功，指纹未被检测 |
| `loaded=0` 且持续 | ❌ 验证服务不可达（检查代理/DNS） |
| `loaded=9` → 短暂后 `err=True` | ❌ 指纹被检测，图片被 JS 隐藏 |
| `canvasHash` 每次不同 | 噪声注入活跃中 |
| 拦截到 `canvas.toDataURL` 调用 | 验证码在检查画布指纹 |

### 诊断产物

所有截图和日志保存在 `.runtime/diag/` 目录：

```
.runtime/diag/
├── noise-false-ok.png      # noise=false 测试成功截图
├── noise-false-err.png     # noise=false 错误截图
├── noise-false-final.png   # noise=false 最终状态截图
├── noise-true-err.png      # noise=true 错误截图
├── platform-win-err.png    # Windows 平台测试截图
├── stock-err.png           # 原生 Chromium 截图
└── intercept-final.png     # API 拦截测试截图
```

## 代码修复记录

### 已实现的改进 (captcha/ 模块)

1. **`captcha/recognizer.py`** — LLM 识别验证码
   - 发送截图到 llama.cpp，解析 JSON 响应
   - 处理截断的 markdown 代码块
   - 返回结构化 `CaptchaRecognition`（类别、正确/错误格子位置）

2. **`captcha/drag_captcha.py`** — 拖拽执行
   - DOM 检测验证码容器（含 iframe 支持）
   - `wait_for_captcha_images()` — 轮询等待图片加载（naturalWidth > 0）
   - `_has_image_load_error()` — 检测"图片加载失败"文字
   - 网格坐标计算 + Bézier 曲线拟人化拖拽
   - 自动刷新重试（最多 4 次）

3. **`captcha/__init__.py`** — 编排流程
   ```
   detect → wait_for_images → refresh×4 → screenshot → LLM → drag → submit
   ```

4. **`run_doubao.py`** — 集成
   - 页面加载后自动检测并解决验证码
   - CAPTCHA 验证服务 CDN 绕过代理（`_install_captcha_cdn_bypass`）
   - `proxy.enabled` 全局代理开关
   - `fingerprint.noise` 指纹噪声开关

5. **`config.template.toml`** — 新增配置项
   ```toml
   [proxy]
   enabled = "true"           # 全局代理开关
   
   [captcha]
   bypass_proxy = true        # 验证服务直连
   
   [fingerprint]
   noise = "false"            # 关闭噪声注入
   ```
