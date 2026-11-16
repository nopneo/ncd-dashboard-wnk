"""DM remission (ตัวชี้วัด HDC 10.2 · NCDs remission clinic รหัสกิจกรรม 1I20)
ฝั่ง HOSxP: ระยะสงบ = HbA1c 2 ครั้งล่าสุด <6.5% ห่างกัน 90–180 วัน และไม่ได้ยาลดน้ำตาลในช่วงนั้น
ฝั่ง HDC: ตาราง s_dm_remission_coverage (b=B2, b1=B1, b3/b4, a=A1, a2/a3)"""
from datetime import date

import pytest

import config
import hdc
import periods
from app import app
from queries import hdc_views, remission

P = periods.make(2569)          # 1 ต.ค. 2568 – 30 ก.ย. 2569
D = date
LAN = {"REMOTE_ADDR": "192.168.11.5"}
VIA_INTERNET = {"environ_base": {"REMOTE_ADDR": "127.0.0.1"}, "headers": {"X-Forwarded-For": "1.1.1.1"}}


def st(points, drugs=(), start=P.start):
    return remission.remission_status(points, list(drugs), start)


# --- สถานะรายคน --------------------------------------------------------------------

def test_two_results_below_cutoff_90_to_180_days_apart_without_drugs_is_remission():
    assert st([(D(2026, 1, 10), 6.8), (D(2026, 2, 1), 6.2), (D(2026, 5, 15), 6.0)]) == "remission"


def test_drug_between_the_two_results_is_not_remission():
    assert st([(D(2026, 2, 1), 6.2), (D(2026, 5, 15), 6.0)], [D(2026, 3, 1)]) == "on_drug"


def test_drug_before_first_low_result_does_not_count():
    assert st([(D(2026, 2, 1), 6.2), (D(2026, 5, 15), 6.0)], [D(2026, 1, 20)]) == "remission"


@pytest.mark.parametrize("second,expected", [(D(2026, 3, 1), "waiting"),        # 28 วัน — เร็วเกิน
                                             (D(2026, 5, 2), "remission"),      # 90 วันพอดี
                                             (D(2026, 7, 31), "remission"),     # 180 วันพอดี
                                             (D(2026, 8, 1), "waiting")])       # 181 วัน — ห่างเกิน
def test_gap_must_be_90_to_180_days(second, expected):
    assert st([(D(2026, 2, 1), 6.2), (second, 6.0)]) == expected


def test_only_latest_below_cutoff_is_waiting_and_drug_after_it_is_on_drug():
    pts = [(D(2026, 1, 1), 7.2), (D(2026, 4, 1), 6.1)]
    assert st(pts) == "waiting"
    assert st(pts, [D(2026, 4, 1)]) == "on_drug"


def test_latest_at_or_above_cutoff_is_not_yet(monkeypatch):
    monkeypatch.setattr(config, "REMISSION_HBA1C", 6.5)
    assert st([(D(2026, 2, 1), 6.0), (D(2026, 5, 15), 6.5)]) == "not_yet"
    assert st([]) == "no_a1c"


def test_remission_confirmed_before_period_is_not_counted_in_this_period():
    assert st([(D(2025, 5, 1), 6.2), (D(2025, 8, 15), 6.0)]) == "waiting"


# --- หน้า DM ฝั่ง HOSxP + รายชื่อ -------------------------------------------------------

PART = {"HN00001", "HN00002", "HN00003", "HN00004"}
SERIES = {"HN00001": [(D(2026, 2, 1), 6.2), (D(2026, 5, 15), 6.0)],
          "HN00002": [(D(2026, 2, 1), 6.2), (D(2026, 5, 15), 6.0)],
          "HN00003": [(D(2026, 3, 1), 8.1)],
          "HN99999": [(D(2026, 3, 1), 6.0)]}                       # ไม่ได้เข้าร่วม clinic → ไม่นับ
DRUGS = {"HN00002": [D(2026, 3, 1)]}


