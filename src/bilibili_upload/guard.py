"""点击与按键守卫：本工具里的每一次点击、按键、文字输入都必须经过这里。

点击前，守卫把目标元素固定成一个 ElementHandle（避免检查一个、点到另一个），
然后在页面里检查：
- 元素自身、它最近的可交互祖先（button / a / [role=button] / label）的文字、aria、type；
- 元素到文档根的所有祖先（穿过 shadow root）的类名；
- 元素内部是否包含提交类元素；
- 点击点实际命中的元素（elementFromPoint）及其可交互祖先。点击点默认是元素中心；中心被别的元素
  盖住时（例如上传中「立即投稿」上方的提示气泡盖住了「更多设置」），改在元素上找一个确实命中它
  自己（或其后代）的点，检查和点击都用这同一个点；找不到就仍按中心检查，命中的遮挡物照常被拒；
- 元素和命中元素的所有祖先里，是否有文字很短或可点击、且文字含禁词的元素（div/span 拼成的按钮；
  包含输入框或可编辑区域的祖先跳过，真正的按钮不会包含输入框）；
- 若在 <label> 里，label 关联的控件（元素和命中元素都查）。
任何一项像提交或存草稿，就抛出 ForbiddenClick，不点击。宁可误拒，不可误点。

唯一的放行例外定义在 selectors.GUARD_EXCEPTIONS：「封面制作」弹窗里文字恰为「完成」的
`.button.submit`。放行只忽略这个元素自身的类名，文字、祖先、命中点等检查照常进行；
所在弹窗若包含「立即投稿」或「存草稿」字样，放行失效。

按键前，守卫要求焦点在预期的可编辑元素上；按回车时还要求它不在任何 <form> 里
（回车可能触发表单的隐式提交；填值和插入文字不会提交，不受这条限制）。
"""

from __future__ import annotations

from typing import Any

from .selectors import GUARD_EXCEPTIONS

# 元素文字里出现这些词就拒绝点击
FORBIDDEN_TEXTS = ("立即投稿", "存草稿", "保存草稿", "草稿", "提交", "投稿", "发布")
# 类名里出现这些片段就拒绝点击
FORBIDDEN_CLASS_FRAGMENTS = ("submit", "draft", "publish")
# 提交按钮本体（与 selectors.SELECTORS["submit"] 保持一致；守卫不依赖其他模块）
SUBMIT_CSS = ".submit-container, .submit-add"

