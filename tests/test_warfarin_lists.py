"""รายชื่อผู้ป่วยหน้า Warfarin (เฉพาะ LAN) — นับเป็นราย ตรงกับตัวเลขบนหน้า"""
from datetime import date

import pytest

import config
import periods
from app import app
from queries import clinic_lists, common

P = periods.make(2569)
D = date
LAN = {"REMOTE_ADDR": "192.168.11.5"}
VIA_INTERNET = {"environ_base": {"REMOTE_ADDR": "127.0.0.1"}, "headers": {"X-Forwarded-For": "1.1.1.1"}}
SERIES = {"W1": [(D(2026, 1, 1), 2.5), (D(2026, 5, 1), 2.6), (D(2026, 8, 1), 2.4)],   # TTR 100 · มี INR ใน 90 วัน
          "W2": [(D(2026, 1, 1), 1.2), (D(2026, 2, 1), 5.0)],                        # TTR ต่ำ · INR >4.5
          "W3": [(D(2025, 11, 1), 2.5)],                                               # ผลเดียว ไม่มี TTR
          "ZZ": [(D(2026, 1, 1), 3.5)]}                                                # ไม่ได้รับ warfarin → ไม่นับ


@pytest.fixture
def fake_warf(monkeypatch, fake_db):
    monkeypatch.setattr(config, "INR_LOW", 2.0)
    monkeypatch.setattr(config, "INR_HIGH", 3.0)
    monkeypatch.setattr(config, "TTR_TARGET", 65.0)
    monkeypatch.setattr(common, "drug_hns", lambda codes, clinic, p: {"W1", "W2", "W3", "W4"})
    monkeypatch.setattr(common, "lab_series_by_hn", lambda code, clinic, s, e, allow_zero=False: {k: list(v) for k, v in SERIES.items()})
    monkeypatch.setattr(common, "icd_hns", lambda ids, p, clinic=None: {"W2", "X9"})
    clinic_lists._MEMO.clear()
    yield fake_db
    clinic_lists._MEMO.clear()


def test_warfarin_groups(fake_warf):
    g, value = clinic_lists.warfarin_groups(P)
    assert g["all"] == {"W1", "W2", "W3", "W4"} and g["ttr_below"] == {"W2"} and g["critical_high"] == {"W2"}
    assert g["bleeding"] == {"W2"} and g["no_recent"] == {"W2", "W3", "W4"}
    assert "INR 5" in value("W2") and "TTR" in value("W2") and value("W4") == "ไม่มีผล INR ในช่วง"


def test_warfarin_page_links_lan_only(fake_warf):
    c = app.test_client()
    lan = c.get("/warfarin?fy=2569", environ_base=LAN).get_data(as_text=True)
    for g in ("all", "ttr_below", "critical_high", "bleeding", "no_recent"):
        assert f"/list/warfarin/group?fy=2569&amp;g={g}" in lan
    assert "/list/" not in c.get("/warfarin?fy=2569", **VIA_INTERNET).get_data(as_text=True)
    r = c.get("/list/warfarin/group?fy=2569&g=no_recent", environ_base=LAN)
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "W3" in html and "W4" in html and "W1" not in html
    assert c.get("/list/warfarin/group?fy=2569&g=all", **VIA_INTERNET).status_code == 403
    assert c.get("/list/warfarin/group?g=zzz", environ_base=LAN).status_code == 404