@pytest.fixture
def fake_rem(monkeypatch, fake_db):
    monkeypatch.setattr(remission, "_inputs", lambda p: (set(PART), SERIES, DRUGS))
    remission._MEMO.clear()
    fake_db.add("from patient p", [{"hn": "HN00002", "pname": "นาง", "fname": "ทดลอง", "lname": "ใจดี", "birthday": D(1970, 1, 1)}])
    yield fake_db
    remission._MEMO.clear()


def test_summary_counts_each_status_among_participants(fake_rem):
    s = remission.summarize(*remission._inputs(P), P)
    assert s["participants"] == 4
    assert s["counts"] == {"remission": 1, "waiting": 0, "on_drug": 1, "not_yet": 1, "no_a1c": 1}


def test_section_table_has_rate_and_lan_links(fake_rem, monkeypatch):
    monkeypatch.setattr(config, "TARGET_DM_REMISSION", 10.0)
    t = remission.section(P)
    first = t["rows"][0]
    assert first[2]["text"] == "1 / 4" and first[3]["text"] == "25.0%" and first[4]["chip"] == "ok"
    links = [r[0].get("list") for r in t["rows"] if r[0].get("list")]
    assert {x["g"] for x in links} >= {"remission", "on_drug", "not_yet", "no_a1c", "all"}
    assert all(x["page"] == "dm" and x["ind"] == "remission" for x in links)


def test_list_on_lan_shows_on_drug_patient(fake_rem):
    r = app.test_client().get("/list/dm/remission?fy=2569&g=on_drug", environ_base=LAN)
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "ทดลอง" in html and "HN00002" in html and "HN00001" not in html
    assert "no-store" in r.headers["Cache-Control"]


def test_list_from_internet_is_refused(fake_rem):
    r = app.test_client().get("/list/dm/remission?fy=2569&g=all", **VIA_INTERNET)
    assert r.status_code == 403 and "HN0000" not in r.get_data(as_text=True)


def test_unknown_remission_group_is_404(fake_rem):
    assert app.test_client().get("/list/dm/remission?g=zzz", environ_base=LAN).status_code == 404
    assert app.test_client().get("/list/dm/other?g=all", environ_base=LAN).status_code == 404


# --- ฝั่ง HDC -------------------------------------------------------------------------------

REM_TOTALS = {"b": 1980.0, "b1": 189.0, "b3": 189.0, "b4": 0.0, "a": 9.0, "a2": 9.0, "a3": 0.0}


def fake_get(table, fy, hospcode=None, refresh=False):
    if table == "s_dm_remission_coverage":
        return hdc.HdcResult(totals=dict(REM_TOTALS), fetched_at="2026-11-14T10:00:00",
                             by_unit={"10894": {"b": 1955.0, "b1": 189.0, "a": 9.0}, "02840": {"b": 4.0, "b1": 0.0, "a": 0.0}})
    return hdc.HdcResult(totals={"target": 100.0, "result": 50.0}, fetched_at="2026-11-14T10:00:00")


def test_remission_table_is_synced_and_pvcode_is_not_summed():
    assert "s_dm_remission_coverage" in hdc.TABLES
    totals, _ = hdc._aggregate([{"hospcode": "10894", "areacode": "1", "__pvcode": "30", "b": "4"},
                                {"hospcode": "10894", "areacode": "2", "__pvcode": "30", "b": "2"}])
    assert totals == {"b": 6.0}


def test_hdc_dm_page_shows_remission_indicator(monkeypatch, fake_db):
    monkeypatch.setattr(hdc, "get", fake_get)
    monkeypatch.setattr(config, "TARGET_DM_REMISSION", 10.0)
    d = hdc_views.build_dm(P)
    assert any(k["label"] == "DM remission (HDC)" and k["value"] == "9" for k in d["kpis"])
    t = next(x for x in d["extra"] if x.get("title", "").startswith("DM remission"))
    a1b1 = t["rows"][0]
    assert a1b1[2]["text"] == "9 / 189" and a1b1[3]["text"] == "4.8%" and a1b1[4]["chip"] == "bad"
    units = next(x for x in d["extra"] if x.get("title", "").startswith("DM remission รายหน่วยบริการ"))
    assert units["rows"][0][1:] == ["1,955", "189", "9", "4.8%"]
