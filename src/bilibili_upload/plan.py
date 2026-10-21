"""由元数据生成执行计划。dry-run 直接输出它；--execute 按它逐步执行。"""

from __future__ import annotations

from typing import Any

from .meta import UploadMeta

# 永远留给人的步骤
ALWAYS_HUMAN = [
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
    if meta.cover:
        add("cover", str(meta.cover))
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
    add("wait_upload", "等待视频上传与处理")
    add("readback", "逐项读回并与元数据比对")
    add("stop_before_submit", "把「立即投稿」滚动到视野内，断开连接，不点击")

    human = list(ALWAYS_HUMAN)
    if meta.subtitles and not meta.subtitles.default_on:
        human.insert(0, "确认字幕对观众默认关闭（若页面没有该开关，投稿后在字幕管理里检查）")
    return {"steps": steps, "human_steps": human, "meta": meta.to_json()}
