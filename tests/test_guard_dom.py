"""用本机 Chrome 无头运行守卫的真实 JS（不联网）。找不到 Chrome 时跳过。"""

import pytest

from bilibili_upload.browser import find_chrome
from bilibili_upload.guard import ForbiddenClick, focus_editable, safe_click, safe_press

chrome = find_chrome()
pytestmark = pytest.mark.skipif(chrome is None, reason="system Chrome not found")

HTML = """
<html><body>
<div class="form">
  <div class="setting"><div class="radio" id="ok">公开可见</div></div>
  <button id="iconbtn"><i id="icon" class="ic">&nbsp;&nbsp;</i>立即投稿</button>
  <div class="a"><div><div><div><div><div><div><div><div class="submit-container">
    <span id="deep">x</span></div></div></div></div></div></div></div></div></div>
  <div id="long">""" + ("长" * 400) + """<span class="submit-add">立即投稿</span></div>
  <div id="wrapper" class="wrap"><span class="btn-submit-x">ok</span></div>
  <form><input id="forminput" class="inp"><button>发送</button></form>
  <input id="plain" class="inp">
  <div class="btn-primary" onclick="window.hit=1"><i id="ic">&nbsp;</i><span>立即投稿</span></div>
  <div class="pub" style="cursor:pointer"><span id="child2">确认</span><span>发布</span></div>
  <label for="sb" id="lab">选项</label><button id="sb">立即投稿</button>
  <form onsubmit="window.submitted=1;return false"><input id="single" class="inp"></form>
  <div class="setting"><div class="ql-editor" contenteditable="true" id="ed">投稿后发布</div></div>
  <div class="upload-area" id="ua" onclick="document.querySelector('#fileinput').click()">上传视频</div>
  <input type="file" id="fileinput" accept=".mp4,.flv" style="display:none">
  <div id="cover" style="position:relative;width:200px;height:40px">covered
    <div class="submit-add" style="position:absolute;inset:0;background:#fff">立即投稿</div></div>
</div></body></html>
"""


@pytest.fixture(scope="module")
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome, headless=True)
        pg = browser.new_page()
        pg.set_content(HTML)
        yield pg
        browser.close()


def test_allows_plain_control(page):
    safe_click(page.locator("#ok"))


@pytest.mark.parametrize("sel", ["#icon", "#deep", "#long", "#wrapper", "#cover", "#ic", "#child2", "#lab"])
def test_rejects_hidden_submit_paths(page, sel):
    with pytest.raises(ForbiddenClick):
        safe_click(page.locator(sel))


def test_press_refused_inside_form_with_submit(page):
    with pytest.raises(ForbiddenClick):
        focus_editable(page.locator("#forminput"))


def test_press_allowed_in_plain_input(page):
    h = focus_editable(page.locator("#plain"))
    safe_press(page, h, "a")
    assert page.locator("#plain").input_value() == "a"


def test_press_refused_when_focus_moved(page):
    h = focus_editable(page.locator("#plain"))
    safe_click(page.locator("#ok"))  # 焦点离开输入框
    page.evaluate("document.activeElement && document.activeElement.blur()")
    with pytest.raises(ForbiddenClick):
        safe_press(page, h, "Enter")


def test_press_refused_in_single_input_form(page):
    with pytest.raises(ForbiddenClick):
        focus_editable(page.locator("#single"))
    assert page.evaluate("window.submitted") is None


def test_editor_with_forbidden_user_text_is_editable(page):
    h = focus_editable(page.locator("#ed"))
    safe_press(page, h, "End")


def test_select_file_via_chooser(page, tmp_path):
    from bilibili_upload.fill import select_file_via_chooser

    f = tmp_path / "clip.mp4"
    f.write_bytes(b"\x00" * 8)
    select_file_via_chooser(page, page.locator("#ua"), f, ".mp4")
    assert page.evaluate("document.querySelector('#fileinput').files[0].name") == "clip.mp4"


def test_select_file_via_chooser_checks_accept(page, tmp_path):
    from bilibili_upload.fill import select_file_via_chooser

    f = tmp_path / "subs.srt"
    f.write_text("x")
    with pytest.raises(RuntimeError):
        select_file_via_chooser(page, page.locator("#ua"), f, ".srt")
