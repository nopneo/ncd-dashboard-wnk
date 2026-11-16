import pytest

import pages
import sections
import ui
from app import app


def test_pct():
    assert ui.pct(946, 2663) == 35.5
    assert ui.pct(1, 0) is None
    assert ui.pct(1, None) is None
    assert ui.pct(0, 10) == 0.0


def test_formatters():
    assert ui.fmt_pct(None) == "—"
    assert ui.fmt_pct(76.14) == "76.1%"
    assert ui.fmt_int(None) == "—"
    assert ui.fmt_int(1234.4) == "1,234"


def test_delta():
    assert ui.delta(110, 100) == {"pct": 10.0, "dir": "up"}
    assert ui.delta(90, 100) == {"pct": -10.0, "dir": "down"}
    assert ui.delta(100, 100) == {"pct": 0.0, "dir": "flat"}
    assert ui.delta(5, 0)["pct"] is None
    assert ui.delta(None, 5)["pct"] is None


def test_donut_segments():
    segs = ui.donut_segments([("a", 50, "#000"), ("b", 50, "#fff")])
    assert [s["pct"] for s in segs] == [50.0, 50.0]
    assert segs[0]["dash"] == "50.0 50.0" and segs[1]["offset"] == 25 - 50.0
    assert ui.donut_segments([("a", 0, "#000"), ("b", 0, "#fff")]) == []


def test_nice_max_and_bars():
    assert ui.nice_max(1188) == 1200
    assert ui.nice_max(0) == 1
    assert ui.nice_max(7) == 8
    g = ui.bar_geometry({"labels": ["a", "b"], "series": [{"name": "x", "values": [10, None], "color": "#123"}]})
    assert g["max"] >= 10 and len(g["groups"]) == 2
    assert g["groups"][0]["bars"][0]["height"] == pytest.approx(100 * 10 / g["max"])
    assert g["groups"][1]["bars"][0]["height"] == 0 and g["groups"][1]["bars"][0]["value"] is None


def test_safe_returns_error_dict():
    out = sections.safe("ความดัน", lambda: 1 / 0)
    assert "error" in out and "ความดัน" in out["error"]
    assert sections.safe("x", lambda a: a * 2, 4) == 8


@pytest.fixture
def fake_page(monkeypatch):
    seen = {}

    def build(p, src="hosxp", opts=None):
        seen.update(fy=p.fy, src=src, opts=dict(opts or {}))
        return {"title": "หน้าทดสอบ", "subtitle": "ซับไตเติล", "kpis": [
            {"label": "ผู้รับบริการ", "value": "1,234", "sub": "ราย", "tone": "blue", "icon": "users",
             "delta": {"pct": 5.0, "dir": "up"}}],
            "monthly": {"labels": ["ต.ค. 68"], "series": [{"name": "ครั้ง", "values": [5], "color": "#1d6ff2"}]},
            "donut": {"title": "สถานะ", "center": "50%", "total_label": "รวม 2 ราย",
                      "parts": [("ดี", 1, "#16a34a"), ("ไม่ดี", 1, "#ef4444")]},
            "table": {"title": "ตัวชี้วัด", "columns": ["ตัวชี้วัด", "ผล"], "rows": [["ก", "1"]]},
            "recent": {"error": "รายการล่าสุด: ดึงข้อมูลไม่ได้"},
            "notes": [{"tone": "info", "text": "ข้อสังเกตทดสอบ"}], "extra": []}

    monkeypatch.setitem(pages.REGISTRY, "ht", build)
    return seen


def test_page_renders_ok(fake_page):
    r = app.test_client().get("/ht?fy=2569&src=hdc")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "หน้าทดสอบ" in html and "ข้อสังเกตทดสอบ" in html
    assert "รายการล่าสุด: ดึงข้อมูลไม่ได้" in html          # ส่วนที่ล้มแสดงข้อผิดพลาด ไม่ทำให้ทั้งหน้าล้ม
    assert fake_page["fy"] == 2569 and fake_page["src"] == "hdc"


def test_unknown_page_404():
    assert app.test_client().get("/nope").status_code == 404


def test_invalid_src_falls_back_to_hosxp(fake_page):
    app.test_client().get("/ht?src=zzz")
    assert fake_page["src"] == "hosxp"


def test_api_json(fake_page):
    r = app.test_client().get("/api/ht.json")
    assert r.status_code == 200 and r.get_json()["title"] == "หน้าทดสอบ"


def test_print_mode_hides_sidebar(fake_page):
    normal = app.test_client().get("/ht").get_data(as_text=True)
    printed = app.test_client().get("/ht?print=1").get_data(as_text=True)
    assert 'class="sidebar"' in normal
    assert 'class="sidebar"' not in printed


def test_builder_exception_does_not_crash_page(monkeypatch):
    def boom(p, src="hosxp", opts=None):
        raise RuntimeError("db down")

    monkeypatch.setitem(pages.REGISTRY, "dm", boom)
    r = app.test_client().get("/dm")
    assert r.status_code == 200
    assert "ดึงข้อมูลไม่ได้" in r.get_data(as_text=True)


def test_all_nav_keys_routable():
    keys = [n["key"] for n in pages.NAV]
    assert keys == ["overview", "ht", "dm", "ckd", "warfarin", "copd", "cvd"]
    assert app.test_client().get("/").status_code == 200


def test_page_data_is_cached_between_requests(monkeypatch):
    calls = []

    def build(p, src="hosxp", opts=None):
        calls.append(1)
        return {"title": "แคช"}

    monkeypatch.setitem(pages.REGISTRY, "ht", build)
    c = app.test_client()
    c.get("/ht?fy=2569")
    c.get("/ht?fy=2569")
    assert len(calls) == 1                         # ผลเดิมใช้ซ้ำ ไม่ query ฐานซ้ำ
    c.get("/ht?fy=2568")
    assert len(calls) == 2                         # ตัวกรองต่าง = คนละรายการแคช


def test_error_results_are_not_cached(monkeypatch):
    calls = []

    def build(p, src="hosxp", opts=None):
        calls.append(1)
        raise RuntimeError("down")

    monkeypatch.setitem(pages.REGISTRY, "ht", build)
    c = app.test_client()
    c.get("/ht")
    c.get("/ht")
    assert len(calls) == 2                         # ล้มแล้วลองใหม่ได้ทันที
