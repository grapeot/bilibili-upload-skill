import pytest
from pathlib import Path

from bilibili_upload.browser import browser_matches
from bilibili_upload.fill import classify_upload, compare, subtitle_chooser_ok, tab_matches_video
from bilibili_upload.meta import parse_meta


def _meta(tmp_path, **extra):
    data = {"video": "v.mp4", "title": "标题", "creation_statement": "内容无需标注", **extra}
    return parse_meta(data, base_dir=tmp_path, check_files=False)


def test_classify_upload():
    assert classify_upload(1, "v.mp4 上传完成")["done"] is True
    assert classify_upload(1, "v.mp4 100%")["done"] is True
    assert classify_upload(1, "v.mp4 上传中 37%")["done"] is False
    assert classify_upload(1, "v.mp4 5.5%")["in_progress"] is True
    assert classify_upload(1, "v.mp4 上传失败")["failed"] is True
    assert classify_upload(0, "")["done"] is False
    assert classify_upload(1, "上传完成 100.0%")["done"] is True
    assert classify_upload(1, "100.00%")["done"] is True


def test_compare_reports_null_as_missing(tmp_path):
    meta = _meta(tmp_path, tags=["a"], partition="知识")
    got = {"title": "标题", "creation_statement": "内容无需标注", "visibility": None, "tags": ["a"], "partition": "知识"}
    mismatches, missing = compare(got, meta)
    assert "visibility_checked" in missing and set(mismatches) == {"visibility"}


def test_compare_detects_mismatch(tmp_path):
    meta = _meta(tmp_path, description="一\n\n二")
    got = {"title": "别的", "creation_statement": "内容无需标注", "visibility": "公开可见", "description": "一\n二"}
    mismatches, missing = compare(got, meta)
    assert set(mismatches) == {"title"} and missing == []


def test_compare_chapters_and_subtitles(tmp_path):
    meta = _meta(tmp_path, chapters=[{"start": 0, "title": "开场"}], subtitles={"path": "s.srt"})
    got = {"title": "标题", "creation_statement": "内容无需标注", "visibility": "公开可见",
           "chapters_section": "章节管理 已配置章节 编辑章节", "subtitles_section": "字幕设置 上传字幕"}
    mismatches, _ = compare(got, meta)
    assert set(mismatches) == {"subtitles_section"}
    got["subtitles_section"] = "字幕设置 已上传【中文】字幕"
    assert compare(got, meta)[0] == {}


def test_compare_tags_extra_is_mismatch_rejected_is_not(tmp_path):
    meta = _meta(tmp_path, tags=["a", "b", "c"])
    base = {"title": "标题", "creation_statement": "内容无需标注", "visibility": "公开可见"}
    assert compare({**base, "tags": ["a", "c"]}, meta)[0] == {}  # b 被静默拒收：只告警
    assert "tags" in compare({**base, "tags": ["a", "前端"]}, meta)[0]  # 多出自动带入的标签


def test_chapters_text_format(tmp_path):
    from bilibili_upload.fill import chapters_text

    meta = _meta(tmp_path, chapters=[{"start": 0, "title": "开场"}, {"start": 229.4, "title": "第二"}])
    assert chapters_text(meta) == "00:00 开场\n03:49 第二"


def test_browser_matches():
    prof = Path("/tmp/prof")
    lines = ["/x/Chrome --remote-debugging-port=9341 --user-data-dir=/tmp/prof --no-first-run",
             "/x/Chrome --remote-debugging-port=9222 --user-data-dir=/tmp/other"]
    assert browser_matches(lines, 9341, prof)
    assert not browser_matches(lines, 9222, prof)
    assert not browser_matches(lines, 93410, prof)
    assert not browser_matches(["C --remote-debugging-port=9341 --user-data-dir=/tmp/prof-old"], 9341, prof)
    assert browser_matches(["C --remote-debugging-port=9341 --user-data-dir=/tmp/prof"], 9341, prof)


def test_tab_matches_video():
    v = Path("/x/my_video_v4.mp4")
    assert tab_matches_video("my_video_v4.mp4 上传完成", None, v)
    assert tab_matches_video("my_video_v4 上传中 3%", None, v)
    assert tab_matches_video("", "my_video_v4", v)  # 标题框里是自动带入的文件名
    assert tab_matches_video("", "我的标题", v, "我的标题")  # 已经填过标题
    assert not tab_matches_video("other.mp4", "别的标题", v, "我的标题")
    assert not tab_matches_video("", "", v, "我的标题")
    assert not tab_matches_video("intro_my_video_v4.mp4 上传中", None, v)  # 不做子串匹配
    assert not tab_matches_video("data.mp4", None, Path("/x/a.mp4"))


@pytest.mark.parametrize("inside, detached, accept, name, ok", [
    (True, False, ".srt", "", True),
    (True, False, "", "", True),
    (False, True, ".srt", "", True),          # 点击时临时创建、不挂到文档里的字幕输入框
    (False, True, "", "", False),             # 游离且没声明 .srt：不认
    (False, False, ".srt", "", False),        # 挂在文档里但不在弹窗内
    (True, False, ".mp4,.flv", "", False),
    (False, True, ".srt", "buploader", False),
])
def test_subtitle_chooser_ok(inside, detached, accept, name, ok):
    assert subtitle_chooser_ok(inside, detached, accept, name) is ok


def test_classify_upload_stalled_at_zero_total():
    stuck = classify_upload(1, "film 上传中... 已经上传：0.0MB/0.0MB 当前速度：0.0MB/s 剩余时间：>1天 0%")
    assert stuck["stalled"] is True and stuck["done"] is False
    starting = classify_upload(1, "film 上传中... 已经上传：0.0MB/70.7MB 当前速度：0.0MB/s 0%")
    assert starting["stalled"] is False
    assert classify_upload(1, "film 上传完成")["stalled"] is False


def test_compare_schedule(tmp_path):
    meta = _meta(tmp_path, schedule="2026-10-23T16:00-07:00")
    base = {"title": "标题", "creation_statement": "内容无需标注", "visibility": "公开可见"}
    ok = {**base, "schedule": "2026-10-24 07:00 (UTC+08:00) Beijing, Chongqing, Hong Kong SAR, Urumqi"}
    assert compare(ok, meta)[0] == {}
    assert "schedule" in compare({**base, "schedule": "off"}, meta)[0]
    assert "schedule" in compare({**base, "schedule": "2026-10-24 07:05 (UTC+08:00) Beijing"}, meta)[0]
    assert compare(base, _meta(tmp_path))[0] == {}  # 没有定时：不读这一项
