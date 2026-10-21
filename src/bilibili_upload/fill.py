"""按计划填写投稿表单，读回核对，停在「立即投稿」之前。

所有点击都经过 guard.safe_click。找不到的选择器写入 missing_selectors，
该步骤跳过，不猜测替代元素。函数结束时只断开 CDP 连接，标签页留给人。
"""

from __future__ import annotations

import re
import time
from typing import Any

from .guard import safe_click
from .meta import UploadMeta, format_timestamp
from .selectors import SELECTORS, UPLOAD_URL, css


class Form:
    def __init__(self, page):
        self.page = page
        self.filled: list[str] = []
        self.skipped: list[dict[str, str]] = []
        self.missing: dict[str, dict[str, str]] = {}

    def find(self, name: str, timeout: float = 5000, state: str = "visible"):
        loc = self.page.locator(css(name))
        try:
            loc.first.wait_for(state=state, timeout=timeout)
            return loc
        except Exception:  # noqa: BLE001 - 超时即视为缺失
            self.missing[name] = {"css": SELECTORS[name].css, "note": SELECTORS[name].note}
            return None

    def skip(self, step: str, reason: str) -> None:
        self.skipped.append({"step": step, "reason": reason})

    def run(self, step: str, fn) -> None:
        try:
            ok = fn()
            if ok is False:
                return
            self.filled.append(step)
        except Exception as e:  # noqa: BLE001 - 每一步独立失败，汇总报告
            self.skip(step, f"{type(e).__name__}: {str(e).splitlines()[0][:200] if str(e) else ''}")


def _clear_and_type_quill(page, editor, text: str) -> None:
    safe_click(editor)
    page.keyboard.press("ControlOrMeta+a")
    page.keyboard.press("Backspace")
    for i, line in enumerate(text.split("\n")):
        if i:
            page.keyboard.press("Enter")
        if line:
            page.keyboard.insert_text(line)


def _norm_text(s: str) -> str:
    return re.sub(r"\n+", "\n", (s or "").replace("\r", "")).strip()


# ---------------------------------------------------------------- 各字段步骤

def step_title(form: Form, meta: UploadMeta):
    loc = form.find("title", timeout=60000)
    if loc is None:
        return False
    box = loc.first
    box.fill("")  # 清掉自动带入的文件名
    box.fill(meta.title)
    if box.input_value() != meta.title:
        raise RuntimeError("title readback differs after fill")


def step_cover(form: Form, meta: UploadMeta):
    cover = form.find("cover")
    if cover is None:
        return False
    safe_click(cover)
    if form.find("cover_dialog", timeout=10000) is None:
        return False
    inp = form.find("cover_file_input", timeout=5000, state="attached")
    if inp is None:
        return False
    inp.first.set_input_files(str(meta.cover))
    form.page.wait_for_timeout(3000)
    dialog = form.page.locator(css("cover_dialog")).first
    for label in ("完成", "确定", "保存"):
        btn = dialog.get_by_text(label, exact=True)
        if btn.count():
            safe_click(btn.last)
            break
    else:
        raise RuntimeError("cover dialog: no 完成/确定 button found")
    form.page.wait_for_timeout(1500)


def step_statement(form: Form, meta: UploadMeta):
    box = form.find("statement_input")
    if box is None:
        return False
    current = box.first.input_value()
    if current == meta.creation_statement:
        return None
    safe_click(box)
    opts = form.page.locator(css("statement_option")).filter(has_text=re.compile(rf"^\s*{re.escape(meta.creation_statement)}\s*$"))
    if not opts.count():
        raise RuntimeError(f"option {meta.creation_statement!r} not in the statement dropdown")
    safe_click(opts)


def step_partition(form: Form, meta: UploadMeta):
    ctl = form.find("partition_controller")
    if ctl is None:
        return False
    val = form.page.locator(css("partition_value"))
    if val.count() and val.first.inner_text().strip() == meta.partition:
        return None
    safe_click(ctl)
    opt = form.page.locator(css("partition_option")).filter(has_text=re.compile(rf"^\s*{re.escape(meta.partition)}\s*$"))
    try:
        opt.first.wait_for(state="visible", timeout=5000)
    except Exception:  # noqa: BLE001
        form.missing.setdefault("partition_option", {"css": SELECTORS["partition_option"].css,
                                                     "note": SELECTORS["partition_option"].note})
        raise RuntimeError(f"partition option {meta.partition!r} not found")
    safe_click(opt)


def read_tags(page) -> list[str]:
    return [t.strip() for t in page.locator(css("tag_item")).all_inner_texts() if t.strip()]


