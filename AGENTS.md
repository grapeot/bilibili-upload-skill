# AGENTS.md

给在 `https://github.com/grapeot/bilibili-upload-skill` 里工作的 coding agent 的说明和不变量。

## 命令

先检查仓库根目录有没有 `.venv`。有就激活；没有就用 uv 创建。安装依赖用 `uv pip install`。

```bash
uv venv
source .venv/bin/activate
uv pip install -e '.[dev]'
python -m pytest -q
```

测试完全离线，不访问 B 站。`tests/test_guard_dom.py` 会用本机 Chrome 无头打开一段内嵌 HTML，检验守卫的真实 JS；找不到 Chrome 时自动跳过。

## 仓库不变量

1. **默认分支是 `master`。** 所有改动走 feature 分支和 PR，目标分支是 `master`。
2. **永不点击提交类按钮。** 「立即投稿」「存草稿」「提交」「投稿」不能被工具点击。所有点击、按键和文字输入必须经过 `guard.py`（`safe_click` / `focus_editable` / `safe_press` / `safe_insert_text` / `safe_fill`）；不要新增绕过守卫的路径（包括 `page.evaluate` 里的 `el.click()`、直接 `keyboard.press`、派发事件等）。`tests/test_guard.py` 会扫描源码拦截这类调用。修改守卫时必须同步更新测试。
3. **不自动登录，不碰 cookie。** 不添加读取、导出、打印或注入 cookie / storage state 的代码。登录只能由人在浏览器窗口里完成。
4. **不提交个人数据。** 不提交浏览器 profile、截图、DOM 快照、视频、字幕、真实的投稿元数据、账号 ID、稿件 ID、个人姓名或任何机器上的绝对路径。文档和测试用占位路径（如 `/path/to/video.mp4`）和合成数据。
5. **选择器只在一处定义。** 所有 CSS 选择器写在 `src/bilibili_upload/selectors.py`。找不到元素时报告选择器名，不要猜测替代元素。
6. **每个命令输出一个 JSON 对象。** `bili-upload` 的每个子命令（包括出错时）向 stdout 输出恰好一个 JSON 对象；`--help` 除外。
7. **`fill` 默认 dry-run。** 只有显式 `--execute` 才连接浏览器并选择文件。已有投稿标签页时 `--execute` 拒绝重复上传，除非显式 `--reuse-tab` 或 `--new-upload`。
8. **只接入自己启动的浏览器。** 连接前核对端口上的 Chrome 进程确实带着当前 `--profile-dir` 启动。

## 目录结构

```text
bilibili-upload-skill/
├── README.md
├── AGENTS.md
├── LICENSE
├── pyproject.toml
├── docs/design.md                # 目标、边界、架构、安全规则
├── skills/bilibili-upload/SKILL.md   # agent 使用说明与元数据格式
├── src/bilibili_upload/          # 实现（见 docs/design.md 的模块划分）
└── tests/                        # 离线测试
```
