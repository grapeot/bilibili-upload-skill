"""点击守卫：本工具里的每一次点击都必须经过 `safe_click`。

守卫在点击前读取目标元素的文字、类名、aria-label 和所在区域，只要像提交或存草稿，
就抛出 ForbiddenClick，不点击。宁可误拒，不可误点。
"""

from __future__ import annotations

from typing import Any

# 元素文字里出现这些词就拒绝点击
FORBIDDEN_TEXTS = ("立即投稿", "存草稿", "保存草稿", "草稿", "提交", "投稿", "发布")
# 类名里出现这些片段就拒绝点击
FORBIDDEN_CLASS_FRAGMENTS = ("submit", "draft", "publish")

# 在页面里描述一个元素：自身及祖先是否位于提交区
_DESCRIBE_JS = """(el) => {
  const cls = (e) => (typeof e.className === 'string' ? e.className : (e.getAttribute('class') || ''));
  let ancestorClasses = [];
  for (let p = el.parentElement, i = 0; p && i < 6; p = p.parentElement, i++) ancestorClasses.push(cls(p));
  const tag = el.tagName.toLowerCase();
  const t = (el.getAttribute('type') || '').toLowerCase();
  const editable = el.isContentEditable || tag === 'textarea' ||
    (tag === 'input' && !['button', 'submit', 'reset', 'image'].includes(t));
  return {
    editable,
    text: (el.innerText || el.value || '').trim().slice(0, 300),
    cls: cls(el),
    aria: el.getAttribute('aria-label') || '',
    type: (el.getAttribute('type') || '').toLowerCase(),
    ancestorClasses,
  };
}"""


class ForbiddenClick(RuntimeError):
    """守卫拒绝点击时抛出。"""


def forbidden_reason(info: dict[str, Any]) -> str | None:
    """纯函数：给定元素描述，返回拒绝理由；可以点击时返回 None。"""
    # 可编辑区域（输入框、富文本）里的文字是用户内容，不是按钮文案，只查 aria
    text = info.get("aria", "") if info.get("editable") else f"{info.get('text', '')} {info.get('aria', '')}"
    for word in FORBIDDEN_TEXTS:
        if word in text:
            return f"text contains {word!r}"
    if info.get("type") == "submit":
        return "type=submit"
    classes = [info.get("cls", "")] + list(info.get("ancestorClasses", []))
    for c in classes:
        low = (c or "").lower()
        for frag in FORBIDDEN_CLASS_FRAGMENTS:
            if frag in low:
                return f"class contains {frag!r}"
    return None


def check_click(locator) -> dict[str, Any]:
    """读取元素描述并做检查；被拒绝时抛 ForbiddenClick。"""
    info = locator.evaluate(_DESCRIBE_JS)
    reason = forbidden_reason(info)
    if reason:
        raise ForbiddenClick(f"refusing to click a submit-like control ({reason}): {info.get('text', '')[:40]!r}")
    return info


def safe_click(locator, timeout: float = 5000) -> None:
    """唯一允许的点击入口。"""
    target = locator.first
    target.wait_for(state="visible", timeout=timeout)
    check_click(target)
    target.click(timeout=timeout)
