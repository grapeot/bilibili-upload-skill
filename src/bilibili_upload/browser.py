"""可见 Chrome 会话：启动（open）、只读登录检查（status）、CDP 连接。

Chrome 用独立的持久 profile 启动，调试端口只绑定 127.0.0.1。脚本通过
Playwright connect_over_cdp 接入，结束时只断开连接，不关闭浏览器。
本模块不读取、不打印 cookie；status 只输出布尔值、标签页数量、接口返回码和页面主机名
（不输出路径，避免个人空间页之类的地址带出账号 ID）。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .selectors import NAV_API, UPLOAD_URL

DEFAULT_PORT = 9341
SINGLETON_FILES = ("SingletonLock", "SingletonSocket", "SingletonCookie")
CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)


@dataclass
class Session:
    port: int
    profile_dir: Path

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def session_from_env(port: int | None = None, profile_dir: str | None = None) -> Session:
    port = port or int(os.environ.get("BILI_CDP_PORT", DEFAULT_PORT))
    prof = profile_dir or os.environ.get("BILI_PROFILE_DIR") or str(Path.home() / ".bilibili-upload" / "browser-profile")
    return Session(port=port, profile_dir=Path(prof).expanduser())


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def profile_in_use(profile: Path) -> bool:
    return any(os.path.lexists(profile / n) for n in SINGLETON_FILES)


def find_chrome() -> str | None:
    explicit = os.environ.get("BILI_CHROME_EXECUTABLE")
    if explicit:
        return explicit if os.path.exists(explicit) else None
    for c in CHROME_CANDIDATES:
        if os.path.exists(c):
            return c
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


def open_browser(session: Session, url: str = UPLOAD_URL) -> dict[str, Any]:
    if port_in_use(session.port):
        return {"ok": False, "error": f"port {session.port} already in use; run `bili-upload status` or set BILI_CDP_PORT"}
    if profile_in_use(session.profile_dir):
        return {"ok": False, "error": "profile is locked by a running Chrome", "profile_dir": str(session.profile_dir)}
    chrome = find_chrome()
    if not chrome:
        return {"ok": False, "error": "Chrome not found; set BILI_CHROME_EXECUTABLE"}
    session.profile_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(session.profile_dir, 0o700)
    if session.profile_dir.parent != Path.home():
        os.chmod(session.profile_dir.parent, 0o700)  # browser.log 也放在这里
    log_path = session.profile_dir.parent / "browser.log"
    with open(log_path, "ab") as log:
        proc = subprocess.Popen(
            [
                chrome,
                f"--remote-debugging-port={session.port}",
                "--remote-debugging-address=127.0.0.1",
                f"--user-data-dir={session.profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "--window-size=1500,1000",
                url,
            ],
            stdout=log, stderr=log, stdin=subprocess.DEVNULL,
            start_new_session=True,  # 浏览器不随启动它的 shell 退出
        )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return {"ok": False, "error": "Chrome exited early", "log": str(log_path)}
        try:
            with urllib.request.urlopen(f"{session.endpoint}/json/version", timeout=2) as r:
                json.loads(r.read())
            return {"ok": True, "pid": proc.pid, "cdp_endpoint": session.endpoint,
                    "profile_dir": str(session.profile_dir), "url": url,
                    "next": "在窗口里扫码登录，然后运行 bili-upload status"}
        except Exception:  # noqa: BLE001 - 等端口就绪
            time.sleep(0.3)
    return {"ok": False, "error": "CDP endpoint did not come up within 20s", "log": str(log_path)}


def browser_matches(cmdlines: list[str], port: int, profile_dir: Path) -> bool:
    """纯函数：是否有一个进程同时带着这个调试端口和这个 profile 启动。"""
    want_port = f"--remote-debugging-port={port}"
    pats = [re.compile(re.escape(f"--user-data-dir={d}") + r"(\s|$)") for d in {profile_dir, profile_dir.resolve()}]
    return any(want_port in line.split() and any(pt.search(line) for pt in pats) for line in cmdlines)


def verify_own_browser(session: Session) -> dict[str, Any]:
    """确认端口上的 Chrome 正是用 session.profile_dir 启动的那个，否则拒绝操作。"""
    try:
        out = subprocess.run(["ps", "-axww", "-o", "args="], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "error": f"cannot list processes to verify the browser: {type(e).__name__}"}
    if browser_matches(out.splitlines(), session.port, session.profile_dir):
        return {"ok": True}
    return {"ok": False, "error": f"the browser on port {session.port} was not started with this profile; "
            "set --profile-dir / BILI_PROFILE_DIR to the profile used by `bili-upload open`"}


def connect(p, session: Session):
    """接入已运行的 Chrome。调用方结束时只让 Playwright 退出，不关闭浏览器。"""
    browser = p.chromium.connect_over_cdp(session.endpoint, timeout=10000)
    if not browser.contexts:
        raise RuntimeError("browser has no default context")
    return browser, browser.contexts[0]


_LOGIN_JS = """async (url) => {
  try {
    const r = await fetch(url, {credentials: 'include'});
    const j = await r.json();
    return {logged_in: !!(j.data && j.data.isLogin), api_code: j.code};
  } catch (e) { return {logged_in: null, error: String(e)}; }
}"""


def check_login(page) -> dict[str, Any]:
    """只读：调用 nav 接口，只返回 isLogin 布尔值和返回码。"""
    return page.evaluate(_LOGIN_JS, NAV_API)


def status(session: Session) -> dict[str, Any]:
    if not port_in_use(session.port):
        return {"ok": False, "browser_connected": False, "hint": "run: bili-upload open"}
    from playwright.sync_api import sync_playwright

    own = verify_own_browser(session)
    if not own["ok"]:
        return {**own, "browser_connected": True}
    with sync_playwright() as p:
        _, ctx = connect(p, session)
        pages = [pg for pg in ctx.pages if "bilibili.com" in pg.url]
        info: dict[str, Any] = {"ok": True, "browser_connected": True, "bilibili_tabs": len(pages)}
        page = pages[0] if pages else None
        if page is None:  # 没有 B 站标签页时开一个探测页（不填写、不点击）
            page = ctx.new_page()
            page.goto("https://member.bilibili.com/", wait_until="domcontentloaded")
            info["opened_probe_tab"] = True
        host = urllib.parse.urlsplit(page.url).hostname or ""
        info["host"] = host
        info["on_upload_page"] = page.url.startswith(UPLOAD_URL)
        info["on_login_page"] = host == "passport.bilibili.com"
        info.update(check_login(page))
        if info.get("logged_in") is not True:
            info["hint"] = "请在浏览器窗口里扫码登录（工具不会代为登录）"
        return info