def step_tags(form: Form, meta: UploadMeta):
    box = form.find("tag_input")
    if box is None:
        return False
    for tag in meta.tags:
        if tag in read_tags(form.page):
            continue
        b = box.first
        safe_click(b)
        b.fill(tag)
        b.press("Enter")
        form.page.wait_for_timeout(400)


def step_description(form: Form, meta: UploadMeta):
    ed = form.find("desc_editor")
    if ed is None:
        return False
    _clear_and_type_quill(form.page, ed.first, meta.description)


def expand_more_settings(form: Form) -> bool:
    more = form.page.locator(css("more_settings"))
    if more.count() and more.first.is_visible():
        return True
    toggle = form.page.locator(css("more_settings_toggle")).filter(has_text="更多设置")
    if not toggle.count():
        form.missing["more_settings_toggle"] = {"css": SELECTORS["more_settings_toggle"].css,
                                                "note": SELECTORS["more_settings_toggle"].note}
        return False
    safe_click(toggle)
    return form.find("more_settings") is not None


def step_visibility(form: Form, meta: UploadMeta):
    if not expand_more_settings(form):
        raise RuntimeError("more settings not expanded")
    label = "公开可见" if meta.visibility == "public" else "仅自己可见"
    radio = form.page.locator(css("visibility_radio")).filter(has_text=label)
    if not radio.count():
        form.missing["visibility_radio"] = {"css": SELECTORS["visibility_radio"].css,
                                            "note": SELECTORS["visibility_radio"].note}
        return False
    safe_click(radio)


def step_dynamic(form: Form, meta: UploadMeta):
    if not expand_more_settings(form):
        raise RuntimeError("more settings not expanded")
    ed = form.find("dynamic_editor")
    if ed is None:
        return False
    _clear_and_type_quill(form.page, ed.first, meta.dynamic)


def step_subtitles(form: Form, meta: UploadMeta):
    if not expand_more_settings(form):
        raise RuntimeError("more settings not expanded")
    btn = form.find("subtitle_button")
    if btn is None:
        return False
    with form.page.expect_file_chooser(timeout=10000) as fc:
        safe_click(btn)
    fc.value.set_files(str(meta.subtitles.path))
    form.page.wait_for_timeout(3000)


def step_chapters(form: Form, meta: UploadMeta):
    if not expand_more_settings(form):
        raise RuntimeError("more settings not expanded")
    btn = form.find("chapter_button")
    if btn is None:
        return False
    if btn.first.is_disabled():
        form.skip("chapters", "「编辑章节」按钮不可用（通常要等视频上传处理完成）")
        return False
    safe_click(btn)
    raise RuntimeError("chapter editor dialog is not automated yet")


# ---------------------------------------------------------------- 上传状态

_UPLOAD_JS = """(sel) => {
  const items = Array.from(document.querySelectorAll(sel));
  const text = items.map(e => e.innerText).join(' | ').replace(/\\s+/g, ' ').trim();
  return {items: items.length, text: text.slice(0, 300)};
}"""


def upload_state(page) -> dict[str, Any]:
    st = page.evaluate(_UPLOAD_JS, css("upload_item"))
    text = st.get("text", "")
    st["done"] = bool(re.search(r"上传完成|已完成|处理完成", text)) and not re.search(r"上传中|\d+(\.\d+)?%", text)
    st["failed"] = bool(re.search(r"失败|错误", text))
    return st


