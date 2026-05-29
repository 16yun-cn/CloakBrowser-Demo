# 项目重构计划 — src 布局 + pytest + ruff

## 目标结构

```
cloakbrowser-demo/
├── src/
│   ├── __init__.py
│   ├── config.py              # 原 config_loader.py
│   ├── runner.py              # 原 run_doubao.py（单 worker）
│   ├── concurrent.py          # 原 run_concurrent.py（多 worker）
│   └── captcha/
│       ├── __init__.py
│       ├── drag_captcha.py    # 原 captcha/drag_captcha.py
│       └── recognizer.py      # 原 captcha/recognizer.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py            # 共享 fixtures
│   ├── test_config.py         # 配置解析测试
│   ├── test_runner.py         # runner 纯逻辑测试
│   ├── test_concurrent.py     # 编排逻辑测试
│   └── test_captcha_recognizer.py  # captcha 识别测试（mock LLM）
├── scripts/                   # 诊断工具（不变）
│   ├── diag_captcha.py
│   └── diag_fingerprint.py
├── docs/                      # 文档（不变）
├── config.template.toml
├── pyproject.toml             # 更新：src 布局、pytest/ruff 配置、入口点
├── Makefile                   # 更新：make test, make lint
├── .gitignore                 # 更新：忽略 CloakBrowser/
├── .pre-commit-config.yaml    # 新增：pre-commit hooks
└── README.md
```

## 变更清单

### 1. 代码搬迁（纯移动，改导入路径）

- `config_loader.py` → `src/config.py`
- `run_doubao.py` → `src/runner.py`
- `run_concurrent.py` → `src/concurrent.py`
- `captcha/` → `src/captcha/`
- 更新所有内部 `import` 路径（`from config_loader` → `from src.config`，`from captcha` → `from src.captcha`）
- 删除 `scripts/test_captcha_recognizer.py`（移到 `tests/`）

### 2. pyproject.toml 更新

- 添加 `[tool.ruff]` 配置（lint + format）
- 添加 `[tool.pytest.ini_options]` 配置
- 添加 `[project.scripts]` 入口点
- 添加 `[dependency-groups]` dev 依赖：`pytest`、`ruff`

### 3. .gitignore 更新

- 添加 `CloakBrowser/` 忽略整行

### 4. 测试初始化

- `tests/conftest.py` — 共享 fixtures（示例 config dict、临时目录）
- `tests/test_config.py` — 测试 `build_fingerprint_args`、`build_proxy`、`get_concurrency` 等纯函数
- `tests/test_runner.py` — 测试 `extract_response`、`is_noise_text`、`prompt_submitted` 等不依赖浏览器的逻辑
- `tests/test_concurrent.py` — 测试 aggregate 构建、worker 结果合并
- `tests/test_captcha_recognizer.py` — 从 `scripts/` 迁移，用 mock 替代 LLM 在线调用
- 每个测试文件至少 3-5 个测试用例

### 5. Makefile 更新

- `make lint` — `uv run ruff check src/ tests/`
- `make format` — `uv run ruff format src/ tests/`
- `make test` — `uv run pytest`
- 更新 `make check` — 同时跑 lint + test

### 6. Pre-commit hooks（新增）

- `.pre-commit-config.yaml`：`ruff check` + `ruff format`

## 不做的

- CI/CD（GitHub Actions）— 等测试覆盖率上来再加
- mypy/pyright 类型检查 — Playwright 动态 API 为主，收益有限
- 集成测试 — 需要 CloakBrowser 二进制 + 代理 + LLM，后续单独加

## 验证

1. `uv run pytest` 全部通过
2. `uv run ruff check` 无报错
3. `uv run ruff format --check` 确认格式正确
4. `make lint`、`make test`、`make check` 均可工作
5. `uv run doubao` 和 `uv run doubao-concurrent` 入口点可用
6. `CloakBrowser/` 在 `.gitignore` 中，`git status` 不会看到它
