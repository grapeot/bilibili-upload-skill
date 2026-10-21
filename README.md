# bilibili-upload-skill

一个 agent skill（`skills/bilibili-upload/SKILL.md`）加一个 Python 命令行工具（`bili-upload`）：在人能看到的 Chrome 里，用 Playwright 把 B 站投稿表单填好，然后停在「立即投稿」按钮前，由人核对并亲手提交。

## 适合谁

自己做视频、用 coding agent 辅助发布的个人创作者。你希望 agent 处理选文件、填标题标签简介、选分区和创作声明、传封面和字幕、录章节这些机械操作，而登录和最后的提交始终由你自己完成。

不适合批量投稿、无人值守投稿或录播搬运。

## 工作方式

1. `bili-upload open` 用系统 Chrome 和一个独立的持久 profile 打开可见窗口，调试端口只监听本机。
2. 你在窗口里扫码登录一次。登录态保存在本机 profile 里，之后重开浏览器仍然有效。
3. agent 准备一份投稿元数据 JSON，先跑 dry-run 给你看计划。
4. 你同意上传后，agent 运行 `bili-upload fill --execute`：选视频（这一步就开始上传）、逐项填表、读回核对，把「立即投稿」滚到视野内，然后断开连接。
5. 你在浏览器里检查，自己点「立即投稿」。

## 安全承诺

- 工具不会点击「立即投稿」「存草稿」「提交」「投稿」。所有点击都经过一个点击守卫，测试覆盖了这一点。
- 工具不自动登录，不接收账号密码，不读取、不打印、不导出 cookie。
- 浏览器 profile 只留在本机，并已写入 `.gitignore`。
- `fill` 默认只打印计划；只有显式传 `--execute` 才会选文件并开始上传。

完整设计和安全规则见 `docs/design.md`。

## 状态

v0.1：命令行已实现，元数据校验、执行计划和点击守卫有离线测试。页面选择器依赖 B 站当前的投稿页结构，改版后可能需要更新。命令参考和各部分的实现状态见 `skills/bilibili-upload/SKILL.md`。

## 安装

需要 Python 3.10 以上、系统安装的 Google Chrome，以及 [uv](https://github.com/astral-sh/uv)。

```bash
uv venv
source .venv/bin/activate
uv pip install -e '.[dev]'
python -m pytest -q
```

本工具连接系统 Chrome，不需要运行 `playwright install` 下载浏览器。

## 快速上手

```bash
bili-upload open                                  # 启动可见 Chrome，扫码登录
bili-upload status                                # logged_in 应为 true
bili-upload fill --meta upload.json               # dry-run，看计划
bili-upload fill --meta upload.json --execute     # 选视频、填表，停在提交前
```

元数据格式见 `skills/bilibili-upload/SKILL.md`。

## 许可

MIT
