"""投稿元数据：读取、校验、规范化。格式说明见 skills/bilibili-upload/SKILL.md。"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TITLE_MAX = 80
TAGS_MAX = 10
TAG_MAX = 20
DESC_MAX = 2000
DYNAMIC_MAX = 233
VIDEO_EXTS = {".mp4", ".flv", ".avi", ".wmv", ".mov", ".webm", ".mpeg4", ".ts", ".mpg", ".rm", ".rmvb", ".mkv", ".m4v"}
COVER_EXTS = {".jpg", ".jpeg", ".png"}
VISIBILITIES = ("public", "self")
KNOWN_KEYS = {
    "video", "title", "cover", "creation_statement", "partition", "tags", "description",
    "chapters", "subtitles", "visibility", "dynamic",
}


class MetaError(ValueError):
    """元数据不合法。message 列出所有问题，而不是只报第一个。"""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class Chapter:
    start: float
    title: str

    @property
    def timestamp(self) -> str:
        return format_timestamp(self.start)


@dataclass
class Subtitles:
    path: Path
    language: str = "中文"
    default_on: bool = False


@dataclass
class UploadMeta:
    video: Path
    title: str
    creation_statement: str
    cover: Path | None = None
    partition: str | None = None
    tags: list[str] = field(default_factory=list)
    description: str = ""
    chapters: list[Chapter] = field(default_factory=list)
    subtitles: Subtitles | None = None
    visibility: str = "public"
    dynamic: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "video": str(self.video),
            "title": self.title,
            "cover": str(self.cover) if self.cover else None,
            "creation_statement": self.creation_statement,
            "partition": self.partition,
            "tags": self.tags,
            "description": self.description,
            "chapters": [{"start": c.start, "time": c.timestamp, "title": c.title} for c in self.chapters],
            "subtitles": (
                {"path": str(self.subtitles.path), "language": self.subtitles.language,
                 "default_on": self.subtitles.default_on}
                if self.subtitles else None
            ),
            "visibility": self.visibility,
            "dynamic": self.dynamic,
        }


_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_TS = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})(?:\.(\d+))?$")


def parse_timestamp(value: Any) -> float:
    """秒数（int/float）或 MM:SS / HH:MM:SS 字符串 -> 秒。"""
    if isinstance(value, bool):
        raise ValueError(f"bad timestamp: {value!r}")
    if isinstance(value, (int, float)):
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"negative timestamp: {value!r}")
        return float(value)
    if isinstance(value, str):
        m = _TS.match(value.strip())
        if m:
            h, mnt, sec, frac = m.groups()
            if int(sec) >= 60 or (h is not None and int(mnt) >= 60):
                raise ValueError(f"bad timestamp: {value!r}")
            total = int(h or 0) * 3600 + int(mnt) * 60 + int(sec)
            return total + (float(f"0.{frac}") if frac else 0.0)
    raise ValueError(f"bad timestamp: {value!r}")


def format_timestamp(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def _resolve(base: Path, value: str) -> Path:
    p = Path(value).expanduser()
    return p if p.is_absolute() else (base / p)


def parse_meta(data: dict[str, Any], base_dir: Path, check_files: bool = True) -> UploadMeta:
    """校验并规范化一个元数据字典。所有问题一次性收集后抛出 MetaError。"""
    problems: list[str] = []
    if not isinstance(data, dict):
        raise MetaError(["metadata must be a JSON object"])

    unknown = sorted(set(data) - KNOWN_KEYS)
    if unknown:
        problems.append(f"unknown keys: {unknown}")

    def need_file(key: str, value: Any, exts: set[str] | None) -> Path | None:
        if not isinstance(value, str) or not value.strip():
            problems.append(f"{key}: must be a non-empty path string")
            return None
        p = _resolve(base_dir, value)
        if exts is not None and p.suffix.lower() not in exts:
            problems.append(f"{key}: unsupported extension {p.suffix!r} (allowed: {sorted(exts)})")
        if check_files and not p.is_file():
            problems.append(f"{key}: file not found: {p}")
        return p.resolve() if check_files and p.is_file() else p

    video = need_file("video", data.get("video"), VIDEO_EXTS)

    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        problems.append("title: required")
        title = ""
    elif (title := title.strip()) and _CONTROL.search(title):
        problems.append("title: must not contain line breaks or control characters")
    elif len(title) > TITLE_MAX:
        problems.append(f"title: {len(title)} chars > {TITLE_MAX}")

    statement = data.get("creation_statement")
    if not isinstance(statement, str) or not statement.strip():
        problems.append("creation_statement: required (the option text shown on the page, e.g. 内容无需标注)")
        statement = ""

    cover = None
    if data.get("cover") is not None:
        cover = need_file("cover", data["cover"], COVER_EXTS)

    partition = data.get("partition")
    if partition is not None and (not isinstance(partition, str) or not partition.strip()):
        problems.append("partition: must be a non-empty string when given")

    tags = data.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        problems.append("tags: must be a list of strings")
        tags = []
    else:
        tags = [t.strip() for t in tags]
        if len(tags) > TAGS_MAX:
            problems.append(f"tags: {len(tags)} > {TAGS_MAX}")
        for t in tags:
            if not t:
                problems.append("tags: empty tag")
            elif "," in t or "，" in t:
                problems.append(f"tags: {t!r} contains a comma (B站 splits tags on commas)")
            elif len(t) > TAG_MAX:
                problems.append(f"tags: {t!r} is {len(t)} chars > {TAG_MAX}")
        if len(set(tags)) != len(tags):
            problems.append("tags: duplicates")

    desc = data.get("description", "")
    if not isinstance(desc, str):
        problems.append("description: must be a string")
        desc = ""
    elif len(desc) > DESC_MAX:
        problems.append(f"description: {len(desc)} chars > {DESC_MAX}")

    chapters: list[Chapter] = []
    raw_ch = data.get("chapters", [])
    if not isinstance(raw_ch, list):
        problems.append("chapters: must be a list")
    else:
        for i, ch in enumerate(raw_ch):
            if not isinstance(ch, dict) or "title" not in ch or "start" not in ch:
                problems.append(f"chapters[{i}]: needs start and title")
                continue
            try:
                start = parse_timestamp(ch["start"])
            except ValueError as e:
                problems.append(f"chapters[{i}]: {e}")
                continue
            t = ch["title"]
            if not isinstance(t, str) or not t.strip():
                problems.append(f"chapters[{i}]: empty title")
                continue
            chapters.append(Chapter(start=start, title=t.strip()))
        if chapters:
            if chapters[0].start != 0:
                problems.append("chapters: the first chapter must start at 0")
            if any(b.start <= a.start for a, b in zip(chapters, chapters[1:])):
                problems.append("chapters: start times must be strictly increasing")

    subtitles = None
    raw_sub = data.get("subtitles")
    if raw_sub is not None:
        if not isinstance(raw_sub, dict):
            problems.append("subtitles: must be an object {path, language, default_on}")
        else:
            sp = need_file("subtitles.path", raw_sub.get("path"), {".srt"})
            lang = raw_sub.get("language", "中文")
            if not isinstance(lang, str) or not lang.strip():
                problems.append("subtitles.language: must be a non-empty string")
            default_on = raw_sub.get("default_on", False)
            if not isinstance(default_on, bool):
                problems.append("subtitles.default_on: must be true or false")
            if sp is not None:
                subtitles = Subtitles(path=sp, language=lang, default_on=bool(default_on))

    visibility = data.get("visibility", "public")
    if visibility not in VISIBILITIES:
        problems.append(f"visibility: must be one of {VISIBILITIES}")

    dynamic = data.get("dynamic", "")
    if not isinstance(dynamic, str):
        problems.append("dynamic: must be a string")
        dynamic = ""
    elif len(dynamic) > DYNAMIC_MAX:
        problems.append(f"dynamic: {len(dynamic)} chars > {DYNAMIC_MAX}")

    if problems:
        raise MetaError(problems)
    assert video is not None
    return UploadMeta(
        video=video, title=title, creation_statement=statement.strip(), cover=cover,
        partition=partition.strip() if partition else None, tags=tags, description=desc,
        chapters=chapters, subtitles=subtitles, visibility=visibility, dynamic=dynamic,
    )


def load_meta(path: str | Path, check_files: bool = True) -> UploadMeta:
    p = Path(path).expanduser()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise MetaError([f"invalid JSON: {e}"]) from e
    return parse_meta(data, base_dir=p.resolve().parent, check_files=check_files)
