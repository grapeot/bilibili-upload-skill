"""由元数据生成执行计划。dry-run 直接输出它；--execute 按它逐步执行。"""

from __future__ import annotations

from typing import Any

from .meta import UploadMeta, picker_time

# B 站在点「立即投稿」时才校验定时时间，填表时合规不代表提交时还合规
SCHEDULE_HUMAN_STEP = "点「立即投稿」时定时时间须仍在当前之后至少 5 分钟；等太久就先在页面上改时间"

# 永远留给人的步骤
ALWAYS_HUMAN = [
    "如属系列，在页面上加入对应合集（工具不操作合集）",
    "在浏览器里核对所有字段",
    "亲手点击「立即投稿」（工具不会点击）",
]


def build_plan(meta: UploadMeta, reuse_tab: bool = False) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []

    def add(step: str, detail: Any = None) -> None:
        steps.append({"step": step, "detail": detail})

    if reuse_tab:
        add("reuse_tab", "接入已选好视频的投稿标签页，不重新选择文件")
    else:
        add("open_tab", "新开标签页进入投稿页")
        add("select_video", {"path": str(meta.video), "note": "选择文件后立即开始上传"})
    add("title", {"value": meta.title, "note": "先清空自动带入的文件名"})
    if meta.cover or meta.cover_4x3:
        add("cover", {"16:9": str(meta.cover) if meta.cover else None,
                      "4:3": str(meta.cover_4x3 or meta.cover),
                      "note": "4:3 未单独指定时用 16:9 图片，B 站会裁掉两侧" if not meta.cover_4x3 else None})
    add("creation_statement", meta.creation_statement)
    if meta.partition:
        add("partition", meta.partition)
    if meta.tags:
        add("tags", meta.tags)
    if meta.description:
        add("description", {"chars": len(meta.description), "lines": meta.description.count("\n") + 1})
    add("visibility", meta.visibility)
    if meta.subtitles:
        add("subtitles", {"path": str(meta.subtitles.path), "language": meta.subtitles.language,
                          "default_on": meta.subtitles.default_on})
    if meta.chapters:
        add("chapters", [{"time": c.timestamp, "title": c.title} for c in meta.chapters])
    if meta.dynamic:
        add("dynamic", {"chars": len(meta.dynamic)})
    if meta.schedule:
        add("schedule", {"at": meta.schedule.isoformat(), "picker": picker_time(meta.schedule),
                         "note": "打开定时发布，按选择器默认的北京时间选日期和时间；时间须在执行时之后 5 分钟到 15 天内"})
    add("dismiss_dialogs", "每一步前用 x 关闭已知无害弹窗（如上传完成通知），其他弹窗按文字报告")
    add("wait_upload", "等待视频上传与处理")
    add("readback", "逐项读回并与元数据比对")
    add("stop_before_submit", "把「立即投稿」滚动到视野内，断开连接，不点击")

    human = list(ALWAYS_HUMAN)
    if meta.subtitles and not meta.subtitles.default_on:
        human.insert(0, "表单里没有字幕默认开关；如需确认字幕对观众默认关闭，投稿后在字幕管理或播放页检查")
    if meta.schedule:
        human.insert(0, SCHEDULE_HUMAN_STEP)
    return {"steps": steps, "human_steps": human, "meta": meta.to_json()}
