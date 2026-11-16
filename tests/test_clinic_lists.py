"""รายชื่อผู้ป่วยหน้า DM / HT (แบบเดียวกับ CKD) — เปิดเฉพาะ LAN ของ รพ.
กลุ่มต้องตรงกับตัวเลขบนหน้า: นับจากทะเบียน/ค่าล่าสุด/การมารับบริการชุดเดียวกัน"""
from datetime import date

import pytest

import periods
from app import app
from queries import clinic_lists, common, ht

P = periods.make(2569)
D = date
LAN = {"REMOTE_ADDR": "192.168.11.5"}
VIA_INTERNET = {"environ_base": {"REMOTE_ADDR": "127.0.0.1"}, "headers": {"X-Forwarded-For": "1.1.1.1"}}
REG = ["HN0A", "HN0B", "HN0C", "HN0D", "HN0E"]


@pytest.fixture
def fake_clinic(monkeypatch, fake_db):
    monkeypatch.setattr(common, "registry_hns", lambda clinic, p: list(REG))
    monkeypatch.setattr(common, "registry_count", lambda clinic, p: len(REG))
    monkeypatch.setattr(common, "latest_lab_by_hn", lambda code, clinic, p, allow_zero=False: [
        {"hn": "HN0A", "value": 6.5, "date": D(2026, 3, 1)}, {"hn": "HN0B", "value": 7.5, "date": D(2026, 3, 2)},
        {"hn": "HN0C", "value": 9.2, "date": D(2026, 3, 3)}, {"hn": "HN0D", "value": None, "date": D(2026, 3, 4)}])
    monkeypatch.setattr(common, "visited_hns", lambda clinic, p: {"HN0A", "HN0B"})
    monkeypatch.setattr(common, "visited_patients", lambda clinic, p: 2)
    monkeypatch.setattr(common, "followup_hns", lambda clinic, p, on: {"lost_3m": {"HN0C"}, "overdue": {"HN0D"}})
    monkeypatch.setattr(ht, "bp_series_by_hn", lambda clinic, p: {
        "HN0A": [(D(2026, 2, 1), 130, 80)],
        "HN0B": [(D(2026, 2, 1), 150, 95), (D(2026, 4, 1), 165, 100)],
        "HN0C": [(D(2026, 2, 1), 185, 112)]})
    clinic_lists._MEMO.clear()
    fake_db.add("from patient p", [{"hn": "HN0C", "pname": "นาย", "fname": "ทดสอบ", "lname": "ระบบ", "birthday": D(1960, 1, 1)}])
    yield fake_db
    clinic_lists._MEMO.clear()


def test_dm_groups_match_page_definitions(fake_clinic):
    g, _vals = clinic_lists.dm_groups(P)
    assert g["lt7"] == {"HN0A"} and g["7to79"] == {"HN0B"} and g["ge8"] == {"HN0C"} and g["ge9"] == {"HN0C"}
    assert g["above7"] == {"HN0B", "HN0C"} and g["no_a1c"] == {"HN0D", "HN0E"}
    assert g["not_visited"] == {"HN0C", "HN0D", "HN0E"} and g["lost_3m"] == {"HN0C"} and g["overdue"] == {"HN0D"}


def test_ht_groups_match_page_definitions(fake_clinic):
    g, _vals = clinic_lists.ht_groups(P)
    assert g["controlled"] == {"HN0A"} and g["partial"] == set() and g["uncontrolled"] == {"HN0B", "HN0C"}
    assert g["not_controlled"] == {"HN0B", "HN0C"} and g["no_bp"] == {"HN0D", "HN0E"}
    assert g["streak"] == {"HN0B"} and g["crisis"] == {"HN0C"}


def test_dm_list_rows_sorted_worst_first_with_value(fake_clinic):
    d = clinic_lists.patient_list("dm", P, "group", "above7")
    assert [r[1] for r in d["rows"]] == ["HN0C", "HN0B"] and d["count"] == 2
    assert "9.2%" in d["rows"][0][4] and "ทดสอบ" in d["rows"][0][2]


def test_ht_list_shows_latest_bp(fake_clinic):
    d = clinic_lists.patient_list("ht", P, "group", "crisis")
    assert [r[1] for r in d["rows"]] == ["HN0C"] and "185/112" in d["rows"][0][4]


@pytest.mark.parametrize("page,ind,g", [("dm", "group", "zzz"), ("ht", "group", "lt7"), ("ht", "other", "crisis")])
def test_unknown_group_is_rejected(fake_clinic, page, ind, g):
    with pytest.raises(KeyError):
        clinic_lists.patient_list(page, P, ind, g)


def test_lists_are_lan_only(fake_clinic):
    c = app.test_client()
    r = c.get("/list/ht/group?fy=2569&g=crisis", environ_base=LAN)
    assert r.status_code == 200 and "HN0C" in r.get_data(as_text=True) and "no-store" in r.headers["Cache-Control"]
    r = c.get("/list/dm/group?fy=2569&g=ge9", **VIA_INTERNET)
    assert r.status_code == 403 and "HN0C" not in r.get_data(as_text=True)
    assert c.get("/list/ht/group?g=zzz", environ_base=LAN).status_code == 404


@pytest.mark.parametrize("page", ["dm", "ht"])
def test_page_links_only_on_lan(fake_clinic, page):
    c = app.test_client()
    lan = c.get(f"/{page}?fy=2569", environ_base=LAN).get_data(as_text=True)
    net = c.get(f"/{page}?fy=2569", **VIA_INTERNET).get_data(as_text=True)
    assert f"/list/{page}/group?fy=2569&amp;g=lost_3m" in lan          # ช่องเร่งด่วน (tiles)
    assert f"/list/{page}/group?fy=2569&amp;g=not_visited" in lan      # แถวในตารางตัวชี้วัด
    assert ("g=no_a1c" if page == "dm" else "g=no_bp") in lan          # คำอธิบายโดนัท
    assert "/list/" not in net
    body = c.get(f"/api/{page}.json?fy=2569").get_data(as_text=True)
    assert "HN0" not in body
