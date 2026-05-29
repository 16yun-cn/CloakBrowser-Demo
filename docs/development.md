# 开发文档

本文档面向维护这个 Demo 的开发者，重点说明项目结构、配置设计、执行流程、关键实现、调试方法和已知限制。

## 1. 项目目标

这个项目的目标不是做一个通用浏览器框架，而是做一个最小可维护的 Doubao 自动化 Demo。

当前范围：

- 使用 `CloakBrowser` 打开 `https://www.doubao.com`
- 所有运行时策略都从 `config.toml` 注入
- 使用指定代理访问目标站点
- 输入配置中的问句并尝试提交
- 等待回复并保存截图、profile、报告
- 每次运行创建独立 session 目录

明确不做的事：

- 不做账号管理
- 不做多站点适配
- 不做自动代理轮换
- 不做复杂任务编排
- 不做代码内硬编码运行参数

## 2. 目录结构

当前主要文件：

```text
CloakBrowser-Demo/
├── Makefile
├── README.md
├── config.toml
├── run_doubao.py
└── docs/
    ├── cloak-browser-readme.md
    └── development.md
```

运行后生成：

```text
.runtime/
└── sessions/
    └── <session-id>/
        ├── doubao-before.png
        ├── doubao-after.png
        ├── doubao-run.json
        └── profile/
```

说明：

- `run_doubao.py` 是唯一业务入口
- `config.toml` 是唯一默认配置入口
- `.runtime/sessions/<session-id>/` 是一次运行的完整证据目录
- `docs/cloak-browser-readme.md` 是上游 CloakBrowser 参考文档
- `docs/development.md` 是本项目自身开发文档

## 3. 运行入口

推荐入口有两种。

### 3.1 直接运行

```bash
uv run --with cloakbrowser python -u run_doubao.py --config config.toml
```

### 3.2 使用 Makefile

```bash
make check
make run
make latest
make report
make sessions
```

说明：

- `make check` 只做语法编译检查
- `make run` 执行完整 Demo
- `make latest` 输出最近一次 session 目录
- `make report` 输出最近一次报告文件路径和内容
- `make sessions` 输出所有 session 目录

## 4. 配置设计

本项目的关键约束是：

1. 代理必须来自配置
2. 问句必须来自配置
3. 等待、轮询、候选数量、定位范围必须来自配置
4. selector 候选和噪声词必须来自配置
5. 代码只负责校验、拼装、执行，不保留业务侧常量

### 4.1 配置文件总览

默认配置文件是 `config.toml`。

当前结构：

```toml
[target]
[proxy]
[session]
[dialog]
[runtime]
[locators]
[fingerprint]
[artifacts]
```

### 4.2 `[target]`

用途：定义目标站点。

字段：

- `url`
  - 类型：字符串
  - 含义：本次访问的目标地址

当前默认值：

```toml
[target]
url = "https://www.doubao.com"
```

### 4.3 `[proxy]`

用途：定义代理。

字段：

- `server`
  - 类型：字符串
  - 例子：`http://127.0.0.1:6152`
- `username`
  - 类型：字符串
- `password`
  - 类型：字符串

代码行为：

- 如果 `username` 或 `password` 为空，则按无认证代理处理
- 如果有认证信息，则拼成 `scheme://user:pass@host:port`
- `server` 必须包含 scheme，否则直接报错

### 4.4 `[session]`

用途：定义一次运行的目录和基本运行参数。

字段：

- `base_dir`
  - session 根目录
- `session_name`
  - 可选前缀
- `profile_template_dir`
  - profile 模板目录，可为空
- `headless`
  - 是否无头
- `humanize`
  - 是否启用人类化交互
- `navigation_timeout_ms`
  - 页面默认导航超时
- `response_timeout_ms`
  - 等待回复总超时

代码行为：

- 每次运行都会生成新的 `session_id`
- `session_id` 格式：
  - 只有时间戳：`YYYYMMDD-HHMMSS`
  - 有前缀时：`<session_name>-YYYYMMDD-HHMMSS`
