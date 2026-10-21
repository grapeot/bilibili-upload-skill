"""按计划填写投稿表单，读回核对，停在「立即投稿」之前。

所有点击、按键都经过 guard。找不到的选择器写入 missing_selectors，
该步骤跳过，不猜测替代元素。函数结束时只断开 CDP 连接，标签页留给人。
"""

from __future__ import annotations

import re
import time
from typing import Any

from .guard import focus_editable, safe_click, safe_fill, safe_insert_text, safe_press
from .meta import UploadMeta, format_timestamp
from .plan import ALWAYS_HUMAN
from .selectors import SELECTORS, UPLOAD_URL, css


class Form:
    def __init__(self, page):
        self.page = page
        self.filled: list[str] = []
        self.skipped: list[dict[str, str]] = []
        self.missing: dict[str, dict[str, str]] = {}
        self.human: list[str] = []

    def mark_missing(self, name: str) -> None:
        self.missing[name] = {"css": SELECTORS[name].css, "note": SELECTORS[name].note}

    def find(self, name: str, timeout: float = 5000, state: str = "visible"):
        loc = self.page.locator(css(name))
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
            ok = fn()
            if ok is False:
                if not any(s["step"] == step for s in self.skipped):
                    self.skip(step, "required element not found (see missing_selectors)")
                return
            self.filled.append(step)
        except Exception as e:  # noqa: BLE001 - 每一步独立失败，汇总报告
            msg = str(e).splitlines()[0][:200] if str(e) else ""
            self.skip(step, f"{type(e).__name__}: {msg}")


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
    inp.first.set_input_files(str(meta.cover))  # 封面是小文件，Playwright 自带方式即可
    form.page.wait_for_timeout(3000)
    dialog = form.page.locator(css("cover_dialog")).first
    for label in ("完成", "确定"):
        btn = dialog.get_by_text(label, exact=True)
        if btn.count():
            safe_click(btn.last)
            break
    else:
        raise RuntimeError("cover dialog: no 完成/确定 button found")
    form.page.wait_for_timeout(1500)
    form.human.append("核对封面是否为指定图片")


def step_statement(form: Form, meta: UploadMeta):
    box = form.find("statement_input")
    if box is None:
        return False
    if box.first.input_value() == meta.creation_statement:
        return None
    safe_click(box)
    if form.find("statement_option") is None:
        return False
    opts = form.page.locator(css("statement_option")).filter(has_text=_exact(meta.creation_statement))
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
    if form.find("partition_option") is None:
        return False
    opt = form.page.locator(css("partition_option")).filter(has_text=_exact(meta.partition))
    if not opt.count():
        raise RuntimeError(f"partition option {meta.partition!r} not found")
    safe_click(opt)


def read_tags(page) -> list[str]:
    return [t.strip() for t in page.locator(css("tag_item")).all_inner_texts() if t.strip()]


def step_tags(form: Form, meta: UploadMeta):
    if form.find("tag_input") is None:
        return False
    existing = read_tags(form.page)
    extra = [t for t in existing if t not in meta.tags]
    todo = [t for t in meta.tags if t not in existing]
    if len(existing) + len(todo) > 10:
        raise RuntimeError(f"too many tags: {len(existing)} on page + {len(todo)} new > 10; remove extras first")
    if extra:
        form.human.append(f"页面上已有元数据之外的标签，请确认是否保留：{extra}")
    for tag in todo:
        handle = safe_fill(form.page.locator(css("tag_input")), tag)
        safe_press(form.page, handle, "Enter")
        form.page.wait_for_timeout(400)


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


def step_subtitles(form: Form, meta: UploadMeta):
    if not expand_more_settings(form):
        return False
    btn = form.find("subtitle_button")
    if btn is None:
        return False
    with form.page.expect_file_chooser(timeout=10000) as fc:
        safe_click(btn)
    chooser = fc.value
    accept = (chooser.element.get_attribute("accept") or "").lower()
    name = chooser.element.get_attribute("name") or ""
    if ".srt" not in accept or name == "buploader":
        raise RuntimeError(f"file chooser does not look like the subtitle input (accept={accept!r}, name={name!r})")
    chooser.set_files(str(meta.subtitles.path))
    form.page.wait_for_timeout(3000)
    form.human.append(f"确认字幕语言为「{meta.subtitles.language}」")
    if not meta.subtitles.default_on:
        form.human.append("确认字幕对观众默认关闭（页面若无此开关，投稿后在字幕管理里检查）")


def step_chapters(form: Form, meta: UploadMeta):
    form.skip("chapters", "章节编辑尚未自动化")
    form.human.append("在「更多设置 > 章节管理」里录入章节：" +
                      "；".join(f"{c.timestamp} {c.title}" for c in meta.chapters))
    return False


# ---------------------------------------------------------------- 上传状态

_UPLOAD_JS = """(sel) => {
  const items = Array.from(document.querySelectorAll(sel));
  const text = items.map(e => e.innerText).join(' | ').replace(/\\s+/g, ' ').trim();
  return {items: items.length, text};
}"""

