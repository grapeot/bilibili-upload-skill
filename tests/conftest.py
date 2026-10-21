import json
from pathlib import Path

import pytest


@pytest.fixture
def media(tmp_path: Path) -> Path:
    """合成的占位文件：内容无意义，只用来通过存在性检查。"""
    (tmp_path / "video.mp4").write_bytes(b"\x00" * 16)
    (tmp_path / "cover.jpg").write_bytes(b"\xff\xd8\xff")
    (tmp_path / "subs.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n测试\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def good_meta() -> dict:
    return {
        "video": "video.mp4",
        "title": "测试标题",
        "cover": "cover.jpg",
        "creation_statement": "内容无需标注",
        "partition": "知识",
        "tags": ["标签一", "标签二"],
        "description": "第一段\n\n第二段",
        "chapters": [{"start": 0, "title": "开场"}, {"start": "05:00", "title": "第二部分"}],
        "subtitles": {"path": "subs.srt"},
        "visibility": "public",
        "dynamic": "动态",
    }


@pytest.fixture
def write_meta(media: Path):
    def _write(data: dict) -> Path:
        p = media / "upload.json"
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return p
    return _write
