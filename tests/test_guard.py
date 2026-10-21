import pytest

from bilibili_upload.guard import FORBIDDEN_TEXTS, ForbiddenClick, check_click, forbidden_reason, safe_click


@pytest.mark.parametrize("text", ["立即投稿", "存草稿", "保存草稿", "提交", "投稿", "确认发布", " 立即投稿 "])
def test_rejects_submit_like_text(text):
    assert forbidden_reason({"text": text, "cls": "bcc-button"}) is not None


@pytest.mark.parametrize("info", [
    {"text": "确定", "cls": "submit-add"},
    {"text": "", "cls": "x", "ancestorClasses": ["submit-container"]},
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
    info = {"editable": True, "text": "投稿后欢迎提交反馈", "cls": "ql-editor", "ancestorClasses": ["desc-container"]}
    assert forbidden_reason(info) is None


def test_editable_still_rejected_inside_submit_area():
    info = {"editable": True, "text": "", "cls": "ql-editor", "ancestorClasses": ["submit-container"]}
    assert forbidden_reason(info) is not None


class FakeLocator:
    def __init__(self, info):
        self.info = info
        self.clicked = False

    @property
    def first(self):
        return self

    def wait_for(self, **kw):
        pass

    def evaluate(self, js):
        return self.info

    def click(self, **kw):
        self.clicked = True


def test_safe_click_refuses_and_never_clicks():
    loc = FakeLocator({"text": "立即投稿", "cls": "submit-add"})
    with pytest.raises(ForbiddenClick):
        safe_click(loc)
    assert loc.clicked is False


def test_safe_click_clicks_allowed():
    loc = FakeLocator({"text": "公开可见", "cls": "check-radio-v2-container"})
    safe_click(loc)
    assert loc.clicked is True


def test_check_click_returns_info():
    assert check_click(FakeLocator({"text": "完成", "cls": ""}))["text"] == "完成"


def test_forbidden_list_covers_required_words():
    for word in ("立即投稿", "存草稿", "提交", "投稿"):
        assert word in FORBIDDEN_TEXTS


def test_no_click_outside_guard():
    """源码里除 guard.py 外不得直接调用 .click( 或 dispatchEvent / el.click。"""
    from pathlib import Path

    import bilibili_upload

    src = Path(bilibili_upload.__file__).parent
    offenders = []
    for f in src.glob("*.py"):
        if f.name == "guard.py":
            continue
        text = f.read_text(encoding="utf-8")
        for needle in (".click(", "dispatchEvent", ".dblclick(", ".tap(", ".check(", "requestSubmit", ".submit()"):
            if needle in text:
                offenders.append(f"{f.name}: {needle}")
    assert offenders == [], offenders