_COMMON_JS = r"""
const FORBID_CLS = %(cls)s;
const FORBID_TXT = %(txt)s;
const hasWord = (t) => FORBID_TXT.some(w => t.includes(w));
const SUBMIT_CSS = %(submit)s;
const EXC = %(exc)s;
let EXC_EL = null;  // 命中限定放行规则的元素：只忽略它自己的类名，文字等其他检查照常
const clsOf = (e) => (e && e !== EXC_EL && (typeof e.className === 'string' ? e.className : (e.getAttribute && e.getAttribute('class')) || '')) || '';
const matchException = (e) => {
  for (const ex of EXC) {
    if (!e.matches || !e.matches(ex.css) || (e.innerText || '').trim() !== ex.text) continue;
    const dlg = e.closest('.bcc-dialog');
    if (!dlg) continue;
    const dt = dlg.innerText || '';
    if (dt.includes(ex.dialog_text) && !dt.includes('立即投稿') && !dt.includes('存草稿')) return e;
  }
  return null;
};
const parentOf = (e) => e.parentElement || (e.getRootNode && e.getRootNode().host) || null;
const TEXT_INPUTS = ['', 'text', 'search', 'email', 'url', 'number', 'tel', 'password'];
const isEditable = (e) => {
  if (!e || e.nodeType !== 1) return false;
  if (e.isContentEditable) return true;
  const tag = e.tagName.toLowerCase();
  if (tag === 'textarea') return true;
  return tag === 'input' && TEXT_INPUTS.includes((e.type || '').toLowerCase());
};
// <button> 没写 type 时浏览器报 'submit'，但只有它属于某个表单时才真能提交表单。
// B 站很多普通按钮（上传字幕、编辑章节）都不写 type，也不在表单里，按写明的属性算。
const typeOf = (e) => {
  if (e.tagName === 'INPUT') return (e.type || '').toLowerCase();
  if (e.tagName !== 'BUTTON') return '';
  // 写了 type 就用浏览器规范化后的值（写错的值也会被当成 submit）
  if (e.hasAttribute('type')) return (e.type || '').toLowerCase();
  return e.form ? 'submit' : '';
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
    type: typeOf(e),
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

_INSPECT_CLICK_JS = "(el, pos) => {" + _COMMON_JS + r"""
  EXC_EL = matchException(el);
  // 祖先里任何「短文字含禁词」或「可点击且文字含禁词」的元素都视为提交按钮（div/span 拼成的按钮）
  const EDITABLE_CSS = 'input:not([type]), input[type=text], input[type=search], input[type=email], input[type=url], ' +
    'input[type=number], input[type=tel], input[type=password], textarea, [contenteditable=""], [contenteditable="true"]';
  const ancestorButton = (e) => {
    for (let p = e; p; p = parentOf(p)) {
      if (p.nodeType !== 1) continue;
      if (isEditable(p) || p.isContentEditable || (p.querySelector && p.querySelector(EDITABLE_CSS))) continue;
      const t = (p.innerText || '').trim();
      if (!t || !hasWord(t)) continue;
      if (t.length <= 12) return `ancestor with short text ${JSON.stringify(t)}`;
      const st = getComputedStyle(p);
      const pointer = p.hasAttribute('onclick') || p.hasAttribute('tabindex') || st.cursor === 'pointer';
      if (pointer && t.length <= 60) return `clickable ancestor with text ${JSON.stringify(t.slice(0, 20))}`;
    }
    return null;
  };
  const out = {self: describe(el), inter: null, hit: null, hitInter: null, control: null,
               containsSubmit: containsSubmit(el), ancestorButton: ancestorButton(el)};
  const i = interactive(el);
  if (i && i !== el) out.inter = describe(i);
  const labelControl = (e) => {
    const lab = e.closest ? e.closest('label') : null;
    return (lab && lab.control && lab.control !== e) ? lab.control : null;
  };
  const ctl = labelControl(el);
  if (ctl) {
    out.control = describe(ctl);
    if (containsSubmit(ctl)) out.containsSubmit = true;
  }
  const r = el.getBoundingClientRect();
  // pos 是相对元素左上角的点击点（与 Playwright click(position=...) 一致）；没有就用中心
  const px = r.left + (pos ? pos.x : r.width / 2), py = r.top + (pos ? pos.y : r.height / 2);
  const hit = document.elementFromPoint(px, py);
  if (hit && hit !== el) {
    out.hit = describe(hit);
    const hi = interactive(hit);
    if (hi && hi !== hit && hi !== i) out.hitInter = describe(hi);
    if (!el.contains(hit)) out.ancestorButton = out.ancestorButton || ancestorButton(hit);
    const hctl = labelControl(hit);
    if (hctl && hctl !== ctl) {
      out.hitControl = describe(hctl);
      if (containsSubmit(hctl)) out.containsSubmit = true;
    }
  }
  out.exception = !!EXC_EL;
  return out;
}"""

# 中心被别的元素盖住时，在元素上找一个命中它自己（或后代）的点；返回相对左上角的偏移，
# 中心本来就命中或整个元素都被盖住时返回 null（按中心检查，遮挡物照常被拒）
_PICK_POINT_JS = r"""(el) => {
  const r = el.getBoundingClientRect();
  if (!r.width || !r.height) return null;
  const own = (x, y) => { const h = document.elementFromPoint(x, y); return !!h && (h === el || el.contains(h)); };
  if (own(r.left + r.width / 2, r.top + r.height / 2)) return null;
  const fr = [0.5, 0.25, 0.75, 0.1, 0.9];
  for (const fy of fr) for (const fx of fr) {
    const x = Math.min(Math.max(r.width * fx, 1), r.width - 1), y = Math.min(Math.max(r.height * fy, 1), r.height - 1);
    if (own(r.left + x, r.top + y)) return {x, y};
  }
  return null;
}"""

_INSPECT_FOCUS_JS = "(el) => {" + _COMMON_JS + r"""
  const a = document.activeElement;
  const ok = !!a && (a === el || el.contains(a));
  // 处在任何 <form> 里都拒绝：回车可能触发隐式提交
  const inForm = !!(a && (a.form || (a.closest && a.closest('form'))));
  return {focused: ok, active: describe(a), inForm};
}"""


def _js(template: str) -> str:
    import json

    return template % {"cls": json.dumps(list(FORBIDDEN_CLASS_FRAGMENTS)), "submit": json.dumps(SUBMIT_CSS),
                       "txt": json.dumps(list(FORBIDDEN_TEXTS), ensure_ascii=False),
                       "exc": json.dumps(list(GUARD_EXCEPTIONS), ensure_ascii=False)}


INSPECT_CLICK_JS = _js(_INSPECT_CLICK_JS)
INSPECT_FOCUS_JS = _js(_INSPECT_FOCUS_JS)
PICK_POINT_JS = _PICK_POINT_JS


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
    if report.get("ancestorButton"):
        return report["ancestorButton"]
    for key in ("self", "inter", "hit", "hitInter", "control", "hitControl"):
        reason = forbidden_reason(report.get(key))
        if reason:
            return f"{key}: {reason}"
    return None


def focus_verdict(report: dict[str, Any], enter: bool = False) -> str | None:
    """纯函数：按键前的焦点检查。enter=True 时额外要求不在 <form> 里。"""
    if not report.get("focused"):
        return "focus is not on the intended element"
    active = report.get("active") or {}
    if not active.get("editable"):
        return "focused element is not editable"
    if enter and (report.get("inForm") or report.get("formHasSubmit")):
        return "focused element is inside a <form> (Enter could submit it)"
    return forbidden_reason(active)


def _pin(locator, timeout: float):
    if not hasattr(locator, "first"):  # 已经是 ElementHandle：直接用这个元素
        locator.wait_for_element_state("visible", timeout=timeout)
        return locator
    target = locator.first
    target.wait_for(state="visible", timeout=timeout)
    handle = target.element_handle(timeout=timeout)
    if handle is None:
        raise ForbiddenClick("element vanished before it could be checked")
    return handle


def check_click(handle, pos: dict[str, float] | None = None) -> dict[str, Any]:
    """检查在 pos（相对元素左上角；None 为中心）点击这个元素是否安全。"""
    report = handle.evaluate(INSPECT_CLICK_JS, pos)
    reason = click_verdict(report)
    if reason:
        text = ((report.get("self") or {}).get("text") or "").strip()[:40]
        raise ForbiddenClick(f"refusing to click a submit-like control ({reason}): {text!r}")
    return report


def _checked_click(handle, timeout: float) -> None:
    """对固定好的元素：选点击点、在这个点上检查、在同一个点上点击。"""
    handle.scroll_into_view_if_needed(timeout=timeout)
    pos = handle.evaluate(PICK_POINT_JS)
    check_click(handle, pos)
    if pos:
        handle.click(timeout=timeout, position=pos)
    else:
        handle.click(timeout=timeout)


def safe_click(locator, timeout: float = 5000) -> None:
    """唯一允许的点击入口：固定元素、检查、对同一个元素的同一个点点击。"""
    _checked_click(_pin(locator, timeout), timeout)


def _check_focus(handle, enter: bool = False) -> None:
    reason = focus_verdict(handle.evaluate(INSPECT_FOCUS_JS), enter=enter)
    if reason:
        raise ForbiddenClick(f"refusing to send keys: {reason}")


def focus_editable(locator, timeout: float = 5000):
    """点击一个可编辑元素使其获得焦点，返回固定后的句柄供后续按键使用。"""
    handle = _pin(locator, timeout)
    _checked_click(handle, timeout)
    _check_focus(handle)
    return handle


def safe_press(page, handle, key: str) -> None:
    """按键前确认焦点仍在预期的可编辑元素上；回车还要求不在表单里。"""
    _check_focus(handle, enter="enter" in key.lower())
    page.keyboard.press(key)


def safe_insert_text(page, handle, text: str) -> None:
    _check_focus(handle)
    page.keyboard.insert_text(text)


def safe_fill(locator, value: str, timeout: float = 5000):
    """向文本输入框填值：只接受可编辑元素。"""
    handle = focus_editable(locator, timeout)
    handle.fill(value, timeout=timeout)
    return handle