_IN_PROGRESS = re.compile(r"上传中|处理中|转码中|(?<![\d.])(?:\d|[1-9]\d)(?:\.\d+)?%")


def classify_upload(items: int, text: str) -> dict[str, Any]:
    """纯函数：根据上传条目文字判断状态。"""
    failed = bool(re.search(r"失败|错误", text))
    in_progress = bool(_IN_PROGRESS.search(text))
    done = items > 0 and not failed and not in_progress and bool(re.search(r"上传完成|已完成|处理完成|100(?:\.0+)?%", text))
    return {"items": items, "text": text, "done": done, "failed": failed, "in_progress": in_progress}


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
        page.wait_for_timeout(5000)
        st = upload_state(page)
    st["timed_out"] = not st["done"] and not st["failed"]
    return st


# ---------------------------------------------------------------- 读回

_READ_JS = """(s) => {
  const q = (c) => document.querySelector(c);
  const txt = (c) => { const e = q(c); return e ? e.innerText.trim() : null; };
  const val = (c) => { const e = q(c); return e ? e.value : null; };
  return {
    title: val(s.title),
    creation_statement: val(s.statement_input),
    partition: txt(s.partition_value),
    tags: q(s.tag_input) ? Array.from(document.querySelectorAll(s.tag_item)).map(e => e.innerText.trim()).filter(Boolean) : null,
    description: txt(s.desc_editor),
    visibility: txt(s.visibility_checked),
    dynamic: txt(s.dynamic_editor),
    subtitles_section: txt(s.subtitle_section),
    chapters_section: txt(s.chapter_section),
  };
}"""

# 读回字段 -> 对应选择器名（读回为 null 时记为缺失）
_READ_SELECTORS = {
    "title": "title", "creation_statement": "statement_input", "partition": "partition_value",
    "tags": "tag_input", "description": "desc_editor", "visibility": "visibility_checked",
    "dynamic": "dynamic_editor", "subtitles_section": "subtitle_section", "chapters_section": "chapter_section",
}


def compare(got: dict[str, Any], meta: UploadMeta) -> tuple[dict[str, Any], list[str]]:
    """纯函数：把读回值与元数据比对，返回 (mismatches, 读回为空的选择器名)。"""
    mismatches: dict[str, Any] = {}
    missing: list[str] = []
    wanted = {"title", "creation_statement", "visibility"}
    wanted |= {k for k, on in (("partition", meta.partition), ("tags", meta.tags),
                               ("description", meta.description), ("dynamic", meta.dynamic),
                               ("subtitles_section", meta.subtitles), ("chapters_section", meta.chapters)) if on}

    def cmp(key: str, ok: bool, expected: Any) -> None:
        if got.get(key) is None:
            missing.append(_READ_SELECTORS[key])
            mismatches[key] = {"expected": expected, "actual": None}
        elif not ok:
            mismatches[key] = {"expected": expected, "actual": got.get(key)}

    for key in wanted:
        if key == "title":
            cmp(key, got.get(key) == meta.title, meta.title)
        elif key == "creation_statement":
            cmp(key, got.get(key) == meta.creation_statement, meta.creation_statement)
        elif key == "partition":
            cmp(key, (got.get(key) or "").strip() == meta.partition, meta.partition)
        elif key == "tags":
            cmp(key, got.get(key) == meta.tags, meta.tags)
        elif key == "description":
            cmp(key, _norm_text(got.get(key)) == _norm_text(meta.description), "(see metadata)")
        elif key == "visibility":
            vis = "公开可见" if meta.visibility == "public" else "仅自己可见"
            cmp(key, got.get(key) == vis, vis)
        elif key == "dynamic":
            cmp(key, _norm_text(got.get(key)) == _norm_text(meta.dynamic), meta.dynamic)
        elif key == "subtitles_section":
            name = meta.subtitles.path.name
            cmp(key, name in (got.get(key) or ""), f"contains {name}")
        elif key == "chapters_section":
            sec = got.get(key) or ""
            cmp(key, all(c.title in sec for c in meta.chapters),
                [f"{format_timestamp(c.start)} {c.title}" for c in meta.chapters])
    return mismatches, sorted(set(missing))


def readback(page, meta: UploadMeta) -> dict[str, Any]:
    got = page.evaluate(_READ_JS, {k: v.css for k, v in SELECTORS.items()})
    mismatches, missing = compare(got, meta)
    if got.get("description") and len(got["description"]) > 120:
        got["description"] = got["description"][:120] + "…"
    return {"values": got, "mismatches": mismatches, "missing": missing}


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
            upload = wait_upload(page, upload_timeout_s if wait_for_upload else 0, form)
            if meta.chapters:
                form.run("chapters", lambda: step_chapters(form, meta))
            check = readback(page, meta)
            for name in check["missing"]:
                form.mark_missing(name)
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
