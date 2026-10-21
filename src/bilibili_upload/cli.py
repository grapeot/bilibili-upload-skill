"""bili-upload 命令行入口。每个子命令向 stdout 输出恰好一个 JSON 对象。"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import __version__
from .browser import open_browser, session_from_env, status
from .meta import MetaError, load_meta
from .plan import build_plan
from .selectors import SELECTORS, UPLOAD_URL


def _emit(obj: dict[str, Any]) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=1))


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # 用法错误也输出 JSON
        _emit({"ok": False, "error": f"usage: {message}"})
        sys.exit(2)


def build_parser() -> argparse.ArgumentParser:
    ap = _Parser(prog="bili-upload", description="在可见 Chrome 里填写 B 站投稿表单，停在提交前。")
    ap.add_argument("--version", action="store_true", help="输出版本号")
    ap.add_argument("--port", type=int, help="CDP 端口（默认 $BILI_CDP_PORT 或 9341）")
    ap.add_argument("--profile-dir", help="Chrome profile 目录（默认 $BILI_PROFILE_DIR 或 ~/.bilibili-upload/browser-profile）")
    sub = ap.add_subparsers(dest="cmd", parser_class=_Parser)

    o = sub.add_parser("open", help="启动可见 Chrome（端口或 profile 被占用时拒绝）")
    o.add_argument("--url", default=UPLOAD_URL)
    sub.add_parser("status", help="只读：浏览器是否在线、是否已登录")

    f = sub.add_parser("fill", help="填写投稿表单；默认 dry-run")
    f.add_argument("--meta", required=True, help="投稿元数据 JSON")
    f.add_argument("--execute", action="store_true", help="真正执行：选择视频（开始上传）并填表")
    f.add_argument("--reuse-tab", action="store_true", help="接入已选好视频的投稿标签页，不再选择文件")
    f.add_argument("--upload-timeout", type=float, default=1800, help="等待上传处理的秒数（默认 1800）")
    f.add_argument("--new-upload", action="store_true", help="已有投稿标签页时仍新开一个上传（会再上传一次）")
    f.add_argument("--no-wait", action="store_true", help="不等待上传完成")

    r = sub.add_parser("readback", help="只读：把当前投稿标签页的字段读回并与元数据比对")
    r.add_argument("--meta", required=True)

    sub.add_parser("selectors", help="列出所有选择器；若浏览器在线，统计当前投稿页的匹配数（只读）")
    return ap


def _with_upload_tab(session, fn, video=None, title=None) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    from .browser import connect, verify_own_browser
    from .fill import find_upload_tab

    own = verify_own_browser(session)
    if not own["ok"]:
        return own
    with sync_playwright() as p:
        _, ctx = connect(p, session)
        page = find_upload_tab(ctx, video, title)
        if page is None:
            return {"ok": False, "error": "no upload tab with a selected video found"}
        return fn(page)


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        session = session_from_env(args.port, args.profile_dir)
        if args.version:
            out = {"ok": True, "version": __version__}
        elif args.cmd is None:
            out = {"ok": False, "error": "usage: a command is required (open, status, fill, readback, selectors)"}
        elif args.cmd == "open":
            out = open_browser(session, args.url)
        elif args.cmd == "status":
            out = status(session)
        elif args.cmd == "fill":
            meta = load_meta(args.meta)
            plan = build_plan(meta, reuse_tab=args.reuse_tab)
            if not args.execute:
                out = {"ok": True, "dry_run": True, **plan,
                       "next": "确认视频所有者授权上传这个视频后，加 --execute 执行"}
            else:
                from .fill import execute

                out = execute(session, meta, reuse_tab=args.reuse_tab, upload_timeout_s=args.upload_timeout,
                              wait_for_upload=not args.no_wait, new_upload=args.new_upload)
        elif args.cmd == "readback":
            meta = load_meta(args.meta)
            from .fill import readback, upload_state

            def rb(pg):
                res = readback(pg, meta)
                return {"ok": not res["mismatches"], "upload": upload_state(pg), **res}
            out = _with_upload_tab(session, rb, meta.video, meta.title)
        elif args.cmd == "selectors":
            listing = {k: {"css": v.css, "note": v.note} for k, v in SELECTORS.items()}
            from .browser import port_in_use

            if port_in_use(session.port):
                def count(pg):
                    return {"ok": True, "selectors": {k: {**listing[k], "count": pg.locator(v.css).count()}
                                                      for k, v in SELECTORS.items()}}
                out = _with_upload_tab(session, count)
                if not out.get("ok"):
                    out = {"ok": True, "selectors": listing, "note": out.get("error")}
            else:
                out = {"ok": True, "selectors": listing, "note": "browser not running; counts unavailable"}
        else:  # pragma: no cover - argparse 已保证
            out = {"ok": False, "error": f"unknown command {args.cmd}"}
    except MetaError as e:
        out = {"ok": False, "error": "invalid metadata", "problems": e.problems}
    except KeyboardInterrupt:
        out = {"ok": False, "error": "interrupted"}
    except Exception as e:  # noqa: BLE001 - 原样透出异常类型和信息
        out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    _emit(out)
    return 0 if out.get("ok") else 1


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
