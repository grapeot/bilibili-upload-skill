---
name: bilibili-upload
description: 在人能看到的 Chrome 里，用 Playwright 替视频所有者填写 B 站（哔哩哔哩）投稿表单：选视频、标题、封面、创作声明、分区、标签、简介、章节、字幕、可见范围、粉丝动态，读回核对后停在「立即投稿」之前，由人亲手提交。适用于个人、低频、需要人把关的投稿；不用于批量或无人值守投稿。
---

# bilibili-upload

## 什么时候用

- 视频所有者要把一个本地视频投到自己的 B 站账号，希望 agent 把表单填好，自己只核对和点提交。
- B 站改版后需要核对、修复选择器。

不要用于批量投稿、无人值守投稿或搬运他人内容。

## 硬性规则

1. **永远不点提交。** 「立即投稿」「存草稿」「提交」「投稿」只能由人点击。工具里所有点击都经过点击守卫，守卫拒绝这类按钮；不要绕过守卫，也不要用 `page.evaluate` 之类的方式间接点击。
2. **选文件就是开始上传。** `fill --execute` 会把视频交给页面的文件输入框，B 站随即开始上传。执行前必须确认视频所有者已经授权上传**这一个具体视频**。没有授权时只跑 dry-run。
3. **不自动登录。** 未登录就请人在浏览器窗口里扫码。不要索要或填写账号、密码、验证码，不要读取或打印 cookie。
4. **登录态不出本机。** profile 目录不进版本库，不上传，不打印其中的文件内容。
5. **只连自己启动的浏览器。** 用 `bili-upload open` 启动的 Chrome；不要接入人正在日常使用的浏览器。
6. **交接后不再动那个标签页。** `fill` 结束后，标签页属于人。

## 流程

```bash
bili-upload status                      # 只读：浏览器是否在线、是否已登录
bili-upload open                        # 没有会话时启动可见 Chrome，然后请人扫码登录
bili-upload fill --meta upload.json     # dry-run：校验元数据，打印执行计划，不碰浏览器
bili-upload fill --meta upload.json --execute   # 选视频、填表、读回核对，停在提交按钮前
```

1. 跑 `status`。`logged_in` 不是 `true` 时，跑 `open`（或让人在已打开的窗口里登录），等人扫码后再跑一次 `status`。
2. 准备元数据 JSON（格式见下文），跑 dry-run，把计划给人看。重点核对：视频路径、标题、分区、创作声明、可见范围。
3. 确认上传授权后跑 `--execute`。命令会等视频上传和处理推进到可以提交的程度（或超时），然后把每个字段读回来比对。
4. 读结果 JSON：`filled`（已填）、`skipped`（跳过及原因）、`missing_selectors`（页面上找不到的选择器）、`mismatches`（读回与预期不符）、`upload`（上传状态）、`human_steps`（需要人做的事）。把这些如实转告人。
5. 请人在浏览器里核对并亲手点「立即投稿」。

## 元数据格式

一个 UTF-8 JSON 对象。相对路径按元数据文件所在目录解析。

```json
{
  "video": "/path/to/video.mp4",
  "title": "视频标题",
  "cover": "cover.jpg",
  "creation_statement": "内容无需标注",
  "partition": "知识",
  "tags": ["标签一", "标签二"],
  "description": "第一段\n\n第二段",
  "chapters": [
    {"start": 0, "title": "开场"},
    {"start": "05:00", "title": "第二部分"}
  ],
  "subtitles": {"path": "subtitles.srt", "language": "中文", "default_on": false},
  "visibility": "public",
  "dynamic": "粉丝动态文字"
}
```

