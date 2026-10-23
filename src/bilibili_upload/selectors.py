"""投稿页选择器：全仓库唯一的定义处。

B 站投稿页是 <micro-app name="video-up"> 微前端，表单在普通 DOM 里，CSS 可以直接选到。
改版后只需要改这里。每个条目带一句用途说明，`missing_selectors` 报告会带上它。
除 chapter_text_mode（只在 Playwright locator 里使用）外，都必须是浏览器原生 CSS，
因为读回时会在页面里用 document.querySelector 执行。
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
    # 弹窗（选完文件后会弹出「开启后视频上传完成第一时间通知」，挡住所有字段）
    "dialog": Selector(".bcc-dialog", "页面上的 bcc 弹窗"),
    "dialog_close": Selector(".bcc-dialog__close", "弹窗右上角的关闭按钮（x）"),
    # 基本信息
    "title": Selector(".video-title input.input-val", "标题输入框"),
    "cover": Selector(".cover-module .cover-img", "封面区域（点击打开「封面制作」弹窗）"),
    "cover_file_input": Selector("input[type=file][accept*=image]", "封面弹窗里唯一的图片文件输入框（在弹窗内查找）"),
    "cover_confirm": Selector(".cover-editor-content .cover-editor-button .button.submit", "封面弹窗的「完成」（守卫对它有限定范围的放行）"),
    "statement_trigger": Selector(".creation-statement-container .bcc-select .bcc-select-input-wrap", "创作声明下拉框（点击展开）"),
    "statement_input": Selector(".creation-statement-container input.bcc-select-input-inner", "创作声明当前值"),
    "statement_option": Selector(".creation-statement-container li.bcc-option", "创作声明选项"),
    "partition_controller": Selector(".video-human-type .select-controller", "分区下拉框"),
    "partition_value": Selector(".video-human-type .select-item-cont", "分区当前值"),
    "partition_option": Selector(".video-human-type .item-cont-main", "分区选项"),
    "tag_input": Selector(".tag-container .tag-input-wrp input.input-val", "标签输入框"),
    "tag_item": Selector(".tag-container .label-item-v2-container", "已添加的标签"),
    "tag_close": Selector(".tag-container .label-item-v2-container svg.close", "已添加标签的删除按钮"),
    "desc_editor": Selector(".desc-container .ql-editor", "简介编辑器（Quill）"),
    # 更多设置
    "more_settings_toggle": Selector("span.label:has(span.des)", "「更多设置（含声明与权益…）」展开开关"),
    "more_settings": Selector(".setting", "更多设置区域（默认折叠）"),
    "visibility_radio": Selector(".check-radio-v2-container", "可见范围单选项"),
    "visibility_checked": Selector(".check-radio-v2-box-checked + .check-radio-v2-name", "当前选中的可见范围"),
    "chapter_section": Selector(".player-setting-wrp", "章节管理区域（同类区块里文字含「章节管理」的那个）"),
    "chapter_button": Selector(".player-setting-wrp button", "「编辑章节」按钮（按文字筛选）"),
    "chapter_iframe": Selector("iframe.iframe-wrp", "章节编辑弹窗里的 iframe（播放器页面）"),
    "chapter_text_mode": Selector("text=章节文本编辑器", "iframe 内：切换到章节文本编辑器"),
    "chapter_textarea": Selector("textarea.text-area", "iframe 内：章节文本框，每行「MM:SS 标题」"),
    "chapter_convert": Selector("button.save-button", "iframe 内：「转换成章节列表」"),
    "chapter_save": Selector("button.chapter-manager-save-btn", "iframe 内：「保存」"),
    "subtitle_section": Selector(".subtitle-setting-wrp", "字幕设置区域"),
    "subtitle_button": Selector(".subtitle-setting-wrp button", "「上传字幕」按钮"),
    "subtitle_dialog": Selector(".bcc-dialog:has(button.modal-content-upload-button)", "上传字幕弹窗"),
    "subtitle_lang": Selector(".bcc-select-input-wrap", "字幕弹窗内：语言下拉框"),
    "subtitle_lang_option": Selector("li.bcc-option", "字幕弹窗内：语言选项"),
    "subtitle_file_button": Selector("button.modal-content-upload-button", "字幕弹窗内：选择字幕文件"),
    "subtitle_confirm": Selector("button.modal-footer-button", "字幕弹窗内：「确认」（选好文件后才可用）"),
    "dynamic_editor": Selector(".fans-input-wrp .ql-editor", "粉丝动态编辑器"),
    # 定时发布（批量操作弹窗里还有一份同名区块，取可见的那个）
    "schedule_container": Selector(".time-container", "定时发布区块"),
    "schedule_switch": Selector(".switch-container", "定时发布区块内：开关（打开后多一个 -active 类）"),
    "schedule_timezone": Selector(".time-picker .bcc-select-input-inner", "定时发布区块内：时区（默认北京时间）"),
    "schedule_shown": Selector(".time-picker .date-show", "定时发布区块内：当前显示的日期、时间"),
    "schedule_date": Selector(".time-picker .date-picker-date", "定时发布区块内：日期下拉"),
    "schedule_date_panel": Selector(".time-picker .date-picker-container", "定时发布区块内：日历面板"),
    "schedule_month_title": Selector(".time-picker .date-picker-nav-title", "日历面板：「2026年10月」"),
    "schedule_next_month": Selector(".time-picker .next-btn-month", "日历面板：下一个月"),
    "schedule_day": Selector(".time-picker .date-wrp .date-item, .time-picker .date-wrp .date-item-selected",
                             "日历面板：可选的日期（不可选的是 date-item-disabled）"),
    "schedule_time": Selector(".time-picker .date-picker-timer", "定时发布区块内：时间下拉"),
    "schedule_time_panel": Selector(".time-picker .time-picker-container", "定时发布区块内：时间面板"),
    "schedule_column": Selector(".time-picker .time-picker-panel-select-wrp", "时间面板：小时列、分钟列"),
    "schedule_column_item": Selector(".time-picker-panel-select-item", "时间面板：一个小时或分钟（不可选的带 time-select-disabled）"),
    # 提交区：页面底部同时有「存草稿」和「立即投稿」，只用来定位和滚动，永不点击
    "submit": Selector(".submit-container .submit-add", "「立即投稿」按钮（只定位，不点击）"),
}

# 已知无害、可以用右上角 x 关闭的弹窗（按弹窗文字匹配）。不点「知道了」，它可能触发浏览器通知授权。
BENIGN_DIALOG_TEXTS = ("开启后视频上传完成第一时间通知",)
# 本工具自己打开的弹窗；步骤失败时用 x 关掉，免得挡住后续步骤
OWN_DIALOG_TEXTS = ("封面制作", "上传字幕", "章节")

# 守卫的限定放行：只有同时满足选择器、精确文字、所在弹窗文字时才放行，
# 且所在弹窗不得包含页面级提交按钮的文字。
GUARD_EXCEPTIONS = (
    {"css": ".cover-editor-content .cover-editor-button .button.submit", "text": "完成", "dialog_text": "封面制作"},
)


def css(name: str) -> str:
    return SELECTORS[name].css
