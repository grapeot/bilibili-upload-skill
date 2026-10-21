import pytest

from bilibili_upload.meta import MetaError, format_timestamp, load_meta, parse_meta, parse_timestamp


def test_good_meta_resolves_relative_paths(write_meta, good_meta, media):
    meta = load_meta(write_meta(good_meta))
    assert meta.video == (media / "video.mp4").resolve()
    assert meta.subtitles.path.name == "subs.srt"
    assert meta.subtitles.default_on is False
    assert meta.subtitles.language == "中文"
    assert [c.start for c in meta.chapters] == [0.0, 300.0]
    assert meta.visibility == "public"


def test_minimal_meta(write_meta):
    meta = load_meta(write_meta({"video": "video.mp4", "title": "t", "creation_statement": "内容无需标注"}))
    assert meta.tags == [] and meta.chapters == [] and meta.subtitles is None and meta.cover is None


def test_collects_all_problems(write_meta):
    bad = {
        "video": "missing.mp4", "title": "x" * 81, "tags": ["a"] * 11, "description": "d" * 2001,
        "visibility": "friends", "dynamic": "y" * 234, "extra": 1,
    }
    with pytest.raises(MetaError) as ei:
        load_meta(write_meta(bad))
    text = " ".join(ei.value.problems)
    for needle in ("unknown keys", "video: file not found", "title:", "creation_statement",
                   "tags: 11", "duplicates", "description:", "visibility", "dynamic:"):
        assert needle in text, needle


@pytest.mark.parametrize("tags,needle", [
    (["x" * 21], "21 chars"),
    ([""], "empty tag"),
    ("a,b", "list of strings"),
])
def test_tag_rules(write_meta, good_meta, tags, needle):
    good_meta["tags"] = tags
    with pytest.raises(MetaError) as ei:
        load_meta(write_meta(good_meta))
    assert needle in str(ei.value)


@pytest.mark.parametrize("chapters,needle", [
    ([{"start": 5, "title": "a"}], "start at 0"),
    ([{"start": 0, "title": "a"}, {"start": 0, "title": "b"}], "strictly increasing"),
    ([{"start": "1:99", "title": "a"}], "bad timestamp"),
    ([{"start": 0}], "needs start and title"),
    ([{"start": 0, "title": " "}], "empty title"),
])
def test_chapter_rules(write_meta, good_meta, chapters, needle):
    good_meta["chapters"] = chapters
    with pytest.raises(MetaError) as ei:
        load_meta(write_meta(good_meta))
    assert needle in str(ei.value)


def test_subtitles_must_be_srt(write_meta, good_meta, media):
    (media / "subs.vtt").write_text("WEBVTT\n", encoding="utf-8")
    good_meta["subtitles"] = {"path": "subs.vtt"}
    with pytest.raises(MetaError) as ei:
        load_meta(write_meta(good_meta))
    assert "unsupported extension" in str(ei.value)


def test_check_files_false_skips_existence(tmp_path, good_meta):
    meta = parse_meta(good_meta, base_dir=tmp_path / "nowhere", check_files=False)
    assert meta.title == "测试标题"


@pytest.mark.parametrize("value,seconds", [(0, 0.0), (229.4, 229.4), ("03:49", 229.0), ("1:02:03", 3723.0), ("00:05.5", 5.5)])
def test_parse_timestamp(value, seconds):
    assert parse_timestamp(value) == pytest.approx(seconds)


@pytest.mark.parametrize("value", [-1, "abc", True, None, "1:60"])
def test_parse_timestamp_rejects(value):
    with pytest.raises(ValueError):
        parse_timestamp(value)


def test_format_timestamp():
    assert format_timestamp(229.4) == "03:49"
    assert format_timestamp(3723) == "01:02:03"
