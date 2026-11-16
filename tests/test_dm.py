from datetime import date

import pages
import periods
from queries import dm

P = periods.make(2569)


def lab(hn, v):
    return {"hn": hn, "value": v, "date": date(2026, 1, 1)}


def test_summarize_hba1c_denominator_is_registry():
    latest = ([lab(str(i), 6.5) for i in range(10)] + [lab(f"a{i}", 7.4) for i in range(4)]
              + [lab("b1", 8.5), lab("b2", 9.5), lab("b3", 10.0)] + [lab(f"n{i}", None) for i in range(3)])
    s = dm.summarize_hba1c(latest, registry=25)
    assert (s["lt7"], s["7to79"], s["ge8"], s["ge9"]) == (10, 4, 3, 2)
    assert s["lt7_pct"] == 40.0 and s["tested_pct"] == 68.0 and s["no_value"] == 8


def test_summarize_hba1c_empty():
    s = dm.summarize_hba1c([], registry=0)
    assert s["lt7_pct"] is None and s["tested_pct"] is None and s["no_value"] == 0


def test_status_map_marks_controlled_only_below_7():
    m = dm.status_by_hn([lab("1", 6.9), lab("2", 7.0), lab("3", None)])
    assert m == {"1": "controlled", "2": "partial", "3": None}


def _seed(fake_db):
    fake_db.add("count(distinct m.hn)", [{"n": 25}])
    fake_db.add("from lab_head", [{"hn": str(i), "result": "6.5", "d": date(2026, 1, 1)} for i in range(10)])


def test_build_all_sections_ok(fake_db):
    _seed(fake_db)
    d = dm.build(P)
    assert len(d["kpis"]) == 4 and sum(v for _, v, _ in d["donut"]["parts"]) == 25
    assert len(d["monthly"]["series"]) == 2                 # visit + ผู้ป่วยรายใหม่
    assert "error" not in d["recent"] and all("error" not in x for x in d["extra"])
    titles = [x["title"] for x in d["extra"]]
    assert any("ภาวะแทรกซ้อน" in t for t in titles) and any("เฝ้าระวัง" in t for t in titles)


def test_screening_table_marks_missing_sources(fake_db):
    _seed(fake_db)
    d = dm.build(P)
    scr = next(x for x in d["extra"] if "ภาวะแทรกซ้อน" in x["title"])
    flat = {r[0]: r[1] for r in scr["rows"]}
    assert flat["ตรวจจอประสาทตา"] == "ไม่มีข้อมูล" and flat["ตรวจเท้า"] == "ไม่มีข้อมูล"
    assert flat["HbA1c"] != "ไม่มีข้อมูล"


def test_icd_events_labelled_from_diagnosis_codes(fake_db):
    _seed(fake_db)
    d = dm.build(P)
    watch = next(x for x in d["extra"] if "เฝ้าระวัง" in x["title"])
    assert "รหัสโรค" in watch["title"]


def test_build_empty_period(fake_db):
    d = dm.build(periods.make(2570))
    assert d["donut"]["center"] == "—"


def test_hdc_source_delegates(monkeypatch):
    from queries import hdc_views
    monkeypatch.setattr(hdc_views, "build_dm", lambda p: {"title": "HDC DM"})
    assert dm.build(P, "hdc")["title"] == "HDC DM"


def test_registered():
    pages.load()
    assert pages.REGISTRY["dm"] is dm.build