- `profile/` 永远位于当前 session 目录下
- 如果配置了 `profile_template_dir`，运行前会复制模板到当前 session 的 `profile/`

### 4.5 `[dialog]`

用途：定义问句和显式 selector。

字段：

- `prompt`
  - 必填
- `input_selector`
  - 可选
- `submit_selector`
  - 可选
- `response_selector`
  - 可选

策略：

- 优先使用显式 selector
- 如果为空，再回退到 `[locators]` 中的候选列表

### 4.6 `[runtime]`

用途：定义所有运行时策略参数。

字段：

- `min_reply_wait_seconds`
  - 检测到回复后最少还要等待多久再截图
- `page_load_timeout_ms`
  - `load` 阶段额外等待时间
- `element_visible_timeout_ms`
  - 输入框候选可见等待时间
- `submit_visible_timeout_ms`
  - 显式提交 selector 的等待时间
- `submit_retry_visible_timeout_ms`
  - 提交按钮候选的等待时间
- `submit_state_timeout_ms`
  - 提交后判断“是否真的发出”的最长等待时间
- `submit_state_poll_interval_ms`
  - 提交状态轮询间隔
- `response_poll_interval_ms`
  - 回复抓取轮询间隔
- `max_selector_matches`
  - 每个 selector 最多检查多少个节点
- `max_button_matches`
  - 近邻按钮查找时最多检查多少个按钮
- `send_button_min_x_ratio`
  - 按钮必须位于输入框右侧多少比例之后
- `send_button_y_tolerance_px`
  - 按钮相对输入框的上下容差
- `response_min_x`
  - 响应候选节点允许的最小横坐标
- `response_min_y`
  - 响应候选节点允许的最小纵坐标
- `response_max_y`
  - 响应候选节点允许的最大纵坐标
- `response_min_text_length`
  - 响应最小文本长度
- `max_response_excerpt_length`
  - 报告中保留的回复摘要最大长度

这部分配置非常关键，因为它直接决定页面结构变化后 Demo 的适应能力。

### 4.7 `[locators]`

用途：定义所有候选 selector 和噪声词。

字段：

- `input_selectors`
  - 输入框候选 selector 列表
- `submit_button_selectors`
  - 发送按钮候选 selector 列表
- `response_candidate_selectors`
  - 回复内容候选 selector 列表
- `noise_tokens`
  - 需要从响应提取中排除的页面文案

说明：

- 这部分必须留在配置里，不应该回退到代码常量
- 页面结构变动时，通常先调这部分而不是改 Python 逻辑

### 4.8 `[fingerprint]`

用途：定义手工指纹。

字段：

- `seed`
- `platform`
- `brand`
- `brand_version`
- `platform_version`
- `gpu_vendor`
- `gpu_renderer`
- `hardware_concurrency`
- `device_memory`
- `screen_width`
- `screen_height`
- `timezone`
- `locale`
- `storage_quota_mb`
- `webrtc_ip_mode`

代码行为：

- 所有字段都会转换成 `--fingerprint-*` 参数
- 不启用 `geoip`
- `webrtc_ip_mode` 仅允许：
  - `auto`
  - 显式 IP

### 4.9 `[artifacts]`

用途：定义产物文件名。

字段：

- `before_send_filename`
- `after_reply_filename`
- `run_report_filename`

约束：

- 这里只允许文件名，不允许路径
- 路径由 session 目录统一控制

## 5. 代码执行流程

一次运行的主调用链如下：

```text
main
  ├── parse_args
  ├── load_config
  ├── build_session_paths
  ├── prepare_profile
  ├── run_dialog
  │   ├── get_runtime_config
  │   ├── get_locator_config
  │   ├── build_fingerprint_args
  │   ├── launch_persistent_context
  │   ├── page.goto
  │   ├── find_first_visible
  │   ├── fill_prompt
  │   ├── submit_prompt
  │   ├── extract_response
  │   └── screenshot
  └── write_report
```

如果第一次运行失败，`main()` 会自动再试一次 HTTP/2 兜底：

