"""投稿页选择器：全仓库唯一的定义处。

B 站投稿页是 <micro-app name="video-up"> 微前端，表单在普通 DOM 里，CSS 可以直接选到。
改版后只需要改这里。每个条目带一句用途说明，`missing_selectors` 报告会带上它。
"""

from __future__ import annotations

from dataclasses import dataclass

UPLOAD_URL = "https://member.bilibili.com/platform/upload/video/frame"
NAV_API = "https://api.bilibili.com/x/web-interface/nav"


@dataclass(frozen=True)
class Selector:
    css: str
    note: str


SELECTORS: dict[str, Selector] = {
    # 落地页
    "file_input": Selector("input[type=file][name=buploader][accept*='.mp4']", "视频文件输入框（落地页，只用于核对）"),
    "upload_area": Selector(".upload-area", "落地页上传区域（点击它弹出文件选择框；内部的 .upload-btn 不接收点击）"),
    # 上传状态
    "upload_item": Selector(".file-list-v2-item, .file-item", "已选视频的上传条目"),
    # 基本信息
    "title": Selector(".video-title input.input-val", "标题输入框"),
    "cover": Selector(".cover-module .cover-img", "封面区域（点击打开封面编辑器）"),
    "cover_dialog": Selector(".cover-editor", "封面编辑弹窗"),
    "cover_file_input": Selector(".cover-editor input[type=file]", "封面弹窗里的图片文件输入框"),
    "statement_input": Selector(".creation-statement-container input.bcc-select-input-inner", "创作声明下拉框"),
    "statement_option": Selector(".creation-statement-container li.bcc-option", "创作声明选项"),
    "partition_controller": Selector(".video-human-type .select-controller", "分区下拉框"),
    "partition_value": Selector(".video-human-type .select-item-cont", "分区当前值"),
    "partition_option": Selector(".video-human-type .drop-list-v2-item", "分区选项"),
    "tag_input": Selector(".tag-container .tag-input-wrp input.input-val", "标签输入框"),
    "tag_item": Selector(".tag-container .tag-pre-wrp .label-item-v2-content", "已添加的标签"),
    "desc_editor": Selector(".desc-container .ql-editor", "简介编辑器（Quill）"),
    # 更多设置
    "more_settings_toggle": Selector(".title .label", "「更多设置」展开开关"),
    "more_settings": Selector(".setting", "更多设置区域（默认折叠）"),
    "visibility_radio": Selector(".check-radio-v2-container", "可见范围单选项"),
    "visibility_checked": Selector(".check-radio-v2-box-checked + .check-radio-v2-name", "当前选中的可见范围"),
    "chapter_section": Selector(".player-setting-wrp", "章节管理区域"),
    "chapter_button": Selector(".player-setting-wrp button", "「编辑章节」按钮"),
    "subtitle_section": Selector(".subtitle-setting-wrp", "字幕设置区域"),
    "subtitle_button": Selector(".subtitle-setting-wrp button", "「上传字幕」按钮"),
    "dynamic_editor": Selector(".fans-input-wrp .ql-editor", "粉丝动态编辑器"),
    # 提交区：只用来定位和滚动，永不点击
    "submit": Selector(".submit-container .submit-add", "「立即投稿」按钮（只定位，不点击）"),
}


def css(name: str) -> str:
    return SELECTORS[name].css
