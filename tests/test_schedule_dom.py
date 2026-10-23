"""用本机 Chrome 无头运行定时发布步骤，页面是按真实结构简化的合成选择器（不联网）。找不到 Chrome 时跳过。"""

from datetime import datetime, timedelta, timezone

import pytest

from bilibili_upload.browser import find_chrome
from bilibili_upload.fill import Form, readback, step_schedule
from bilibili_upload.meta import PICKER_TZ, parse_meta

chrome = find_chrome()
pytestmark = pytest.mark.skipif(chrome is None, reason="system Chrome not found")

HTML = """
<html><body>
<div class="time-container">
  <div class="section-title-container"><h3>定时发布</h3></div>
  <div class="time-switch-wrp">
    <div class="switch-container" style="width:40px;height:20px;background:#ccc"><span class="switch-roll"></span></div>
    <span>(可选择距离当前最早≥5分钟/最晚≤15天的时间，花火、预约、互动视频稿件不可修改/取消)</span>
    <div class="time-picker" style="display:none">
      <input class="bcc-select-input-inner" readonly value="__TZ__">
      <div class="date-picker-date" style="width:120px;height:20px"><p class="date-show" id="d">__DATE__</p></div>
      <div class="date-picker-container" style="display:none">
        <div><svg class="next-btn-month" width="20" height="20"></svg><p class="date-picker-nav-title" id="title"></p></div>
        <div class="date-wrp" id="days"></div>
      </div>
      <div class="date-picker-timer" style="width:120px;height:20px"><p class="date-show" id="t">__TIME__</p></div>
      <div class="time-picker-container" style="display:none">
        <div class="time-picker-panel-select-wrp" id="hours"></div>
        <div class="time-picker-panel-select-wrp" id="mins"></div>
      </div>
    </div>
  </div>
</div>
<div class="submit-container"><span class="submit-add">立即投稿</span></div>
<script>
const $ = (s) => document.querySelector(s);
const pad = (n) => String(n).padStart(2, '0');
const start = $('#d').innerText.split('-').map(Number);  // 今天之前的日期不可选
let ym = [start[0], start[1]];
$('.switch-container').onclick = () => {
  $('.switch-container').classList.toggle('switch-container-active');
  $('.time-picker').style.display = $('.switch-container').classList.contains('switch-container-active') ? '' : 'none';
};
const renderDays = () => {
  $('#title').innerText = ym[0] + '年' + ym[1] + '月';
  const n = new Date(ym[0], ym[1], 0).getDate();
  $('#days').innerHTML = '';
  for (let d = 1; d <= n; d++) {
    const el = document.createElement('div');
    const before = ym[0] * 400 + ym[1] * 32 + d < start[0] * 400 + start[1] * 32 + start[2];
    el.className = 'date-picker-body-item ' + (before ? 'date-item-disabled' : 'date-item');
    el.style.cssText = 'display:inline-block;width:20px;height:20px';
    el.innerText = ' ' + d + ' ';
    el.onclick = () => { if (before) return; $('#d').innerText = ym[0] + '-' + pad(ym[1]) + '-' + pad(d);
                         $('.date-picker-container').style.display = 'none'; };
    $('#days').appendChild(el);
  }
};
$('.date-picker-date').onclick = () => {
  const p = $('.date-picker-container'); p.style.display = p.style.display === 'none' ? '' : 'none'; renderDays();
};
$('.next-btn-month').onclick = () => { ym = ym[1] === 12 ? [ym[0] + 1, 1] : [ym[0], ym[1] + 1]; renderDays(); };
const col = (id, values, pos) => {
  $(id).innerHTML = '';
  for (const v of values) {
    const el = document.createElement('span');
    el.className = 'time-picker-panel-select-item';
    el.style.cssText = 'display:inline-block;width:20px;height:20px';
    el.innerText = v;
    el.onclick = () => { const t = $('#t').innerText.split(':'); t[pos] = v; $('#t').innerText = t.join(':'); };
    $(id).appendChild(el);
  }
};
col('#hours', Array.from({length: 24}, (_, i) => pad(i)), 0);
col('#mins', Array.from({length: 12}, (_, i) => pad(i * 5)), 1);
$('.date-picker-timer').onclick = () => {
  const p = $('.time-picker-container'); p.style.display = p.style.display === 'none' ? '' : 'none';
};
</script>
</body></html>
"""

BEIJING_TZ = "(UTC+08:00) Beijing, Chongqing, Hong Kong SAR, Urumqi"


def _target(days: int) -> datetime:
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    t = now + timedelta(days=days)
    return t.replace(minute=t.minute - t.minute % 5)


@pytest.fixture()
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome, headless=True)
        yield browser.new_page()
        browser.close()


def _load(page, tz=BEIJING_TZ):
    now = datetime.now(timezone.utc).astimezone(PICKER_TZ) + timedelta(minutes=5)
    page.set_content(HTML.replace("__TZ__", tz).replace("__DATE__", now.strftime("%Y-%m-%d"))
                     .replace("__TIME__", now.strftime("%H:%M")))


def _meta(tmp_path, when: datetime):
    return parse_meta({"video": "v.mp4", "title": "标题", "creation_statement": "内容无需标注",
                       "schedule": when.astimezone(timezone(timedelta(hours=-7))).isoformat()},
                      base_dir=tmp_path, check_files=False)


@pytest.mark.parametrize("days", [1, 14])
def test_schedule_sets_date_and_time(page, tmp_path, days):
    when = _target(days)
    # 14 天后多半跨月：顺带检验翻页
    _load(page)
    meta = _meta(tmp_path, when)
    form = Form(page)
    assert step_schedule(form, meta) is None
    local = when.astimezone(PICKER_TZ)
    assert page.locator("#d").inner_text() == local.strftime("%Y-%m-%d")
    assert page.locator("#t").inner_text() == local.strftime("%H:%M")
    assert page.locator(".date-picker-container").is_hidden() and page.locator(".time-picker-container").is_hidden()
    rb = readback(page, meta)
    assert rb["values"]["schedule"].startswith(local.strftime("%Y-%m-%d %H:%M (UTC+08:00)"))
    assert "schedule" not in rb["mismatches"]


def test_schedule_refuses_other_time_zone(page, tmp_path):
    _load(page, tz="(UTC-07:00) America/Phoenix")
    with pytest.raises(RuntimeError, match="only sets times"):
        step_schedule(Form(page), _meta(tmp_path, _target(1)))


def test_schedule_refuses_out_of_window(page, tmp_path):
    _load(page)
    with pytest.raises(RuntimeError, match="more than 15 days"):
        step_schedule(Form(page), _meta(tmp_path, _target(16)))
