"""ทุกหน้า × ทั้งสองแหล่งข้อมูล × หลายปีงบ ต้องตอบ 200 และไม่รั่วข้อมูลรายคน แม้ฐาน/HDC ล้ม"""
from datetime import date

import pytest

import hdc
import pages
from app import app

SECRET = "HN-SECRET-0001"


@pytest.fixture
def seeded(fake_db, monkeypatch):
    # แถวสากลที่มีคอลัมน์ HN จริง (ถ้า query ใดไม่ตรงรูปแบบ จะล้มในส่วนนั้นและแสดงกล่องผิดพลาด — ไม่ทำให้หน้าล้ม)
    fake_db.add("select", [{"hn": SECRET, "n": 7, "d": date(2026, 1, 1), "result": "2.5", "sbp": 150.0, "dbp": 95.0,
                            "ym": "2026-01", "name": "ชื่อทดสอบ", "visits": 3, "sex": "1", "birthday": date(1960, 1, 1),
                            "icd10": "I639", "icode": "1000102"}])
    monkeypatch.setattr(hdc, "_post", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("hdc down")))


@pytest.mark.parametrize("key", pages.KEYS)
@pytest.mark.parametrize("src", ["hosxp", "hdc"])
@pytest.mark.parametrize("fy", ["2569", "2570"])
def test_every_page_renders_and_does_not_leak_hn(seeded, key, src, fy):
    c = app.test_client()
    url = ("/" if key == "overview" else f"/{key}") + f"?fy={fy}&src={src}"
    r = c.get(url)
    assert r.status_code == 200, url
    assert SECRET not in r.get_data(as_text=True)
    j = c.get(f"/api/{key}.json?fy={fy}&src={src}")
    assert j.status_code == 200 and SECRET not in j.get_data(as_text=True)


def test_print_mode_and_scopes_render(seeded):
    c = app.test_client()
    for scope in ("year", "q1", "q4", "m11", "m2"):
        assert c.get(f"/ht?fy=2569&scope={scope}&print=1").status_code == 200


def test_prefixed_links_are_correct(seeded):
    html = app.test_client().get("/ht", headers={"X-Forwarded-Prefix": "/ncd"}).get_data(as_text=True)
    assert 'href="/ncd/ht' in html and "/ncd/static/css/app.css" in html and 'href="/ht' not in html