| 字段 | 必填 | 约束 | 说明 |
|---|---|---|---|
| `video` | 是 | 文件存在 | 视频文件路径 |
| `title` | 是 | 1 到 80 字 | 会先清空 B 站自动带入的文件名 |
| `cover` | 否 | jpg / png，文件存在 | 封面图；不填则保留 B 站自动截取的封面 |
| `creation_statement` | 是 | 页面上的选项原文 | 如「内容无需标注」「含AI生成内容」「个人观点，仅供参考」。添加后不可编辑 |
| `partition` | 否 | 页面上的分区显示名 | 不填则保留 B 站推荐的分区 |
| `tags` | 否 | 至多 10 个，每个至多 20 字，不重复 | 逐个输入并回车 |
| `description` | 否 | 至多 2000 字 | `\n` 换行 |
| `chapters` | 否 | `start` 递增，第一个为 0 | `start` 可以是秒数或 `MM:SS` / `HH:MM:SS`；页面不支持章节时记入 `skipped` |
| `subtitles` | 否 | 只接受 `.srt` | `default_on` 默认 `false`；页面若没有默认开关，记入 `human_steps` |
| `visibility` | 否 | `public` 或 `self` | 默认 `public`；首次在新账号上演练建议用 `self` |
| `dynamic` | 否 | 至多 233 字 | 粉丝动态文字 |

## 命令参考

所有命令向 stdout 输出一个 JSON 对象。全局参数 `--port`（默认 `$BILI_CDP_PORT` 或 9341）、`--profile-dir`（默认 `$BILI_PROFILE_DIR` 或 `~/.bilibili-upload/browser-profile`）。

| 命令 | 作用 | 是否改动页面 |
|---|---|---|
| `open [--url URL]` | 启动可见 Chrome；端口或 profile 被占用时拒绝 | 启动浏览器 |
| `status` | 浏览器是否在线、`logged_in` 是否为 `true` | 只读 |
| `fill --meta M` | 校验元数据并输出执行计划 | 不碰浏览器 |
| `fill --meta M --execute` | 新开标签页、选视频（开始上传）、填表、等待上传、读回核对；已有投稿标签页时拒绝，避免重复上传 | 填表，不提交 |
| `fill --meta M --execute --reuse-tab` | 接入已选好视频的投稿标签页继续填，不再选文件，不会重复上传 | 填表，不提交 |
| `readback --meta M` | 读回当前投稿标签页并与元数据比对 | 只读 |
| `selectors` | 列出所有选择器；浏览器在线时统计当前投稿页的匹配数 | 只读 |

`fill --execute` 的其他参数：`--upload-timeout 秒数`（默认 1800）、`--no-wait`（不等上传完成）、`--new-upload`（明确要再上传一次时才用）。

`status`、`fill --execute`、`readback`、`selectors` 连接前都会核对端口上的 Chrome 是用当前 profile 启动的；对不上就拒绝，并提示设置 `--profile-dir` 或 `BILI_PROFILE_DIR`。

`fill --execute` 一旦选了文件，即使后续步骤出错也会返回完整的部分报告（`video_selected: true`）。重试时用 `--reuse-tab`，它会按视频文件名找到原来的标签页继续填。

## 实现状态

| 部分 | 状态 |
|---|---|
| 元数据校验、执行计划、点击守卫 | 已实现，有离线测试 |
| `open` / `status` / `readback` / `selectors` | 已实现 |
| `fill --execute` | 已实现；选择器以真实新投稿页为准，B 站改版后可能需要更新 |

## 已知限制与坑

- **大文件不能用 Playwright 的 `set_input_files`。** 通过 `connect_over_cdp` 接入的浏览器在 Playwright 看来是远程浏览器，`set_input_files` 会把文件内容经 CDP 传过去，上限 50 MB，真实视频几乎都超过，报错为 `Cannot transfer files larger than 50Mb to a browser not co-located with the server`。本工具改用 CDP 的 `DOM.setFileInputFiles`，只把本机绝对路径交给 Chrome，由 Chrome 自己从磁盘读取。前提是 Chrome 和本工具在同一台机器上。
- 选文件之前出错时，`fill --execute` 会关掉自己新开的标签页，不留空的投稿页。
- 章节编辑还没有自动化，执行结果会把章节列在 `human_steps` 里。
- 字幕默认开关、字幕语言、封面最终效果需要人在页面上确认。

## 故障排查

- `missing_selectors` 非空：B 站可能改版。打开浏览器开发者工具找到新结构，只改 `src/bilibili_upload/selectors.py`。
- 上传一直不结束：大文件需要时间，`--upload-timeout` 可以加长等待；等待超时不会中断上传，标签页仍然保留。
- 中途放弃：选文件后 B 站可能生成草稿，请人去创作中心的草稿列表清理。
