"""点击与按键守卫：本工具里的每一次点击、按键、文字输入都必须经过这里。

点击前，守卫把目标元素固定成一个 ElementHandle（避免检查一个、点到另一个），
然后在页面里检查：
- 元素自身、它最近的可交互祖先（button / a / [role=button] / label）的文字、aria、type；
- 元素到文档根的所有祖先（穿过 shadow root）的类名；
- 元素内部是否包含提交类元素；
- 元素中心点实际命中的元素（elementFromPoint）及其可交互祖先。
任何一项像提交或存草稿，就抛出 ForbiddenClick，不点击。宁可误拒，不可误点。

按键前，守卫要求焦点在预期的可编辑元素上，且该元素不在带提交按钮的 <form> 里。
"""

from __future__ import annotations

from typing import Any

# 元素文字里出现这些词就拒绝点击
FORBIDDEN_TEXTS = ("立即投稿", "存草稿", "保存草稿", "草稿", "提交", "投稿", "发布")
# 类名里出现这些片段就拒绝点击
FORBIDDEN_CLASS_FRAGMENTS = ("submit", "draft", "publish")
# 提交按钮本体（与 selectors.SELECTORS["submit"] 保持一致；守卫不依赖其他模块）
SUBMIT_CSS = ".submit-container, .submit-add"

_COMMON_JS = r"""
const FORBID_CLS = %(cls)s;
const SUBMIT_CSS = %(submit)s;
const clsOf = (e) => (e && (typeof e.className === 'string' ? e.className : (e.getAttribute && e.getAttribute('class')) || '')) || '';
const parentOf = (e) => e.parentElement || (e.getRootNode && e.getRootNode().host) || null;
const TEXT_INPUTS = ['', 'text', 'search', 'email', 'url', 'number', 'tel', 'password'];
const isEditable = (e) => {
  if (!e || e.nodeType !== 1) return false;
  if (e.isContentEditable) return true;
  const tag = e.tagName.toLowerCase();
  if (tag === 'textarea') return true;
  return tag === 'input' && TEXT_INPUTS.includes((e.type || '').toLowerCase());
};
const interactive = (e) => e.closest ? e.closest('button, a, [role=button], label, input[type=submit], input[type=button]') : null;
const describe = (e) => {
  if (!e) return null;
  const ancestors = [];
  for (let p = parentOf(e); p; p = parentOf(p)) ancestors.push(clsOf(p));
  return {
    editable: isEditable(e),
    text: isEditable(e) ? '' : ((e.innerText || '') + ' ' + (e.tagName === 'INPUT' ? (e.value || '') : '')),
    aria: (e.getAttribute && (e.getAttribute('aria-label') || '')) || '',
    cls: clsOf(e),
    type: ((e.tagName === 'BUTTON' || e.tagName === 'INPUT') ? (e.type || '') : '').toLowerCase(),
    ancestorClasses: ancestors,
  };
};
const containsSubmit = (e) => {
  if (!e || !e.querySelector) return false;
  const sel = FORBID_CLS.map(f => `[class*="${f}"]`).join(',');
  if (e.querySelector(sel)) return true;
  const s = document.querySelector(SUBMIT_CSS);
  return !!(s && e !== document.body && e !== document.documentElement && e.contains(s));
};
"""

_INSPECT_CLICK_JS = "(el) => {" + _COMMON_JS + r"""
  const out = {self: describe(el), inter: null, hit: null, hitInter: null, containsSubmit: containsSubmit(el)};
  const i = interactive(el);
  if (i && i !== el) out.inter = describe(i);
  const r = el.getBoundingClientRect();
  const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  if (hit && hit !== el) {
    out.hit = describe(hit);
    const hi = interactive(hit);
    if (hi && hi !== hit && hi !== i) out.hitInter = describe(hi);
  }
  return out;
}"""

_INSPECT_FOCUS_JS = "(el) => {" + _COMMON_JS + r"""
  const a = document.activeElement;
  const ok = !!a && (a === el || el.contains(a));
  let formHasSubmit = false;
  const f = a && a.form;
  if (f) formHasSubmit = !!f.querySelector('button:not([type]), button[type=submit], input[type=submit], input[type=image]');
  return {focused: ok, active: describe(a), formHasSubmit};
}"""


