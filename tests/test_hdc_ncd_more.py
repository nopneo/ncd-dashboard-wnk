"""ตัวชี้วัด NCD อื่นของ HDC: คัดกรองความเสี่ยง HT/DM, ตรวจเท้า DM, หืดรายใหม่, IHD รายใหม่, STEMI/อัตราตาย, CVD risk"""
import hdc
import periods
from queries import hdc_views

P = periods.make(2569)
T = {
    "s_ht_screen_risk": {"target": 14844, "result": 12727, "normal": 11377, "risk": 845, "high_risk": 448, "ill": 632},
    "s_dm_screen_risk": {"target": 17643, "result": 14771, "normal": 14195, "risk": 446, "high_risk": 43, "ill": 217},
    "s_dm_foot": {"target": 2660, "result": 1183, "normal1": 848, "abnormal1": 335},
    "s_dm_retina_kpi": {"target": 2000, "result": 20},
    "s_asthma_incidence": {"target": 43794, "result": 5, "result11": 2, "result01": 1, "result02": 1, "result07": 1},
    "s_copd_incidence": {"result": 30, "result10": 30},
    "s_ihd_incidence": {"target": 43794, "result": 9},
    "s_stemi_death": {"targetq1": 4, "targetq2": 4, "targetq3": 2, "targetq4": 3, "resultq1": 1},
    "s_kpi_cvd_risk": {"target": 1794, "result": 754},
}


def fake_get(table, fy, hospcode=None, refresh=False):
    tot = {k: float(v) for k, v in T.get(table, {"target": 10, "result": 5}).items()}
    return hdc.HdcResult(totals=tot, by_unit={"10894": dict(tot)}, fetched_at="2026-11-14T10:00:00")


def _table(d, prefix):
    return next(x for x in d["extra"] if x.get("title", "").startswith(prefix))


def test_new_tables_are_synced():
    for t in ("s_kpi_cvd_risk", "s_dm_foot", "s_stemi_death", "s_asthma_incidence", "s_ihd_incidence",
              "s_ht_screen_risk", "s_dm_screen_risk"):
        assert t in hdc.TABLES


def test_ht_screening_risk_table(monkeypatch, fake_db):
    monkeypatch.setattr(hdc, "get", fake_get)
    t = _table(hdc_views.build_ht(P), "ผลการคัดกรองความดันโลหิต")
    assert [r[1] for r in t["rows"]] == ["11,377", "845", "448", "632"]
    assert t["rows"][0][2] == "89.4%"                          # ของผู้ได้รับการคัดกรอง 12,727


def test_dm_complication_and_screening_tables(monkeypatch, fake_db):
    monkeypatch.setattr(hdc, "get", fake_get)
    d = hdc_views.build_dm(P)
    comp = _table(d, "การตรวจภาวะแทรกซ้อน DM")
    foot = next(r for r in comp["rows"] if "ตรวจเท้า" in r[0]["text"] and "ผิดปกติ" not in r[0]["text"])
    assert foot[2]["text"] == "1,183 / 2,660" and foot[3]["text"] == "44.5%"
    abn = next(r for r in comp["rows"] if "ผิดปกติ" in r[0]["text"])
    assert abn[2]["text"] == "335 / 1,183"
    assert [r[1] for r in _table(d, "ผลการคัดกรองเบาหวาน")["rows"]] == ["14,195", "446", "43", "217"]


def test_copd_page_adds_asthma_incidence(monkeypatch, fake_db):
    monkeypatch.setattr(hdc, "get", fake_get)
    d = hdc_views.build_copd(P)
    assert any(k["label"] == "หืดรายใหม่ปีงบ (HDC)" and k["value"] == "5" for k in d["kpis"])
    assert [s["name"] for s in d["monthly"]["series"]] == ["COPD รายใหม่", "หืดรายใหม่"]
    assert sum(d["monthly"]["series"][1]["values"]) == 5


def test_cvd_page_adds_ihd_stemi_and_cvd_risk(monkeypatch, fake_db):
    monkeypatch.setattr(hdc, "get", fake_get)
    d = hdc_views.build_cvd(P)
    k = {x["label"]: x for x in d["kpis"]}
    assert k["IHD รายใหม่ปีงบ (HDC)"]["value"] == "9"
    assert k["ผู้ป่วย STEMI (HDC)"]["value"] == "13" and "เสียชีวิต 1 ราย" in k["ผู้ป่วย STEMI (HDC)"]["sub"]
    t = _table(d, "ตัวชี้วัด CVD (HDC)")
    risk = next(r for r in t["rows"] if "CVD Risk" in r[0]["text"])
    assert risk[2]["text"] == "754 / 1,794"
    death = next(r for r in t["rows"] if "STEMI" in r[0]["text"])
    assert death[2]["text"] == "1 / 13" and death[3]["text"] == "7.7%"