- 在启动参数中附加 `--disable-http2`
- 复用当前 session 的 profile 目录

## 6. 关键实现说明

### 6.1 `build_session_paths`

职责：

- 生成 session 目录
- 生成截图和报告路径
- 保证每次运行目录隔离

为什么这样做：

- 自动化链路必须保留证据
- 同一目录反复覆盖会让问题定位变难

### 6.2 `prepare_profile`

职责：

- 决定本次运行的 profile 来源

行为：

- 有模板目录：复制模板
- 没模板目录：创建空 profile

作用：

- 允许后续使用预热过的 profile 做稳定性对比

### 6.3 `build_proxy`

职责：

- 统一代理拼装格式

注意点：

- 认证信息不写死在代码
- `server` 缺 scheme 时直接失败

### 6.4 `build_fingerprint_args`

职责：

- 把 TOML 中的手工指纹字段拼成 CloakBrowser 启动参数

注意点：

- 这是项目和上游 CloakBrowser 的对接层
- 后续如果新增指纹字段，应优先扩这个函数和 `[fingerprint]`

### 6.5 `find_first_visible`

职责：

- 从候选 selector 列表中，找到第一个真正可见且有尺寸的节点

为什么不是 `.first`：

- 豆包页面存在多个相似节点
- 只取第一个很容易命中隐藏层或壳节点

### 6.6 `fill_prompt`

职责：

- 把问句真正写入输入区

当前策略：

1. 先点击并聚焦
2. 如果是 `textarea` / `input`，先 `fill`
3. 如果回读不一致，再尝试键盘输入
4. 如果是 `contenteditable`，再尝试 JS 注入和键盘兜底
5. 最后强制回读校验

设计目的：

- 不把“调用了输入方法”误判为“已经输入成功”

### 6.7 `submit_prompt`

职责：

- 把已输入的问句真正发出去

当前策略：

1. 优先用 `dialog.submit_selector`
2. 再走 `[locators].submit_button_selectors`
3. 再走“距离输入框最近的按钮”
4. 最后回退到 `Enter`

提交成功判断：

- 不是看点击是否执行
- 而是看输入框内容是否不再等于原始 prompt

### 6.8 `click_nearest_send_button`

职责：

- 在显式 selector 都失败时，通过几何关系找发送按钮

适用场景：

- 页面按钮没有稳定文字
- DOM 结构变化频繁

调优入口：

- `send_button_min_x_ratio`
- `send_button_y_tolerance_px`
- `max_button_matches`

### 6.9 `extract_response`

职责：

- 从页面中提取真实回复文本

策略：

1. 如果配置了 `dialog.response_selector`，优先直接取
2. 否则按 `[locators].response_candidate_selectors` 轮询
3. 用坐标范围和噪声词过滤页面 chrome 文案
4. 找到满足最短长度要求的文本即视为回复

这部分是最容易误报成功的地方。

之前踩过的坑：

- 把“下载电脑版”“登录”等页面文案误当成回复
- 把提示语或自身 prompt 误当成回复

所以这部分的过滤条件必须清晰且可配置。

## 7. 运行产物

一次运行会产生四类产物。

### 7.1 `doubao-before.png`

用途：

- 记录发送前页面状态
- 确认输入框定位是否正确
- 确认 prompt 是否已经进入输入区

### 7.2 `doubao-after.png`

用途：

- 记录等待结束后页面状态
- 确认是否真的出现了回复
- 确认是否存在错误图标、失败提示、登录提示

### 7.3 `doubao-run.json`

用途：

- 机器可读的运行结果

主要字段：

- `status`
- `session_id`
- `session_dir`
- `profile_dir`
- `artifacts`
- `started_at`
- `finished_at`
- `duration_seconds`
- `used_http2_fallback`
- `final_url`
- `title`
- `prompt`
- `response_excerpt`
- `error`

### 7.4 `profile/`

用途：

- 保存本次浏览器上下文
- 用于问题复现或 profile 对比

## 8. 错误分层

建议按下面顺序判断问题。

### 8.1 配置错误

典型表现：

