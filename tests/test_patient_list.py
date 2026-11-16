"""รายชื่อผู้ป่วยจากตัวชี้วัด CKD (ฝั่ง HOSxP) — เปิดเฉพาะเครือข่าย LAN ของ รพ.
จากอินเทอร์เน็ต (ผ่าน Cloudflare/Apache) เห็นเฉพาะจำนวนนับ ไม่มีลิงก์ ไม่มีชื่อ และ /api/*.json ไม่มี HN"""
from datetime import date

import pytest

import periods
from app import app
from queries import ckd

P = periods.make(2569)
LAN = {"REMOTE_ADDR": "192.168.11.5"}
VIA_INTERNET = {"environ_base": {"REMOTE_ADDR": "127.0.0.1"}, "headers": {"X-Forwarded-For": "1.1.1.1"}}
# หมายเหตุ: อย่าใช้ 203.0.113.x / 198.51.100.x ในการทดสอบ — ipaddress ของ Python ถือว่าเป็น private

COHORT = {"HN0000A": {"stage": "G3a", "egfr": 50.0}, "HN0000B": {"stage": "G4", "egfr": 20.0},
          "HN0000C": {"stage": "G3b", "egfr": 40.0}, "HN0000D": {"stage": "G5", "egfr": 10.0}}
INPUTS = dict(cohort=COHORT, prior_ckd=set(), dm={"HN0000A", "HN0000B"}, ht={"HN0000C"},
              dm_visited={"HN0000A", "HN0000B"}, uacr_tested={"HN0000A"},
              visited={"HN0000A", "HN0000B", "HN0000C"}, acei={"HN0000A"},
              hb={"HN0000A": 11.0, "HN0000B": 9.0}, hct={}, a1c={"HN0000A": 6.5}, dialysis=set())


@pytest.fixture
def fake_ckd(monkeypatch, fake_db):
    core = {"series": {}, "cohort": COHORT, "summary": ckd.summarize(COHORT), "label": P.label,
            "dialysis_hns": set(), "dialysis": 0, "admits": 0}
    monkeypatch.setattr(ckd, "_core", lambda p: core)
    monkeypatch.setattr(ckd, "_slowdown_inputs", lambda p, c: dict(INPUTS))
    ckd._LIST_MEMO.clear()
    fake_db.add("from patient p", [
        {"hn": "HN0000B", "pname": "นาย", "fname": "สมชาย", "lname": "ทดสอบ", "birthday": date(1950, 1, 1)},
        {"hn": "HN0000C", "pname": "นาง", "fname": "สมศรี", "lname": "ตัวอย่าง", "birthday": date(1960, 6, 1)}])
    fake_db.add("max(o.vstdate)", [{"hn": "HN0000B", "d": date(2026, 5, 1)}])
    yield fake_db
    ckd._LIST_MEMO.clear()


# --- คำนวณกลุ่ม ---------------------------------------------------------------------------

def test_slowdown_groups_give_numerator_and_denominator_sets():
    num, den = ckd.slowdown_groups(**INPUTS)["acei"]
    assert num == {"HN0000A"} and den == {"HN0000A", "HN0000B", "HN0000C"}      # D ระยะ 5 ไม่อยู่ในตัวหาร


def test_acei_missing_list_has_names_sorted_by_worst_egfr(fake_ckd):
    d = ckd.patient_list(P, "acei", "miss")
    assert d["count"] == 2
    assert [r[1] for r in d["rows"]] == ["HN0000B", "HN0000C"]                  # eGFR 20 ก่อน 40
    assert "นายสมชาย ทดสอบ" in d["rows"][0] and "ยังไม่ได้รับ ACEI/ARB" in d["title"]


def test_anemia_list_shows_hb_value(fake_ckd):
    d = ckd.patient_list(P, "anemia", "miss")
    assert [r[1] for r in d["rows"]] == ["HN0000B"]
    assert any("Hb 9" in str(c) for c in d["rows"][0])


def test_stage_list(fake_ckd):
    assert [r[1] for r in ckd.patient_list(P, "stage", "G4")["rows"]] == ["HN0000B"]


@pytest.mark.parametrize("ind,g", [("zzz", "miss"), ("acei", "bogus"), ("stage", "G9")])
def test_unknown_list_is_rejected(fake_ckd, ind, g):
    with pytest.raises(KeyError):
        ckd.patient_list(P, ind, g)


# --- สิทธิ์เข้าถึง -----------------------------------------------------------------------------

def test_list_page_on_lan_shows_names_and_is_not_cached(fake_ckd):
    r = app.test_client().get("/list/ckd/acei?fy=2569&g=miss", environ_base=LAN)
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "สมชาย" in html and "HN0000C" in html
    assert "no-store" in r.headers["Cache-Control"]


def test_list_page_from_internet_is_refused_without_names(fake_ckd):
    r = app.test_client().get("/list/ckd/acei?fy=2569&g=miss", **VIA_INTERNET)
    html = r.get_data(as_text=True)
    assert r.status_code == 403 and "สมชาย" not in html and "HN0000" not in html
    assert not any("from patient" in c[0] for c in fake_ckd.calls)               # ไม่แตะข้อมูลรายคนเลย


def test_unknown_list_is_404_on_lan(fake_ckd):
    assert app.test_client().get("/list/ckd/zzz", environ_base=LAN).status_code == 404
    assert app.test_client().get("/list/dm/acei", environ_base=LAN).status_code == 404


def test_ckd_page_links_to_lists_only_on_lan(fake_ckd):
    c = app.test_client()
    lan = c.get("/ckd?fy=2569", environ_base=LAN).get_data(as_text=True)
    net = c.get("/ckd?fy=2569", **VIA_INTERNET).get_data(as_text=True)          # หน้าเดียวกันจากแคช
    assert "/list/ckd/acei" in lan and "ยังไม่ได้รับ ACEI/ARB" in lan and "/list/ckd/stage" in lan
    assert "/list/ckd/" not in net


def test_api_json_has_counts_only(fake_ckd):
    body = app.test_client().get("/api/ckd.json?fy=2569", environ_base=LAN).get_data(as_text=True)
    assert "HN0000" not in body