def _js(template: str) -> str:
    import json

    return template % {"cls": json.dumps(list(FORBIDDEN_CLASS_FRAGMENTS)), "submit": json.dumps(SUBMIT_CSS)}


INSPECT_CLICK_JS = _js(_INSPECT_CLICK_JS)
INSPECT_FOCUS_JS = _js(_INSPECT_FOCUS_JS)


class ForbiddenClick(RuntimeError):
    """守卫拒绝点击或按键时抛出。"""


def forbidden_reason(info: dict[str, Any] | None) -> str | None:
    """纯函数：给定一个元素描述，返回拒绝理由；可以点击时返回 None。

    可编辑区域（输入框、富文本）里的文字是用户内容，不是按钮文案，只查 aria。
    """
    if not info:
        return None
    text = info.get("aria", "") if info.get("editable") else f"{info.get('text', '')} {info.get('aria', '')}"
    for word in FORBIDDEN_TEXTS:
        if word in text:
            return f"text contains {word!r}"
    if info.get("type") == "submit":
        return "type=submit"
    for c in [info.get("cls", "")] + list(info.get("ancestorClasses", [])):
        low = (c or "").lower()
        for frag in FORBIDDEN_CLASS_FRAGMENTS:
            if frag in low:
                return f"class contains {frag!r}"
    return None


def click_verdict(report: dict[str, Any]) -> str | None:
    """纯函数：综合点击检查报告，返回拒绝理由或 None。"""
    if report.get("containsSubmit"):
        return "element contains a submit-like control"
    for key in ("self", "inter", "hit", "hitInter"):
        reason = forbidden_reason(report.get(key))
        if reason:
            return f"{key}: {reason}"
    return None


def focus_verdict(report: dict[str, Any]) -> str | None:
    """纯函数：按键前的焦点检查。"""
    if not report.get("focused"):
        return "focus is not on the intended element"
    active = report.get("active") or {}
    if not active.get("editable"):
        return "focused element is not editable"
    if report.get("formHasSubmit"):
        return "focused element is inside a form with a submit button"
    return forbidden_reason(active)


def _pin(locator, timeout: float):
    target = locator.first
    target.wait_for(state="visible", timeout=timeout)
    handle = target.element_handle(timeout=timeout)
    if handle is None:
        raise ForbiddenClick("element vanished before it could be checked")
    return handle


def check_click(handle) -> dict[str, Any]:
    report = handle.evaluate(INSPECT_CLICK_JS)
    reason = click_verdict(report)
    if reason:
        text = ((report.get("self") or {}).get("text") or "").strip()[:40]
        raise ForbiddenClick(f"refusing to click a submit-like control ({reason}): {text!r}")
    return report


def safe_click(locator, timeout: float = 5000) -> None:
    """唯一允许的点击入口：固定元素、检查、对同一个元素点击。"""
    handle = _pin(locator, timeout)
    handle.scroll_into_view_if_needed(timeout=timeout)
    check_click(handle)
    handle.click(timeout=timeout)


def _check_focus(handle) -> None:
    reason = focus_verdict(handle.evaluate(INSPECT_FOCUS_JS))
    if reason:
        raise ForbiddenClick(f"refusing to send keys: {reason}")


def focus_editable(locator, timeout: float = 5000):
    """点击一个可编辑元素使其获得焦点，返回固定后的句柄供后续按键使用。"""
    handle = _pin(locator, timeout)
    handle.scroll_into_view_if_needed(timeout=timeout)
    check_click(handle)
    handle.click(timeout=timeout)
    _check_focus(handle)
    return handle


def safe_press(page, handle, key: str) -> None:
    """按键前确认焦点仍在预期的可编辑元素上。"""
    _check_focus(handle)
    page.keyboard.press(key)


def safe_insert_text(page, handle, text: str) -> None:
    _check_focus(handle)
    page.keyboard.insert_text(text)


def safe_fill(locator, value: str, timeout: float = 5000):
    """向文本输入框填值：只接受可编辑元素。"""
    handle = focus_editable(locator, timeout)
    handle.fill(value, timeout=timeout)
    return handle