- 缺 section
- 缺必填字段
- 字段类型错误
- 文件名字段包含路径

处理方式：

- 先修 `config.toml`
- 不要先改代码

### 8.2 浏览器启动错误

典型表现：

- CloakBrowser 启动失败
- 上游包安装失败
- 二进制初始化失败

处理方式：

- 先看 `uv` 和 `cloakbrowser` 安装状态
- 再看上游环境依赖

### 8.3 页面加载错误

典型表现：

- 页面打不开
- 页面被拦截
- 页面结构与预期不一致

处理方式：

- 先看 `doubao-before.png`
- 再看代理、登录态、风控状态

### 8.4 输入错误

典型表现：

- 页面打开了，但问句没进输入框

处理方式：

- 先调 `[locators].input_selectors`
- 再看 `fill_prompt` 是否需要补新路径

### 8.5 发送错误

典型表现：

- 问句进去了，但蓝色发送按钮仍然存在
- 输入框内容未清空

处理方式：

- 先调 `[locators].submit_button_selectors`
- 再调发送按钮位置参数

### 8.6 回复提取错误

典型表现：

- 页面已有回复，但报告没抓到
- 页面没回复，却误判成功

处理方式：

- 先调 `[locators].response_candidate_selectors`
- 再调：
  - `noise_tokens`
  - `response_min_x`
  - `response_min_y`
  - `response_max_y`
  - `response_min_text_length`

## 9. 调试建议

### 9.1 最小调试顺序

推荐先看这三个东西：

1. `doubao-before.png`
2. `doubao-after.png`
3. `doubao-run.json`

原因：

- 大多数问题都能先从证据文件看出在哪一层失败

### 9.2 配置优先，代码次之

页面结构变化时，优先调：

- `[dialog]`
- `[runtime]`
- `[locators]`

不要第一时间改 Python 逻辑。

### 9.3 新增站点适配时的原则

如果以后要支持别的站点，建议：

- 保留当前 Doubao 脚本作为单站点实现
- 不要直接把它泛化成过早抽象的大框架
- 先复制一份站点脚本，再根据共性决定是否抽象

## 10. 当前已知限制

当前最重要的限制有三个。

### 10.1 代理导致的回复不稳定

已经验证：

- 页面可打开
- 输入可完成
- 提交可完成

仍然可能失败：

- 回复不返回
- 回复返回很慢
- 页面只显示已发送问句，没有有效回答

这更像代理链路或站点策略问题，而不是输入逻辑问题。

### 10.2 回复提取仍依赖页面结构

虽然现在已经把提取策略配置化，但本质上它仍然依赖页面结构。

如果 Doubao 改版，最先需要调整的通常是：

- `response_candidate_selectors`
- `noise_tokens`
- 响应坐标范围

### 10.3 仍未引入登录态策略

当前 demo 没有内建登录态管理。

如果目标环境需要登录才能稳定回包，后续应优先考虑：

- 预热 profile
- 提供 profile 模板
- 通过 `profile_template_dir` 注入登录态

## 11. 后续演进建议

如果继续开发，优先级建议如下。

### 11.1 第一优先级

- 把页面上的“发送失败”状态显式提取到报告
- 区分“无回复”和“回复提取失败”
- 给 `run_report` 增加更明确的失败分类

### 11.2 第二优先级

- 为不同代理策略维护多份 TOML 配置
- 增加 profile 模板使用规范
- 增加一份“稳定回包”的基准配置

### 11.3 第三优先级

- 细化日志
- 增加更明确的阶段耗时
- 增加开发态截图或 DOM dump

## 12. 维护原则

维护这个项目时，建议始终遵守以下原则：

1. 能配就不要写死
2. 能留证据就不要只看控制台
3. 能先调 selector 就不要先改流程
4. 能最小修改就不要提前抽象
5. 不要把“页面有变化”误判成“已经收到有效回复”

如果后续有人接手，这份文档应该和 `config.toml`、`run_doubao.py` 一起维护；任何新增运行时策略，都应该先体现在配置和本文档里，再进入代码。
