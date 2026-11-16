from datetime import date, timedelta

import pages
import periods
from queries import warfarin

P = periods.make(2569)
D = date(2026, 1, 1)


def days(n):
    return D + timedelta(days=n)


def test_inr_groups_counted_per_result():
    s = {"1": [(days(0), 2.5), (days(14), 2.8)], "2": [(days(0), 3.5)], "3": [(days(0), 1.5)]}
    r = warfarin.summarize(s, P)
    assert (r["inr_in"], r["inr_low"], r["inr_high"], r["inr_total"]) == (2, 1, 1, 4)
    assert r["patients"] == 3


def test_critical_inr_over_4_5():
    r = warfarin.summarize({"1": [(days(0), 4.6), (days(7), 4.5)], "2": [(days(0), 5.0)]}, P)
    assert r["critical_gt45"] == 2 and r["critical_patients"] == 2


def test_ttr_only_for_patients_with_two_or_more_inr():
    s = {"1": [(days(0), 2.0), (days(10), 3.0)], "2": [(days(0), 2.5)]}
    r = warfarin.summarize(s, P)
    assert r["ttr_mean"] == 100.0 and r["ttr_patients"] == 1
    assert r["ttr_ge_target_pct"] == 100.0


def test_ttr_none_when_no_pair():
    r = warfarin.summarize({"1": [(days(0), 2.5)]}, P)
    assert r["ttr_mean"] is None and r["ttr_ge_target_pct"] is None


def test_median_gap_days():
    s = {"1": [(days(0), 2.5), (days(10), 2.6), (days(30), 2.7)]}
    assert warfarin.summarize(s, P)["median_gap_days"] == 15.0         # ช่วงห่าง 10 และ 20 วัน


def test_empty_series():
    r = warfarin.summarize({}, P, patients=0)
    assert r["patients"] == 0 and r["inr_total"] == 0 and r["median_gap_days"] is None


def test_patients_override_counts_cohort_without_inr():
    assert warfarin.summarize({}, P, patients=10)["patients"] == 10


def test_custom_range_from_config(monkeypatch):
    import config
    monkeypatch.setattr(config, "INR_LOW", 1.5)
    monkeypatch.setattr(config, "INR_HIGH", 2.5)
    r = warfarin.summarize({"1": [(days(0), 1.6)]}, P)
    assert r["inr_in"] == 1


def test_recent_inr_within_90_days():
    s = {"1": [(date(2026, 9, 1), 2.5)], "2": [(date(2026, 3, 1), 2.5)]}
    assert warfarin.recent_inr(s, date(2026, 9, 30)) == 1


def test_alert_rows_counts_only_latest_dates_no_patient_ids():
    s = {"1": [(date(2026, 9, 1), 5.0)], "2": [(date(2026, 9, 1), 4.8), (date(2026, 9, 5), 1.2)]}
    rows = warfarin.alert_rows(s, limit=5)
    assert rows[0][0] == "5 ก.ย. 2569" and rows[0][1] == "INR <1.5" and rows[0][2] == "1"
    assert any(r[1] == "INR >4.5" and r[2] == "2" for r in rows)
    assert "1" not in [r[0] for r in rows]


def _seed(fake_db):
    fake_db.add("select distinct r.hn", [{"hn": "1"}, {"hn": "2"}])
    fake_db.add("from lab_head", [{"hn": "1", "result": "2.5", "d": date(2026, 1, 1)}, {"hn": "1", "result": "3.4", "d": date(2026, 1, 15)},
                                   {"hn": "2", "result": "1.4", "d": date(2026, 2, 1)}, {"hn": "9", "result": "2.5", "d": date(2026, 2, 1)}])


def test_build_restricts_inr_to_warfarin_cohort(fake_db):
    _seed(fake_db)
    d = warfarin.build(P)
    assert d["kpis"][0]["value"] == "2"                                # ผู้ป่วย warfarin 2 (hn 9 ไม่ได้รับยา)
    assert sum(v for _, v, _ in d["donut"]["parts"]) == 3              # ผล INR 3 ครั้งของ hn 1,2
    assert "error" not in d["monthly"] and all("error" not in x for x in d["extra"])
    assert "ไม่มีข้อมูล" in str(d["table"])                             # Identification Error ไม่มีแหล่งข้อมูล


def test_build_empty(fake_db):
    d = warfarin.build(periods.make(2570))
    assert d["kpis"][0]["value"] in ("0", "—") and d["donut"]["center"] == "—"


def test_hdc_source_is_explained(fake_db):
    d = warfarin.build(P, "hdc")
    assert any("HDC" in n["text"] for n in d["notes"]) and "kpis" not in d


def test_registered():
    pages.load()
    assert pages.REGISTRY["warfarin"] is warfarin.build
