"""按计划填写投稿表单，读回核对，停在「立即投稿」之前。

所有点击、按键都经过 guard。找不到的选择器写入 missing_selectors，
该步骤跳过，不猜测替代元素。函数结束时只断开 CDP 连接，标签页留给人。
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any

from .guard import focus_editable, safe_click, safe_fill, safe_insert_text, safe_press
from .meta import UploadMeta, picker_time, schedule_window_problem
from .plan import ALWAYS_HUMAN, SCHEDULE_HUMAN_STEP
from .selectors import BENIGN_DIALOG_TEXTS, OWN_DIALOG_TEXTS, SELECTORS, UPLOAD_URL, css

COVER_SLOT_4X3 = "首页推荐封面（4:3）"
COVER_SLOT_16X9 = "个人空间封面（16:9）"


class Form:
    def __init__(self, page):
        self.page = page
        self.filled: list[str] = []
        self.skipped: list[dict[str, str]] = []
        self.missing: dict[str, dict[str, str]] = {}
        self.human: list[str] = []
        self.unknown_dialogs: list[str] = []
        self.warnings: list[str] = []

    def mark_missing(self, name: str) -> None:
        self.missing[name] = {"css": SELECTORS[name].css, "note": SELECTORS[name].note}

    def find(self, name: str, timeout: float = 5000, state: str = "visible", root=None):
        loc = (root or self.page).locator(css(name))
        try:
            loc.first.wait_for(state=state, timeout=timeout)
            return loc
        except Exception:  # noqa: BLE001 - 超时即视为缺失
            self.mark_missing(name)
            return None

    def skip(self, step: str, reason: str) -> None:
        self.skipped.append({"step": step, "reason": reason})

    def run(self, step: str, fn) -> None:
        try:
            dismiss_dialogs(self)
            ok = fn()
            if ok is False:
                if not any(s["step"] == step for s in self.skipped):
                    self.skip(step, "required element not found (see missing_selectors)")
                close_own_dialogs(self)
                return
            self.filled.append(step)
        except Exception as e:  # noqa: BLE001 - 每一步独立失败，汇总报告
            msg = str(e).splitlines()[0][:200] if str(e) else ""
            self.skip(step, f"{type(e).__name__}: {msg}")
            try:
                close_own_dialogs(self)
            except Exception:  # noqa: BLE001
                pass


def visible_dialog_handles(page) -> list[tuple[Any, str]]:
    """可见弹窗的 ElementHandle 与文字。用句柄而不是 nth()，避免弹窗增减时点错对象。"""
    out = []
    for h in page.locator(css("dialog")).element_handles():
        try:
            if h.is_visible():
                out.append((h, re.sub(r"\s+", " ", h.inner_text()).strip()))
        except Exception:  # noqa: BLE001 - 弹窗在检查过程中消失
            continue
    return out


def _close_dialog(handle) -> bool:
    x = handle.query_selector(css("dialog_close"))
    if x is None:
        return False
    safe_click(x)
    return True


def dismiss_dialogs(form: Form) -> None:
    """关掉已知无害的弹窗（用 x，不点「知道了」）；其他可见弹窗按文字报告，不动它。"""
    for handle, text in visible_dialog_handles(form.page):
        if any(t in text for t in BENIGN_DIALOG_TEXTS):
            try:
                if _close_dialog(handle):
                    form.page.wait_for_timeout(500)
                    continue
            except Exception:  # noqa: BLE001
                pass
        if any(t in text for t in OWN_DIALOG_TEXTS):
            continue  # 本工具自己的弹窗由对应步骤处理
        short = text[:80]
        if short and short not in form.unknown_dialogs:
            form.unknown_dialogs.append(short)


def close_own_dialogs(form: Form) -> None:
    """步骤失败后，用 x 关掉本工具打开的弹窗，免得挡住后续步骤。"""
    for handle, text in visible_dialog_handles(form.page):
        if any(t in text for t in OWN_DIALOG_TEXTS):
            try:
                _close_dialog(handle)
                form.page.wait_for_timeout(500)
            except Exception:  # noqa: BLE001
                pass


def _dialog_with(page, marker: str, timeout_ms: float = 10000):
    """等待并返回文字含 marker 的可见弹窗（按文字筛选的 Locator，不依赖位置）。"""
    loc = page.locator(css("dialog")).filter(has_text=marker).filter(visible=True).first
    try:
        loc.wait_for(state="visible", timeout=timeout_ms)
        return loc
    except Exception:  # noqa: BLE001
        return None


def _clear_and_type_quill(page, editor_locator, text: str) -> None:
    handle = focus_editable(editor_locator)
    safe_press(page, handle, "ControlOrMeta+a")
    safe_press(page, handle, "Backspace")
    for i, line in enumerate(text.split("\n")):
        if i:
            safe_press(page, handle, "Enter")
        if line:
            safe_insert_text(page, handle, line)


def _norm_text(s: str | None) -> str:
    return re.sub(r"\n+", "\n", (s or "").replace("\r", "")).strip()


def _exact(text: str) -> re.Pattern:
    return re.compile(rf"^\s*{re.escape(text)}\s*$")


def wait_page_settled(page, idle_ms: float = 15000, extra_ms: float = 2000) -> None:
    """等上传组件加载完再选文件。太早选文件时组件报错
    (Cannot read properties of undefined (reading 'upload'))，条目停在 0.0MB/0.0MB 永远不动。"""
    try:
        page.wait_for_load_state("networkidle", timeout=idle_ms)
    except Exception:  # noqa: BLE001 - 页面有长连接时等不到 networkidle，退回固定等待
        pass
    page.wait_for_timeout(extra_ms)


def select_file_via_chooser(page, click_locator, path, accept_hint: str, timeout_ms: float = 15000) -> None:
    """点击上传区域，拦截它弹出的文件选择框，让 Chrome 直接从本机磁盘读取文件。

    connect_over_cdp 接入的浏览器在 Playwright 看来是「远程」的，set_input_files 会把文件
    内容经 CDP 传过去，并且限制在 50 MB 以内，真实视频几乎都超过。直接对输入框调用
    DOM.setFileInputFiles 时 B 站的上传组件也不会响应。可行的做法是：开启
    Page.setInterceptFileChooserDialog，经守卫点击上传区域，收到 Page.fileChooserOpened
    后对它给出的 backendNodeId 调用 DOM.setFileInputFiles，只传绝对路径。
    前提是 Chrome 和本工具在同一台机器上。
    """
    from pathlib import Path

    abs_path = str(Path(path).expanduser().resolve())
    cdp = page.context.new_cdp_session(page)
    events: list[dict[str, Any]] = []
    cdp.on("Page.fileChooserOpened", lambda e: events.append(e))
    try:
        cdp.send("Page.enable")
        cdp.send("Page.setInterceptFileChooserDialog", {"enabled": True})
        safe_click(click_locator)
        deadline = time.monotonic() + timeout_ms / 1000
        while not events and time.monotonic() < deadline:
            page.wait_for_timeout(100)
        if not events:
            raise RuntimeError("clicking the upload area did not open a file chooser")
        node = events[0].get("backendNodeId")
        if node is None:
            raise RuntimeError("file chooser event carried no backendNodeId")
        obj = cdp.send("DOM.resolveNode", {"backendNodeId": node})["object"]["objectId"]
        info = cdp.send("Runtime.callFunctionOn", {
            "objectId": obj, "returnByValue": True,
            "functionDeclaration": "function () { return {tag: this.tagName, type: this.type || '', "
                                   "accept: (this.accept || '').toLowerCase()}; }",
        })["result"]["value"]
        if info.get("tag") != "INPUT" or info.get("type") != "file" or accept_hint not in info.get("accept", ""):
            raise RuntimeError(f"file chooser input does not look right: {info}")
        cdp.send("DOM.setFileInputFiles", {"files": [abs_path], "backendNodeId": node})
    finally:
        # 清理失败不能掩盖结果：文件可能已经选上，调用方据此决定是否关标签页
        for fn in (lambda: cdp.send("Page.setInterceptFileChooserDialog", {"enabled": False}), cdp.detach):
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------- 各字段步骤

def step_title(form: Form, meta: UploadMeta):
    if form.find("title", timeout=60000) is None:
        return False
    handle = safe_fill(form.page.locator(css("title")), meta.title)  # fill 会替换自动带入的文件名
    if handle.input_value() != meta.title:
        raise RuntimeError("title readback differs after fill")


def _set_cover_slot(form: Form, dialog, slot_text: str, path) -> None:
    slot = dialog.get_by_text(slot_text, exact=True)
    if not slot.count():
        raise RuntimeError(f"cover slot {slot_text!r} not found in the cover dialog")
    safe_click(slot)
    form.page.wait_for_timeout(500)
    inp = form.find("cover_file_input", timeout=5000, state="attached", root=dialog)
    if inp is None:
        raise RuntimeError("image file input not found in the cover dialog")
    inp.first.set_input_files(str(path))  # 封面是小文件，Playwright 自带方式即可
    form.page.wait_for_timeout(2500)


def step_cover(form: Form, meta: UploadMeta):
    cover = form.find("cover")
    if cover is None:
        return False
    if form.page.locator(css("cover_disabled")).count():
        raise RuntimeError("cover slot is disabled (B站 may still be processing the video); "
                           "retry with --reuse-tab after the upload finishes")
    safe_click(cover)
    dialog = _dialog_with(form.page, "封面制作")
    if dialog is None:
        raise RuntimeError("cover dialog (封面制作) did not open")
    four_three = meta.cover_4x3 or meta.cover
    if four_three:
        _set_cover_slot(form, dialog, COVER_SLOT_4X3, four_three)
        if meta.cover_4x3 is None:
            form.human.append("4:3 首页推荐封面用的是 16:9 图片，B 站会裁掉两侧，请检查")
    if meta.cover:
        _set_cover_slot(form, dialog, COVER_SLOT_16X9, meta.cover)
    confirm = dialog.locator(css("cover_confirm")).filter(has_text=_exact("完成"))
    if not confirm.count():
        form.mark_missing("cover_confirm")
        raise RuntimeError("cover dialog: 完成 not found")
    safe_click(confirm)  # 守卫对这一个按钮有限定范围的放行
    form.page.wait_for_timeout(1500)
    if _dialog_with(form.page, "封面制作", timeout_ms=1000) is not None:
        raise RuntimeError("cover dialog still open after 完成")
    form.human.append("核对封面（4:3 与 16:9 两个位置）")


def step_statement(form: Form, meta: UploadMeta):
    box = form.find("statement_input", state="attached")
    if box is None:
        return False
    if box.first.input_value() == meta.creation_statement:
        return None
    trigger = form.find("statement_trigger")
    if trigger is None:
        return False
    safe_click(trigger)
    if form.find("statement_option") is None:
        return False
    opts = form.page.locator(css("statement_option")).filter(has_text=_exact(meta.creation_statement))
    if not opts.count():
        raise RuntimeError(f"option {meta.creation_statement!r} not in the statement dropdown")
    safe_click(opts)
    form.page.wait_for_timeout(500)
    if box.first.input_value() != meta.creation_statement:
        raise RuntimeError("creation statement did not change after choosing the option")


def step_partition(form: Form, meta: UploadMeta):
    ctl = form.find("partition_controller")
    if ctl is None:
        return False
    val = form.page.locator(css("partition_value"))
    if val.count() and val.first.inner_text().strip() == meta.partition:
        return None
    safe_click(ctl)
    if form.find("partition_option") is None:
        return False
    opt = form.page.locator(css("partition_option")).filter(has_text=_exact(meta.partition))
    if not opt.count():
        raise RuntimeError(f"partition option {meta.partition!r} not found")
    safe_click(opt)
    form.page.wait_for_timeout(500)


def read_tags(page) -> list[str]:
    return [t.strip() for t in page.locator(css("tag_item")).all_inner_texts() if t.strip()]


def step_tags(form: Form, meta: UploadMeta):
    if form.find("tag_input") is None:
        return False
    # B 站会按内容自动带入标签：先删掉元数据之外的标签
    for _ in range(20):
        existing = [t.strip() for t in form.page.locator(css("tag_item")).all_inner_texts()]  # 不丢空项，保持下标对齐
        extra = [i for i, t in enumerate(existing) if t not in meta.tags]
        if not extra:
            break
        closes = form.page.locator(css("tag_close")).element_handles()
        if len(closes) != len(existing):
            form.mark_missing("tag_close")
            raise RuntimeError("cannot locate the delete button of each existing tag")
        safe_click(closes[extra[0]])
        form.page.wait_for_timeout(300)
    else:
        raise RuntimeError(f"could not remove auto-filled tags: {[t for t in read_tags(form.page) if t not in meta.tags]}")
    for tag in meta.tags:
        if tag in read_tags(form.page):
            continue
        handle = safe_fill(form.page.locator(css("tag_input")), tag)
        safe_press(form.page, handle, "Enter")
        form.page.wait_for_timeout(500)
    rejected = [t for t in meta.tags if t not in read_tags(form.page)]
    if rejected:  # B 站会静默拒收部分标签，不报错
        form.warnings.append(f"tags not accepted by Bilibili: {rejected}")
        form.human.append(f"这些标签没有被 B 站接受（页面无提示）：{rejected}")


def step_description(form: Form, meta: UploadMeta):
    if form.find("desc_editor") is None:
        return False
    _clear_and_type_quill(form.page, form.page.locator(css("desc_editor")), meta.description)


def expand_more_settings(form: Form) -> bool:
    more = form.page.locator(css("more_settings"))
    if more.count() and more.first.is_visible():
        return True
    toggle = form.page.locator(css("more_settings_toggle")).filter(has_text="更多设置")
    if not toggle.count():
        form.mark_missing("more_settings_toggle")
        return False
    safe_click(toggle)
    return form.find("more_settings") is not None


def step_visibility(form: Form, meta: UploadMeta):
    if not expand_more_settings(form):
        return False
    if form.find("visibility_radio") is None:
        return False
    label = "公开可见" if meta.visibility == "public" else "仅自己可见"
    radio = form.page.locator(css("visibility_radio")).filter(has_text=label)
    if not radio.count():
        raise RuntimeError(f"visibility option {label!r} not found")
    safe_click(radio)


def step_dynamic(form: Form, meta: UploadMeta):
    if not expand_more_settings(form):
        return False
    if form.find("dynamic_editor") is None:
        return False
    _clear_and_type_quill(form.page, form.page.locator(css("dynamic_editor")), meta.dynamic)


def subtitle_chooser_ok(inside_dialog: bool, detached: bool, accept: str, name: str) -> bool:
    """纯函数：字幕弹窗弹出的文件选择框是不是字幕输入框，而不是视频上传器。"""
    if name == "buploader":
        return False
    if inside_dialog:
        return not accept or ".srt" in accept
    return detached and ".srt" in accept


def step_subtitles(form: Form, meta: UploadMeta):
    if not expand_more_settings(form):
        return False
    dialog = form.page.locator(css("subtitle_dialog")).filter(visible=True).first
    if not dialog.count():  # 上一次运行留下的弹窗还开着时直接接着用
        btn = form.find("subtitle_button")
        if btn is None:
            return False
        safe_click(btn)
    try:
        dialog.wait_for(state="visible", timeout=10000)
    except Exception:  # noqa: BLE001
        form.mark_missing("subtitle_dialog")
        return False
    lang = form.find("subtitle_lang", root=dialog)
    if lang is None:
        return False
    safe_click(lang)
    opt = dialog.locator(css("subtitle_lang_option")).filter(has_text=_exact(meta.subtitles.language))
    if not opt.count():
        raise RuntimeError(f"subtitle language {meta.subtitles.language!r} not offered")
    safe_click(opt)
    up = form.find("subtitle_file_button", root=dialog)
    if up is None:
        return False
    with form.page.expect_file_chooser(timeout=10000) as fc:
        safe_click(up)
    chooser = fc.value
    accept = (chooser.element.get_attribute("accept") or "").lower()
    name = chooser.element.get_attribute("name") or ""
    inside = chooser.element.evaluate("(el, d) => d.contains(el)", dialog.element_handle())
    # 现在的页面点「上传文件」时临时创建一个不挂到文档里的 input；这种游离的输入框只在明确接受 .srt 时放行
    detached = chooser.element.evaluate("(el) => !el.isConnected")
    if not subtitle_chooser_ok(inside, detached, accept, name):
        raise RuntimeError(f"file chooser is not the subtitle input (inside_dialog={inside}, detached={detached}, "
                           f"accept={accept!r}, name={name!r})")
    chooser.set_files(str(meta.subtitles.path))  # 字幕是小文件
    confirm = dialog.locator(css("subtitle_confirm")).filter(has_text="确认")
    if not confirm.count():
        form.mark_missing("subtitle_confirm")
        raise RuntimeError("subtitle dialog: 确认 not found")
    confirm.first.wait_for(state="visible", timeout=5000)
    for _ in range(20):  # 选好文件后「确认」才可用
        if confirm.first.is_enabled():
            break
        form.page.wait_for_timeout(500)
    pinned = dialog.element_handle()  # 固定这一个弹窗：内容切换后 :has() 选择器可能不再匹配，那不代表弹窗关了
    safe_click(confirm)
    try:  # 字幕上传完弹窗才关；关得慢时回读会误报没上传
        pinned.wait_for_element_state("hidden", timeout=15000)
    except Exception:  # noqa: BLE001
        form.warnings.append("subtitle dialog still open 15 s after 确认; check the subtitle section")
    if not meta.subtitles.default_on:
        form.human.append("表单里没有字幕「对观众默认开启/关闭」的设置；如需确认，投稿后去字幕管理或播放页检查")


def _schedule_shown(box) -> list[str]:
    return [t.strip() for t in box.locator(css("schedule_shown")).all_inner_texts()]


def _calendar_month(title: str) -> tuple[int, int] | None:
    m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月", title or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def _close_panel(form: Form, box, panel: str, opener: str) -> None:
    if box.locator(css(panel)).filter(visible=True).count():
        safe_click(box.locator(css(opener)))
        form.page.wait_for_timeout(300)
    if box.locator(css(panel)).filter(visible=True).count():  # 开着的面板会挡住后面的步骤
        raise RuntimeError(f"{panel} did not close")


def step_schedule(form: Form, meta: UploadMeta):
    """打开「定时发布」并选好日期、时间。只在选择器显示北京时间（默认）时操作，不改时区。"""
    problem = schedule_window_problem(meta.schedule, datetime.now(timezone.utc))
    if problem:
        raise RuntimeError(problem)
    want = picker_time(meta.schedule)
    box = form.page.locator(css("schedule_container")).filter(visible=True).first
    try:  # 批量操作弹窗里藏着一份同名区块，可能排在前面：只认可见的
        box.wait_for(state="visible", timeout=5000)
    except Exception:  # noqa: BLE001
        form.mark_missing("schedule_container")
        return False
    switch = box.locator(css("schedule_switch")).first
    if "switch-container-active" not in (switch.get_attribute("class") or ""):
        safe_click(switch)
    if form.find("schedule_timezone", timeout=5000, root=box) is None:
        return False
    tz = box.locator(css("schedule_timezone")).first.input_value()
    if not tz.startswith("(UTC+08:00)"):
        raise RuntimeError(f"schedule picker time zone is {tz!r}; this tool only sets times while it shows (UTC+08:00)")

    if _schedule_shown(box)[:1] != [want["date"]]:
        safe_click(box.locator(css("schedule_date")))
        title = box.locator(css("schedule_month_title")).first
        title.wait_for(state="visible", timeout=5000)
        target = (int(want["date"][:4]), int(want["date"][5:7]))
        for _ in range(3):  # 日历可能停在目标之前或之后的月份（上一次运行选过别的日期）
            shown_month = _calendar_month(title.inner_text())
            if shown_month == target:
                break
            go = "schedule_next_month" if shown_month is None or shown_month < target else "schedule_prev_month"
            safe_click(box.locator(css(go)))
            form.page.wait_for_timeout(300)
        if _calendar_month(title.inner_text()) != target:
            raise RuntimeError(f"calendar did not reach {target[0]}年{target[1]}月")
        day = box.locator(css("schedule_day")).filter(has_text=_exact(str(int(want["date"][8:]))))
        if day.count() != 1:
            raise RuntimeError(f"day {want['date']} is not selectable in the calendar")
        safe_click(day)
        form.page.wait_for_timeout(500)
        _close_panel(form, box, "schedule_date_panel", "schedule_date")

    if _schedule_shown(box)[1:2] != [want["time"]]:
        safe_click(box.locator(css("schedule_time")))
        cols = box.locator(css("schedule_column"))
        cols.first.wait_for(state="visible", timeout=5000)
        for i, value in enumerate(want["time"].split(":")):  # 先小时后分钟：分钟是否可选取决于小时
            item = cols.nth(i).locator(css("schedule_column_item")).filter(has_text=_exact(value))
            if item.count() != 1 or "disabled" in (item.first.get_attribute("class") or ""):
                raise RuntimeError(f"{'hour' if i == 0 else 'minute'} {value} is not selectable")
            safe_click(item)
            form.page.wait_for_timeout(300)
        _close_panel(form, box, "schedule_time_panel", "schedule_time")

    shown = _schedule_shown(box)
    if shown[:2] != [want["date"], want["time"]]:
        raise RuntimeError(f"schedule picker shows {shown}, expected {[want['date'], want['time']]}")
    form.human.append(SCHEDULE_HUMAN_STEP)


def chapters_text(meta: UploadMeta) -> str:
    """章节文本编辑器接受的格式：每行「MM:SS 标题」（超过 1 小时为 HH:MM:SS）。"""
    return "\n".join(f"{c.timestamp} {c.title}" for c in meta.chapters)


def step_chapters(form: Form, meta: UploadMeta):
    if not expand_more_settings(form):
        return False
    if form.find("chapter_button") is None:
        return False
    btn = form.page.locator(css("chapter_button")).filter(has_text="编辑章节")
    if not btn.count():
        raise RuntimeError("编辑章节 button not found")
    if btn.first.is_disabled():
        raise RuntimeError("编辑章节 is disabled (usually until the upload has been processed)")
    safe_click(btn)
    if form.find("chapter_iframe", timeout=15000) is None:
        return False
    # iframe 内的元素同样经过守卫；守卫的 DOM 检查只看得到 iframe 自己的文档，
    # 跨文档的遮挡由 Playwright 点击前的命中检查兜底。
    frame = form.page.locator(css("chapter_iframe")).first.element_handle().content_frame()
    if frame is None:
        raise RuntimeError("chapter iframe has no frame")
    mode = frame.locator(css("chapter_text_mode"))
    mode.first.wait_for(state="visible", timeout=15000)
    safe_click(mode)
    area = form.find("chapter_textarea", root=frame)
    if area is None:
        return False
    safe_fill(frame.locator(css("chapter_textarea")), chapters_text(meta))
    convert = form.find("chapter_convert", root=frame)
    if convert is None:
        return False
    safe_click(convert)
    form.page.wait_for_timeout(1000)
    err = frame.get_by_text("请保证章节名称字数不超过16字")
    if err.count() and err.first.is_visible():
        raise RuntimeError("Bilibili rejected the chapters: 请保证章节名称字数不超过16字")
    save = form.find("chapter_save", root=frame)
    if save is None:
        return False
    safe_click(save)
    form.page.wait_for_timeout(2000)


# ---------------------------------------------------------------- 上传状态

_UPLOAD_JS = """(sel) => {
  const items = Array.from(document.querySelectorAll(sel));
  const text = items.map(e => e.innerText).join(' | ').replace(/\\s+/g, ' ').trim();
  return {items: items.length, text};
}"""

_ZERO_TOTAL = re.compile(r"/\s*0(?:\.0+)?\s*MB")
_IN_PROGRESS = re.compile(r"上传中|处理中|转码中|(?<![\d.])(?:\d|[1-9]\d)(?:\.\d+)?%")


def classify_upload(items: int, text: str) -> dict[str, Any]:
    """纯函数：根据上传条目文字判断状态。"""
    failed = bool(re.search(r"失败|错误", text))
    in_progress = bool(_IN_PROGRESS.search(text))
    done = items > 0 and not failed and not in_progress and bool(re.search(r"上传完成|已完成|处理完成|100(?:\.0+)?%", text))
    # 文件总大小显示为 0：上传组件没接住文件（常见于页面还没加载完就选了文件），会一直停在 0%
    stalled = not done and bool(_ZERO_TOTAL.search(text))
    return {"items": items, "text": text, "done": done, "failed": failed, "in_progress": in_progress,
            "stalled": stalled}


def upload_state(page, full_text: bool = False) -> dict[str, Any]:
    st = page.evaluate(_UPLOAD_JS, css("upload_item"))
    out = classify_upload(st.get("items", 0), st.get("text", ""))
    if not full_text:
        out["text"] = out["text"][:300]
    return out


def wait_upload(page, timeout_s: float, form: Form | None = None, grace_s: float = 30) -> dict[str, Any]:
    start = time.monotonic()
    st = upload_state(page)
    while not st["done"] and not st["failed"] and time.monotonic() - start < timeout_s:
        if st["items"] == 0 and time.monotonic() - start > grace_s:
            if form is not None:
                form.mark_missing("upload_item")
            break
        if st["stalled"] and time.monotonic() - start > grace_s:
            if form is not None:
                form.warnings.append("upload stalled at 0.0MB/0.0MB: the upload widget did not take the file; "
                                     "ask the human before closing this tab, then select the video again in a fully loaded page")
            break
        page.wait_for_timeout(5000)
        st = upload_state(page)
    st["timed_out"] = not st["done"] and not st["failed"] and not st["stalled"]
    return st


# ---------------------------------------------------------------- 读回

_READ_JS = """(s) => {
  const q = (c) => document.querySelector(c);
  const txt = (c) => { const e = q(c); return e ? e.innerText.trim() : null; };
  const val = (c) => { const e = q(c); return e ? e.value : null; };
  const txtWith = (c, marker) => {
    const e = Array.from(document.querySelectorAll(c)).find(x => (x.innerText || '').includes(marker));
    return e ? e.innerText.replace(/\\s+/g, ' ').trim() : null;
  };
  return {
    title: val(s.title),
    creation_statement: val(s.statement_input),
    partition: txt(s.partition_value),
    tags: q(s.tag_input) ? Array.from(document.querySelectorAll(s.tag_item)).map(e => e.innerText.trim()).filter(Boolean) : null,
    description: txt(s.desc_editor),
    visibility: txt(s.visibility_checked),
    dynamic: txt(s.dynamic_editor),
    subtitles_section: txt(s.subtitle_section),
    chapters_section: txtWith(s.chapter_section, '章节管理'),
    schedule: (() => {
      const box = Array.from(document.querySelectorAll(s.schedule_container)).find(e => e.getClientRects().length);
      if (!box) return null;
      const sw = box.querySelector(s.schedule_switch);
      if (!sw || !sw.className.includes('switch-container-active')) return 'off';
      const tz = box.querySelector(s.schedule_timezone);
      const shown = Array.from(box.querySelectorAll(s.schedule_shown)).map(e => e.innerText.trim());
      return shown.join(' ') + ' ' + (tz ? tz.value : '');
    })(),
  };
}"""

# 读回字段 -> 对应选择器名（读回为 null 时记为缺失）
_READ_SELECTORS = {
    "title": "title", "creation_statement": "statement_input", "partition": "partition_value",
    "tags": "tag_input", "description": "desc_editor", "visibility": "visibility_checked",
    "dynamic": "dynamic_editor", "subtitles_section": "subtitle_section", "chapters_section": "chapter_section",
    "schedule": "schedule_container",
}


def compare(got: dict[str, Any], meta: UploadMeta) -> tuple[dict[str, Any], list[str]]:
    """纯函数：把读回值与元数据比对，返回 (mismatches, 读回为空的选择器名)。

    标签：页面上多出元数据之外的标签算不符；元数据里的标签被 B 站静默拒收不算不符
    （由 step_tags 作为 warning 报告）。
    """
    mismatches: dict[str, Any] = {}
    missing: list[str] = []
    wanted = {"title", "creation_statement", "visibility"}
    wanted |= {k for k, on in (("partition", meta.partition), ("tags", meta.tags),
                               ("description", meta.description), ("dynamic", meta.dynamic),
                               ("subtitles_section", meta.subtitles), ("chapters_section", meta.chapters),
                               ("schedule", meta.schedule)) if on}

    def cmp(key: str, ok: bool, expected: Any) -> None:
        if got.get(key) is None:
            missing.append(_READ_SELECTORS[key])
            mismatches[key] = {"expected": expected, "actual": None}
        elif not ok:
            mismatches[key] = {"expected": expected, "actual": got.get(key)}

    for key in sorted(wanted):
        v = got.get(key)
        if key == "title":
            cmp(key, v == meta.title, meta.title)
        elif key == "creation_statement":
            cmp(key, v == meta.creation_statement, meta.creation_statement)
        elif key == "partition":
            cmp(key, (v or "").strip() == meta.partition, meta.partition)
        elif key == "tags":
            page_tags = v or []
            ok = all(t in meta.tags for t in page_tags)  # 不比较顺序：自动带入且在元数据里的标签保留原位
            cmp(key, ok, meta.tags)
        elif key == "description":
            cmp(key, _norm_text(v) == _norm_text(meta.description), "(see metadata)")
        elif key == "visibility":
            vis = "公开可见" if meta.visibility == "public" else "仅自己可见"
            cmp(key, v == vis, vis)
        elif key == "dynamic":
            cmp(key, _norm_text(v) == _norm_text(meta.dynamic), meta.dynamic)
        elif key == "subtitles_section":
            lang = meta.subtitles.language
            cmp(key, "已上传" in (v or "") and lang in (v or ""), f"已上传【{lang}】字幕")
        elif key == "chapters_section":
            cmp(key, "已配置章节" in (v or ""), "已配置章节")
        elif key == "schedule":
            w = picker_time(meta.schedule)
            expected = f"{w['date']} {w['time']} (UTC+08:00)"
            cmp(key, (v or "").startswith(expected), expected)
    return mismatches, sorted(set(missing))


def readback(page, meta: UploadMeta) -> dict[str, Any]:
    got = page.evaluate(_READ_JS, {k: v.css for k, v in SELECTORS.items()})
    mismatches, missing = compare(got, meta)
    if got.get("description") and len(got["description"]) > 120:
        got["description"] = got["description"][:120] + "…"
    rejected = [t for t in meta.tags if got.get("tags") is not None and t not in got["tags"]]
    return {"values": got, "mismatches": mismatches, "missing": missing, "tags_not_accepted": rejected}


# ---------------------------------------------------------------- 入口

def find_upload_tabs(ctx) -> list:
    """已经选好视频（标题框已渲染）的投稿标签页，新的在前。"""
    return [pg for pg in reversed(ctx.pages)
            if pg.url.startswith(UPLOAD_URL) and pg.locator(css("title")).count()]


def tab_matches_video(text: str, title_value: str | None, video, title: str | None = None) -> bool:
    """纯函数：这个标签页是否在处理这个视频。

    依据（整词相等，不做子串匹配）：上传条目文字里有完整文件名或去掉扩展名的文件名；
    或者标题框里是 B 站自动带入的文件名（不含扩展名）；或者标题框已经是元数据里的标题。
    """
    tokens = {t for t in re.split(r"[\s|]+", text or "") if t}
    if video.name in tokens or video.stem in tokens:
        return True
    tv = (title_value or "").strip()
    return bool(tv) and (tv in (video.stem, video.name) or (title is not None and tv == title))


def _title_value(pg) -> str | None:
    loc = pg.locator(css("title"))
    try:
        return loc.first.input_value(timeout=2000) if loc.count() else None
    except Exception:  # noqa: BLE001
        return None


def matching_upload_tabs(ctx, video, title: str | None = None) -> list:
    return [pg for pg in find_upload_tabs(ctx)
            if tab_matches_video(upload_state(pg, full_text=True)["text"], _title_value(pg), video, title)]


def find_upload_tab(ctx, video=None, title: str | None = None):
    """恰好一个标签页匹配时返回它；零个或多个都返回 None（多个时不替人选）。"""
    if video is None:
        tabs = find_upload_tabs(ctx)
        return tabs[0] if len(tabs) == 1 else None
    tabs = matching_upload_tabs(ctx, video, title)
    return tabs[0] if len(tabs) == 1 else None


def describe_upload_tabs(ctx) -> list[dict[str, Any]]:
    return [{"upload_item_text": upload_state(pg)["text"][:120], "title_box": (_title_value(pg) or "")[:80]}
            for pg in find_upload_tabs(ctx)]


ASK_HUMAN = ("ask the human which tab holds this video; do not start another upload "
             "(--new-upload only when the human explicitly asks for a second upload)")


def execute(session, meta: UploadMeta, reuse_tab: bool, upload_timeout_s: float,
            wait_for_upload: bool = True, new_upload: bool = False) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    from .browser import check_login, connect, verify_own_browser

    if meta.schedule:  # 在选文件之前拒绝已经不合规的定时，免得白白开始上传
        problem = schedule_window_problem(meta.schedule, datetime.now(timezone.utc))
        if problem:
            return {"ok": False, "error": problem, "next": "fix schedule in the metadata and run again"}
    own = verify_own_browser(session)
    if not own["ok"]:
        return own
    with sync_playwright() as p:
        browser, ctx = connect(p, session)
        if reuse_tab:
            page = find_upload_tab(ctx, meta.video, meta.title)
            if page is None:
                tabs = describe_upload_tabs(ctx)
                n = len(matching_upload_tabs(ctx, meta.video, meta.title))
                return {"ok": False, "error": (f"{n} upload tabs match {meta.video.name!r}; refusing to choose" if n > 1
                                               else f"no upload tab matches {meta.video.name!r}"),
                        "upload_tabs": tabs, "next": ASK_HUMAN if tabs else
                        "no upload tab is open; only then is a run without --reuse-tab appropriate"}
            form = Form(page)
        else:
            if find_upload_tabs(ctx) and not new_upload:
                return {"ok": False, "error": "an upload tab with a selected video already exists",
                        "upload_tabs": describe_upload_tabs(ctx),
                        "next": "continue it with --reuse-tab; if it holds a different video, " + ASK_HUMAN}
            page = ctx.new_page()
            form = Form(page)
            try:
                page.goto(UPLOAD_URL, wait_until="domcontentloaded")
                login = check_login(page)
                if login.get("logged_in") is not True:  # 保留这个标签页，人可以在里面扫码登录
                    return {"ok": False, "error": "not logged in; ask the human to log in (QR scan) in the opened tab",
                            **login}
                if form.find("upload_area", timeout=20000) is None:
                    page.close()
                    return {"ok": False, "error": "upload area not found", "missing_selectors": form.missing}
                wait_page_settled(page)
                select_file_via_chooser(page, page.locator(css("upload_area")), meta.video, ".mp4")  # 上传从这里开始
            except Exception as e:  # noqa: BLE001 - 文件没选上：关掉自己开的标签页，不留空页
                try:
                    if not page.is_closed() and not page.locator(css("title")).count():
                        page.close()
                except Exception:  # noqa: BLE001 - 页面已崩溃或跳走：保持原样，交给人
                    pass
                return {"ok": False, "video_selected": None if not page.is_closed() else False,
                        "error": f"{type(e).__name__}: {e}"}
            form.filled.append("select_video")
        page.bring_to_front()

        upload: dict[str, Any] = {}
        check: dict[str, Any] = {"values": {}, "mismatches": {}, "missing": []}
        submit_visible = False
        error = None
        try:
            form.run("title", lambda: step_title(form, meta))
            if meta.cover or meta.cover_4x3:
                form.run("cover", lambda: step_cover(form, meta))
            form.run("creation_statement", lambda: step_statement(form, meta))
            if meta.partition:
                form.run("partition", lambda: step_partition(form, meta))
            if meta.tags:
                form.run("tags", lambda: step_tags(form, meta))
            if meta.description:
                form.run("description", lambda: step_description(form, meta))
            form.run("visibility", lambda: step_visibility(form, meta))
            if meta.dynamic:
                form.run("dynamic", lambda: step_dynamic(form, meta))
            if meta.schedule:
                form.run("schedule", lambda: step_schedule(form, meta))
            if meta.subtitles:
                form.run("subtitles", lambda: step_subtitles(form, meta))
            upload = wait_upload(page, upload_timeout_s if wait_for_upload else 0, form)
            if meta.chapters:
                form.run("chapters", lambda: step_chapters(form, meta))
            check = readback(page, meta)
            for name in check["missing"]:
                form.mark_missing(name)
            dismiss_dialogs(form)
            submit = page.locator(css("submit"))
            if submit.count():
                submit.first.scroll_into_view_if_needed()  # 只滚动，不点击
                submit_visible = submit.first.is_visible()
            else:
                form.mark_missing("submit")
        except Exception as e:  # noqa: BLE001 - 文件已选，必须返回部分报告
            error = f"{type(e).__name__}: {str(e).splitlines()[0][:200] if str(e) else ''}"

        human = form.human + list(ALWAYS_HUMAN)
        for s in form.skipped:
            human.insert(0, f"手动完成或重试：{s['step']}（{s['reason']}）")
        out = {
            "ok": error is None and not form.skipped and not form.missing and not check["mismatches"],
            "video_selected": True,
            "filled": form.filled,
            "skipped": form.skipped,
            "missing_selectors": form.missing,
            "unknown_dialogs": form.unknown_dialogs,
            "warnings": form.warnings,
            "tags_not_accepted": check.get("tags_not_accepted", []),
            "upload": upload,
            "readback": check["values"],
            "mismatches": check["mismatches"],
            "submit_button_visible": submit_visible,
            "submit_clicked": False,
            "tab_url": page.url.split("?")[0],
            "human_steps": human,
            "next": "如需重试，用 --reuse-tab 继续这个标签页，不要重新选择文件",
        }
        if error:
            out["error"] = error
        return out
