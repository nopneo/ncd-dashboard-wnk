from datetime import date

import pages
import periods
from queries import ckd

P = periods.make(2569)
D = date


def test_persistent_low_egfr_is_ckd():
    s = {"A": [(D(2025, 12, 1), 55.0), (D(2026, 4, 5), 50.0)]}          # <60 สองครั้งห่าง >90 วัน
    out = ckd.identify_ckd(s, set())
    assert out["A"]["stage"] == "G3a" and out["A"]["persistent"] is True and out["A"]["egfr"] == 50.0


def test_single_low_value_without_icd_is_not_ckd():
    assert ckd.identify_ckd({"B": [(D(2026, 1, 1), 50.0)]}, set()) == {}


def test_single_low_value_with_n18_is_ckd():
    out = ckd.identify_ckd({"C": [(D(2026, 1, 1), 50.0)]}, {"C"})
    assert out["C"]["stage"] == "G3a" and out["C"]["persistent"] is False


def test_normal_egfr_without_icd_excluded_and_with_icd_is_g12():
    s = {"D": [(D(2025, 12, 1), 62.0), (D(2026, 4, 5), 64.0)], "E": [(D(2026, 1, 1), 90.0)]}
    out = ckd.identify_ckd(s, {"E"})
    assert "D" not in out and out["E"]["stage"] == "G1-2"


def test_n18_without_any_egfr_has_unknown_stage():
    out = ckd.identify_ckd({}, {"F"})
    assert out["F"]["stage"] is None and out["F"]["egfr"] is None


def test_stale_history_only_is_excluded_when_period_given():
    s = {"G": [(D(2024, 1, 1), 50.0), (D(2024, 6, 1), 45.0)]}          # ไม่มีผลในช่วงปีงบ
    assert ckd.identify_ckd(s, set(), in_period_from=D(2025, 10, 1)) == {}
    assert "G" in ckd.identify_ckd(s, {"G"}, in_period_from=D(2025, 10, 1))


def test_rapid_decline_flag():
    s = {"H": [(D(2025, 9, 1), 60.0), (D(2026, 3, 1), 52.0), (D(2026, 9, 30), 46.0)]}      # 3 ผล ครอบคลุม >1 ปี
    out = ckd.identify_ckd(s, {"H"})
    assert out["H"]["rapid"] is True
    slow = ckd.identify_ckd({"I": [(D(2025, 10, 1), 55.0), (D(2026, 9, 30), 54.0)]}, {"I"})
    assert slow["I"]["rapid"] is False


def test_rapid_decline_needs_three_results_over_a_year():
    """ผลสั้น/น้อยเกินไปแกว่งง่าย (ผู้ป่วยป่วยเฉียบพลัน) — ไม่ควรนับว่า eGFR ลดเร็ว"""
    two = {"J": [(D(2025, 9, 1), 70.0), (D(2026, 9, 30), 40.0)]}                            # 2 ผล
    short = {"K": [(D(2026, 1, 1), 70.0), (D(2026, 3, 1), 55.0), (D(2026, 5, 1), 40.0)]}   # 3 ผล แต่ครอบคลุมแค่ 4 เดือน
    assert ckd.identify_ckd(two, {"J"})["J"]["rapid"] is False
    assert ckd.identify_ckd(short, {"K"})["K"]["rapid"] is False


def test_summarize_stages():
    cohort = {"1": {"stage": "G3a", "rapid": False}, "2": {"stage": "G3a", "rapid": True}, "3": {"stage": "G3b", "rapid": False},
              "4": {"stage": "G4", "rapid": False}, "5": {"stage": "G5", "rapid": False}, "6": {"stage": "G1-2", "rapid": False},
              "7": {"stage": None, "rapid": False}}
    s = ckd.summarize(cohort)
    assert (s["g3a"], s["g3b"], s["g4"], s["g5"], s["g12"], s["unknown"]) == (2, 1, 1, 1, 1, 1)
    assert s["stage3"] == 3 and s["total"] == 7 and s["stage345"] == 5
    assert s["rapid_decline"] == 1 and s["egfr_lt30"] == 2


def test_summarize_empty():
    s = ckd.summarize({})
    assert s["total"] == 0 and s["stage345"] == 0


def _seed(fake_db):
    fake_db.add("from lab_head", [
        {"hn": "A", "result": "55", "d": D(2025, 12, 1)}, {"hn": "A", "result": "50", "d": D(2026, 4, 5)},
        {"hn": "B", "result": "50", "d": D(2026, 1, 1)}, {"hn": "C", "result": "70", "d": D(2026, 1, 1)}])
    fake_db.add("ovstdiag", [{"hn": "B"}])


def test_build_sections(fake_db):
    _seed(fake_db)
    d = ckd.build(P)
    assert len(d["kpis"]) == 4 and d["kpis"][0]["value"] == "2"          # A, B (C ปกติ)
    assert sum(v for _, v, _ in d["donut"]["parts"]) == 2
    assert "error" not in d["monthly"] and all("error" not in x for x in d["extra"])
    texts = str(d["extra"])
    assert "ไม่มีข้อมูล" in texts                                           # ส่งปรึกษา ไม่มีแหล่งข้อมูล


def test_build_empty(fake_db):
    d = ckd.build(periods.make(2570))
    assert d["kpis"][0]["value"] in ("0", "—") and d["donut"]["center"] in ("0", "—")


def test_registered_and_hdc_delegates(monkeypatch):
    pages.load()
    assert pages.REGISTRY["ckd"] is ckd.build
    from queries import hdc_views
    monkeypatch.setattr(hdc_views, "build_ckd", lambda p: {"title": "HDC CKD"})
    assert ckd.build(P, "hdc")["title"] == "HDC CKD"
