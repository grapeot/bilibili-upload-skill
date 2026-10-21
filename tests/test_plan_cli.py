import json

from bilibili_upload.cli import run
from bilibili_upload.meta import load_meta
from bilibili_upload.plan import build_plan
from bilibili_upload.selectors import SELECTORS


def test_plan_order_and_stop(write_meta, good_meta):
    plan = build_plan(load_meta(write_meta(good_meta)))
    steps = [s["step"] for s in plan["steps"]]
    assert steps[0] == "open_tab" and steps[1] == "select_video"
    assert steps[-1] == "stop_before_submit"
    for s in ("title", "cover", "creation_statement", "partition", "tags", "description",
              "visibility", "subtitles", "chapters", "dynamic", "readback"):
        assert s in steps
    assert any("立即投稿" in h for h in plan["human_steps"])
    assert any("字幕" in h for h in plan["human_steps"])


def test_plan_reuse_tab_skips_file_selection(write_meta, good_meta):
    steps = [s["step"] for s in build_plan(load_meta(write_meta(good_meta)), reuse_tab=True)["steps"]]
    assert "select_video" not in steps and steps[0] == "reuse_tab"


def test_cli_dry_run_is_default(write_meta, good_meta, capsys, monkeypatch):
    import bilibili_upload.fill as fill

    monkeypatch.setattr(fill, "execute", lambda *a, **k: (_ for _ in ()).throw(AssertionError("executed")))
    assert run(["fill", "--meta", str(write_meta(good_meta))]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True and out["ok"] is True


def test_cli_invalid_meta_is_single_json(write_meta, capsys):
    assert run(["fill", "--meta", str(write_meta({"title": ""}))]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["problems"]


def test_cli_usage_error_is_json(capsys):
    import pytest

    with pytest.raises(SystemExit) as ei:
        run(["fill"])
    assert ei.value.code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and "usage" in out["error"]


def test_selectors_listing_offline(capsys, monkeypatch):
    import bilibili_upload.browser as browser

    monkeypatch.setattr(browser, "port_in_use", lambda port: False)
    assert run(["selectors"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert set(out["selectors"]) == set(SELECTORS)


def test_every_selector_has_note():
    for name, sel in SELECTORS.items():
        assert sel.css and sel.note, name


def test_cli_version_is_json(capsys):
    assert run(["--version"]) == 0
    assert json.loads(capsys.readouterr().out)["version"]


def test_cli_bad_env_is_json(capsys, monkeypatch):
    monkeypatch.setenv("BILI_CDP_PORT", "abc")
    assert run(["status"]) == 1
    assert "ValueError" in json.loads(capsys.readouterr().out)["error"]