def wait_upload(page, timeout_s: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    st = upload_state(page)
    while not st["done"] and not st["failed"] and time.monotonic() < deadline:
        page.wait_for_timeout(5000)
        st = upload_state(page)
    st["timed_out"] = not st["done"] and not st["failed"]
    return st


# ---------------------------------------------------------------- 读回

_READ_JS = """(s) => {
  const q = (c) => document.querySelector(c);
  const txt = (c) => { const e = q(c); return e ? e.innerText.trim() : null; };
  const val = (c) => { const e = q(c); return e ? e.value : null; };
  const cover = q(s.cover);
  return {
    title: val(s.title),
    creation_statement: val(s.statement_input),
    partition: txt(s.partition_value),
    tags: Array.from(document.querySelectorAll(s.tag_item)).map(e => e.innerText.trim()).filter(Boolean),
    description: txt(s.desc_editor),
    visibility: txt(s.visibility_checked),
    dynamic: txt(s.dynamic_editor),
    cover_image: cover ? (getComputedStyle(cover).backgroundImage || '').slice(0, 40) !== 'none' : null,
    subtitles_section: txt(s.subtitle_section),
    chapters_section: txt(s.chapter_section),
  };
}"""


def readback(page, meta: UploadMeta) -> dict[str, Any]:
    sels = {k: v.css for k, v in SELECTORS.items()}
    got = page.evaluate(_READ_JS, sels)
    mismatches: dict[str, Any] = {}

    def cmp(key: str, ok: bool, expected: Any) -> None:
        if not ok:
            mismatches[key] = {"expected": expected, "actual": got.get(key)}

    cmp("title", got["title"] == meta.title, meta.title)
    cmp("creation_statement", got["creation_statement"] == meta.creation_statement, meta.creation_statement)
    if meta.partition:
        cmp("partition", (got["partition"] or "").strip() == meta.partition, meta.partition)
    if meta.tags:
        cmp("tags", got["tags"] == meta.tags, meta.tags)
    if meta.description:
        cmp("description", _norm_text(got["description"]) == _norm_text(meta.description), "(see metadata)")
    vis = "公开可见" if meta.visibility == "public" else "仅自己可见"
    if got["visibility"] is not None or meta.visibility == "self":
        cmp("visibility", got["visibility"] == vis, vis)
    if meta.dynamic:
        cmp("dynamic", _norm_text(got["dynamic"]) == _norm_text(meta.dynamic), meta.dynamic)
    if meta.subtitles:
        name = meta.subtitles.path.name
        cmp("subtitles_section", name in (got["subtitles_section"] or ""), f"contains {name}")
    if meta.chapters:
        sec = got["chapters_section"] or ""
        cmp("chapters_section", all(c.title in sec for c in meta.chapters),
            [f"{format_timestamp(c.start)} {c.title}" for c in meta.chapters])
    if got.get("description") and len(got["description"]) > 120:
        got["description"] = got["description"][:120] + "…"
    return {"values": got, "mismatches": mismatches}


# ---------------------------------------------------------------- 入口

def find_upload_tab(ctx):
    """找已经选好视频（标题框已渲染）的投稿标签页；没有则返回 None。"""
    for pg in reversed(ctx.pages):
        if pg.url.startswith(UPLOAD_URL) and pg.locator(css("title")).count():
            return pg
    return None


def execute(session, meta: UploadMeta, reuse_tab: bool, upload_timeout_s: float,
            wait_for_upload: bool = True) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    from .browser import check_login, connect

    with sync_playwright() as p:
        _, ctx = connect(p, session)
        if reuse_tab:
            page = find_upload_tab(ctx)
            if page is None:
                return {"ok": False, "error": "no upload tab with a selected video found; run without --reuse-tab"}
        else:
            page = ctx.new_page()
            page.goto(UPLOAD_URL, wait_until="domcontentloaded")
            login = check_login(page)
            if login.get("logged_in") is not True:
                return {"ok": False, "error": "not logged in; ask the human to scan the QR code", **login}
        page.bring_to_front()
        form = Form(page)

        if not reuse_tab:
            inp = form.find("file_input", timeout=20000, state="attached")
            if inp is None:
                return {"ok": False, "error": "video file input not found",
                        "missing_selectors": form.missing}
            inp.first.set_input_files(str(meta.video))  # 上传从这里开始
            form.filled.append("select_video")

        form.run("title", lambda: step_title(form, meta))
        if meta.cover:
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
        if meta.subtitles:
            form.run("subtitles", lambda: step_subtitles(form, meta))

        upload = wait_upload(page, upload_timeout_s if wait_for_upload else 0)

        if meta.chapters:
            form.run("chapters", lambda: step_chapters(form, meta))

        check = readback(page, meta)
        submit = page.locator(css("submit"))
        submit_visible = False
        if submit.count():
            submit.first.scroll_into_view_if_needed()  # 只滚动，不点击
            submit_visible = submit.first.is_visible()
        else:
            form.missing["submit"] = {"css": SELECTORS["submit"].css, "note": SELECTORS["submit"].note}

        human = ["在浏览器里核对所有字段", "亲手点击「立即投稿」（工具不会点击）"]
        if meta.subtitles and not meta.subtitles.default_on:
            human.insert(0, "确认字幕对观众默认关闭（若页面没有该开关，投稿后在字幕管理里检查）")
        for s in form.skipped:
            human.insert(0, f"手动完成：{s['step']}（{s['reason']}）")
        return {
            "ok": not form.skipped and not form.missing and not check["mismatches"],
            "filled": form.filled,
            "skipped": form.skipped,
            "missing_selectors": form.missing,
            "upload": upload,
            "readback": check["values"],
            "mismatches": check["mismatches"],
            "submit_button_visible": submit_visible,
            "submit_clicked": False,
            "tab_url": page.url.split("?")[0],
            "human_steps": human,
        }
