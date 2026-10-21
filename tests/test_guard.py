from pathlib import Path

import pytest

import bilibili_upload
from bilibili_upload.guard import (
    FORBIDDEN_TEXTS, ForbiddenClick, click_verdict, focus_verdict, forbidden_reason, safe_click,
)


@pytest.mark.parametrize("text", ["立即投稿", "存草稿", "保存草稿", "提交", "投稿", "确认发布", " 立即投稿 "])
def test_rejects_submit_like_text(text):
    assert forbidden_reason({"text": text, "cls": "bcc-button"}) is not None


@pytest.mark.parametrize("info", [
    {"text": "确定", "cls": "submit-add"},
    {"text": "", "cls": "x", "ancestorClasses": ["a", "b", "c", "d", "e", "f", "g", "submit-container"]},
    {"text": "ok", "cls": "draft-btn"},
    {"text": "", "aria": "立即投稿", "cls": ""},
    {"text": "go", "cls": "", "type": "submit"},
])
def test_rejects_by_class_aria_type(info):
    assert forbidden_reason(info) is not None


@pytest.mark.parametrize("text", ["公开可见", "仅自己可见", "含AI生成内容", "上传字幕", "编辑章节", "完成", "科技数码"])
def test_allows_form_controls(text):
    assert forbidden_reason({"text": text, "cls": "bcc-button", "ancestorClasses": ["setting"]}) is None


def test_editable_user_text_is_not_button_text():
    info = {"editable": True, "text": "", "cls": "ql-editor", "ancestorClasses": ["desc-container"]}
    assert forbidden_reason(info) is None


def test_editable_still_rejected_inside_submit_area():
    info = {"editable": True, "text": "", "cls": "ql-editor", "ancestorClasses": ["submit-container"]}
    assert forbidden_reason(info) is not None


def test_click_verdict_checks_interactive_ancestor_and_hit_target():
    ok = {"text": "", "cls": "icon"}
    assert click_verdict({"self": ok, "inter": {"text": "立即投稿", "cls": "btn"}}) is not None
    assert click_verdict({"self": ok, "hit": {"text": "", "cls": "submit-add"}}) is not None
    assert click_verdict({"self": ok, "containsSubmit": True}) is not None
    assert click_verdict({"self": ok, "ancestorButton": "ancestor with short text"}) is not None
    assert click_verdict({"self": ok, "control": {"text": "立即投稿", "cls": ""}}) is not None
    assert click_verdict({"self": ok}) is None


def test_focus_verdict():
    good = {"focused": True, "active": {"editable": True, "cls": "input-val"}}
    assert focus_verdict(good) is None
    assert focus_verdict({**good, "focused": False}) is not None
    assert focus_verdict({**good, "formHasSubmit": True}, enter=True) is not None
    assert focus_verdict({**good, "inForm": True}, enter=True) is not None
    assert focus_verdict({**good, "inForm": True}) is None  # 填值、插入文字不会提交
    assert focus_verdict({"focused": True, "active": {"editable": False, "text": "确定"}}) is not None


class FakeHandle:
    def __init__(self, report):
        self.report = report
        self.clicked = False

    def evaluate(self, js):
        return self.report

    def scroll_into_view_if_needed(self, **kw):
        pass

    def click(self, **kw):
        self.clicked = True


class FakeLocator:
    def __init__(self, handle):
        self.handle = handle

    @property
    def first(self):
        return self

    def wait_for(self, **kw):
        pass

    def element_handle(self, **kw):
        return self.handle


def test_safe_click_refuses_and_never_clicks():
    h = FakeHandle({"self": {"text": "立即投稿", "cls": "submit-add"}})
    with pytest.raises(ForbiddenClick):
        safe_click(FakeLocator(h))
    assert h.clicked is False


def test_safe_click_clicks_the_checked_handle():
    h = FakeHandle({"self": {"text": "公开可见", "cls": "check-radio-v2-container"}})
    safe_click(FakeLocator(h))
    assert h.clicked is True


def test_forbidden_list_covers_required_words():
    for word in ("立即投稿", "存草稿", "提交", "投稿"):
        assert word in FORBIDDEN_TEXTS


def test_no_input_outside_guard():
    """除 guard.py 外，源码里不得直接点击、按键或派发事件。"""
    src = Path(bilibili_upload.__file__).parent
    needles = (".click(", "dispatchEvent", "dispatch_event(", ".dblclick(", ".tap(", ".check(", "set_checked(",
               "select_option(", "drag_to(", ".hover(", ".press(", "keyboard.", "mouse.", "requestSubmit",
               ".submit()", "touchscreen")
    offenders = []
    for f in src.glob("*.py"):
        if f.name == "guard.py":
            continue
        text = f.read_text(encoding="utf-8")
        offenders += [f"{f.name}: {n}" for n in needles if n in text]
    assert offenders == [], offenders
