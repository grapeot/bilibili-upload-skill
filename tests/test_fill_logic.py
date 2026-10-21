from pathlib import Path

from bilibili_upload.browser import browser_matches
from bilibili_upload.fill import classify_upload, compare, tab_matches_video
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
           "chapters_section": "章节管理 00:00 开场", "subtitles_section": "字幕设置"}
    mismatches, _ = compare(got, meta)
    assert set(mismatches) == {"subtitles_section"}


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
    assert tab_matches_video("my_video_v4.mp4 上传完成", v)
    assert tab_matches_video("my_video_v4 上传中 3%", v)
    assert not tab_matches_video("other.mp4", v)
