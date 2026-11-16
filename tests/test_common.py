from datetime import date

import pytest

import periods
import ui
from queries import common

P = periods.make(2569)
TODAY = date(2026, 11, 11)


def test_age_group_boundaries():
    assert common.age_group(39) == "<40"
    assert common.age_group(40) == "40-59"
    assert common.age_group(60) == "60-79"
    assert common.age_group(80) == "80+"
    assert common.age_group(None) == "ไม่ระบุ"


def test_control_by_group_by_sex_keeps_unknown_rows():
    rows = [{"hn": "1", "status": "controlled"}, {"hn": "2", "status": "uncontrolled"},
            {"hn": "3", "status": None}, {"hn": "4", "status": "controlled"}]
    demo = {"1": ("1", 50), "2": ("2", 70), "3": ("2", 45)}        # hn 4 ไม่มีข้อมูลประชากร
    out = {r["group"]: r for r in common.control_by_group(rows, demo, "sex")}
    assert out["ชาย"] == {"group": "ชาย", "total": 1, "controlled": 1, "pct": 100.0}
    assert out["หญิง"]["total"] == 2 and out["หญิง"]["controlled"] == 0
    assert out["ไม่ระบุ"]["total"] == 1 and out["ไม่ระบุ"]["controlled"] == 1


def test_control_by_group_by_age():
    rows = [{"hn": "1", "status": "controlled"}, {"hn": "2", "status": "partial"}]
    demo = {"1": ("1", 35), "2": ("2", 65)}
    out = {r["group"]: r["total"] for r in common.control_by_group(rows, demo, "age")}
    assert out == {"<40": 1, "60-79": 1}


def test_thai_date():
    assert ui.thai_date(date(2026, 9, 30)) == "30 ก.ย. 2569"


def test_registry_count_binds_clinic_and_period(fake_db):
    fake_db.add("from clinicmember", [{"n": 4000}])
    assert common.registry_count("002", P) == 4000
    sql, args, bound = fake_db.calls[-1]
    assert args["clinic"] == "002" and args["start"] == P.start and args["end"] == P.end
    assert "discharge" in bound


def test_registry_zero_when_no_rows(fake_db):
    assert common.registry_count("002", P) == 0


def test_monthly_visits_aligned_to_months(fake_db):
    fake_db.add("from ovst", [{"ym": "2025-10", "n": 5}, {"ym": "2026-01", "n": 7}])
    out = common.monthly_visits("002", P)
    assert len(out) == 12 and out[0] == 5 and out[3] == 7 and out[1] == 0


def test_latest_lab_takes_latest_parseable_value(fake_db):
    fake_db.add("from lab_head", [
        {"hn": "1", "result": "6.5", "d": date(2025, 11, 1)},
        {"hn": "1", "result": "7.2", "d": date(2026, 3, 1)},
        {"hn": "1", "result": "", "d": date(2026, 6, 1)},          # ล่าสุดแต่ว่าง → ข้าม ใช้ 7.2
        {"hn": "2", "result": "pending", "d": date(2026, 2, 1)},    # อ่านไม่ได้ → ไม่มีค่า
        {"hn": "3", "result": "<4", "d": date(2026, 2, 1)},
    ])
    out = {r["hn"]: r for r in common.latest_lab_by_hn(271, "001", P)}
    assert out["1"]["value"] == 7.2 and out["1"]["date"] == date(2026, 3, 1)
    assert out["2"]["value"] is None
    assert out["3"]["value"] == 4.0


def test_lab_series_by_hn_skips_unparseable(fake_db):
    fake_db.add("from lab_head", [
        {"hn": "1", "result": "2.5", "d": date(2026, 1, 1)},
        {"hn": "1", "result": "x", "d": date(2026, 1, 8)},
        {"hn": "1", "result": "3.1", "d": date(2026, 1, 15)},
    ])
    s = common.lab_series_by_hn(2020, None, date(2026, 1, 1), date(2026, 12, 31))
    assert s == {"1": [(date(2026, 1, 1), 2.5), (date(2026, 1, 15), 3.1)]}


def test_icd_hns_uses_prefix_parameters_not_literals(fake_db):
    fake_db.add("ovstdiag", [{"hn": "1"}, {"hn": "2"}])
    fake_db.add("iptdiag", [{"hn": "2"}, {"hn": "3"}])
    assert common.icd_hns(["I63", "I64"], P) == {"1", "2", "3"}
    for _sql, args, bound in fake_db.calls:
        assert "I63%" in args.values() and "I63" not in bound.replace("I63%", "")


def test_icd_hns_takes_ipd_hn_from_ipt_and_drops_empty(fake_db):
    """iptdiag.hn ว่างราว 57% ของแถว (ข้อมูลจริงปีงบ 2569) — ต้องเอา HN จาก ipt และไม่นับ HN ว่าง"""
    fake_db.add("ovstdiag", [{"hn": "1"}, {"hn": None}, {"hn": ""}])
    fake_db.add("iptdiag", [{"hn": "3"}, {"hn": None}])
    assert common.icd_hns(["J44"], P) == {"1", "3"}
    ipd_sql = next(sql for sql, _a, _b in fake_db.calls if "iptdiag" in sql)
    assert "select distinct i.hn from iptdiag" in ipd_sql and "d.hn" not in ipd_sql
    common.icd_hns(["J44"], P, clinic="024")
    ipd_member = [sql for sql, _a, _b in fake_db.calls if "iptdiag" in sql][-1]
    assert "i.hn in (" in ipd_member and "d.hn" not in ipd_member


def test_icd_hns_empty_prefix_list_runs_no_query(fake_db):
    assert common.icd_hns([], P) == set()
    assert fake_db.calls == []


def test_drug_hns_empty_list_is_empty_set(fake_db):
    assert common.drug_hns([], None, P) == set()
    assert fake_db.calls == []


def test_followup_gaps_zero_when_no_rows(fake_db):
    assert common.followup_gaps("002", P, TODAY) == {"lost_3m": 0, "overdue": 0}


def test_followup_gaps_values(fake_db):
    fake_db.add("not exists (select 1 from ovst o where o.hn = m.hn", [{"hn": "1"}, {"hn": "2"}])
    fake_db.add("not exists (select 1 from ovst o where o.hn = a.hn", [{"hn": "3"}])
    assert common.followup_gaps("002", P, TODAY) == {"lost_3m": 2, "overdue": 1}
    h = common.followup_hns("002", P, TODAY)
    assert h["lost_3m"] == {"1", "2"} and h["overdue"] == {"3"}


def test_followup_gaps_uses_visits_not_stale_clinicmember_columns(fake_db):
    """clinicmember.lastvisit/next_app_date ไม่ถูกอัปเดตใน HOSxP นี้ (lastvisit ล่าสุด 2026-07-07) — ต้องอิง ovst/oapp"""
    common.followup_gaps("002", P, TODAY)
    bound = " ".join(b for _s, _a, b in fake_db.calls)
    assert "lastvisit" not in bound and "next_app_date" not in bound
    assert "from ovst" in bound and "from oapp" in bound


def test_followup_gaps_for_past_period_are_bounded_at_period_end_and_use_period_membership(fake_db):
    """เลือกช่วงในอดีต: ต้องนับ visit เฉพาะถึงวันสิ้นช่วง (ไม่ให้ visit หลังสิ้นช่วงลบการขาดนัด) และใช้สมาชิกของช่วงนั้น"""
    end = date(2026, 9, 30)
    common.followup_gaps("002", P, end)
    for _sql, args, bound in fake_db.calls:
        assert args["today"] == end and args["start"] == P.start and args["end"] == P.end
        import re
        assert re.search(r"o\.vstdate (between '[0-9-]+' and '2026-09-30'|<= '2026-09-30')", bound), bound   # visit นับถึงสิ้นช่วงเท่านั้น
        assert "m.regdate" in bound                      # MEMBER_COND ของช่วงนั้น ไม่ใช่ "ยัง active ปัจจุบัน"


def test_demographics_computes_age(fake_db):
    fake_db.add("from patient", [{"hn": "1", "sex": "1", "birthday": date(1966, 11, 10)},
                                 {"hn": "2", "sex": "2", "birthday": None}])
    out = common.demographics(["1", "2"], on=TODAY)
    assert out["1"] == ("1", 60) and out["2"] == ("2", None)


def test_hospital_names_falls_back_to_code(fake_db):
    fake_db.add("from hospcode", [{"hospcode": "07001", "name": "รพ.สต.ทดสอบ"}])
    assert common.hospital_names(["07001", "99999"]) == {"07001": "รพ.สต.ทดสอบ", "99999": "99999"}


def test_hospital_names_abbreviates_sub_district_health_promoting_hospital(fake_db):
    fake_db.add("from hospcode", [
        {"hospcode": "07001", "name": "โรงพยาบาลส่งเสริมสุขภาพตำบลบุเจ้าคุณ"},
        {"hospcode": "07002", "name": "โรงพยาบาลส่งเสริมสุขภาพตำบล ยุบอีปูน"},
        {"hospcode": "10001", "name": "โรงพยาบาลวังน้ำเขียว"}])
    out = common.hospital_names(["07001", "07002", "10001"])
    assert out == {"07001": "รพ.สต.บุเจ้าคุณ", "07002": "รพ.สต.ยุบอีปูน", "10001": "โรงพยาบาลวังน้ำเขียว"}


def test_short_unit_name_leaves_other_names_untouched():
    assert common.short_unit_name("รพ.สต.ทดสอบ") == "รพ.สต.ทดสอบ"
    assert common.short_unit_name("โรงพยาบาลส่งเสริมสุขภาพตำบล") == "รพ.สต."


def test_visited_patients_and_registry_hns(fake_db):
    fake_db.add("count(distinct", [{"n": 9}])
    assert common.visited_patients("002", P) == 9
    fake_db.add("select m.hn", [{"hn": "1"}, {"hn": "2"}])
    assert common.registry_hns("002", P) == ["1", "2"]


@pytest.mark.parametrize("fn", ["registry_count", "visit_count", "visited_patients"])
def test_empty_period_does_not_raise(fn, fake_db):
    assert getattr(common, fn)("002", P) == 0


def test_new_members_by_month_aligned(fake_db):
    fake_db.add("m.regdate", [{"ym": "2025-11", "n": 3}, {"ym": "2026-09", "n": 2}])
    out = common.new_members_by_month("001", P)
    assert len(out) == 12 and out[1] == 3 and out[11] == 2 and out[0] == 0


def test_lab_item_list_uses_in_clause(fake_db):
    fake_db.add("from lab_head", [{"hn": "1", "result": "100", "d": date(2026, 1, 1)}])
    out = common.latest_lab_by_hn([270, 1956], "001", P)
    assert out[0]["value"] == 100.0
    sql, args, bound = fake_db.calls[-1]
    assert args["l0"] == 270 and args["l1"] == 1956 and " in (" in bound


def test_lab_item_single_int_still_supported(fake_db):
    common.latest_lab_by_hn(271, None, P)
    assert fake_db.calls[-1][1]["l0"] == 271


def test_group_table_builds_rows(fake_db):
    fake_db.add("select m.hn", [{"hn": "1"}, {"hn": "2"}, {"hn": "3"}])
    fake_db.add("from patient", [{"hn": "1", "sex": "1", "birthday": date(1960, 1, 1)},
                                 {"hn": "2", "sex": "2", "birthday": date(1950, 1, 1)}])
    t = common.group_table("001", P, {"1": "controlled", "2": "uncontrolled"}, "sex", "HbA1c <7")
    assert t["type"] == "table" and "เพศ" in t["title"] and "HbA1c <7" in t["title"]
    rows = {r[0]: r for r in t["rows"]}
    assert rows["ชาย"][1] == "1" and rows["ชาย"][2] == "1" and rows["ชาย"][3] == "100.0%"
    assert rows["ไม่ระบุ"][1] == "1"                       # hn 3 ไม่มีข้อมูลประชากร


def test_icd_admissions_empty_runs_nothing(fake_db):
    assert common.icd_admissions([], P) == 0 and fake_db.calls == []


def test_icd_admissions_counts_an(fake_db):
    fake_db.add("count(distinct d.an)", [{"n": 7}])
    assert common.icd_admissions(["N18"], P) == 7
    assert fake_db.calls[-1][1]["i0"] == "N18%"


def test_drug_monthly_visits_aligned(fake_db):
    fake_db.add("date_format(r.vstdate", [{"ym": "2025-10", "n": 4}, {"ym": "2026-02", "n": 6}])
    out = common.drug_monthly_visits(["1000102"], P)
    assert len(out) == 12 and out[0] == 4 and out[4] == 6
    assert common.drug_monthly_visits([], P) == [0] * 12


def test_visited_hns_returns_set(fake_db):
    fake_db.add("select distinct o.hn", [{"hn": "1"}, {"hn": "2"}])
    assert common.visited_hns("024", P) == {"1", "2"}
    assert fake_db.calls[-1][1]["clinic"] == "024"


def test_icd_deaths_filters_discharge_status(fake_db):
    fake_db.add("count(distinct d.an)", [{"n": 4}])
    assert common.icd_deaths(["I63"], ["08", "09"], P) == 4
    args = fake_db.calls[-1][1]
    assert args["i0"] == "I63%" and args["s0"] == "08" and args["s1"] == "09"
    assert common.icd_deaths([], ["08"], P) == 0 and common.icd_deaths(["I63"], [], P) == 0


def test_visited_among_chunks_and_empty(fake_db):
    assert common.visited_among([], P) == set()
    fake_db.add("select distinct o.hn", [{"hn": "1"}])
    assert common.visited_among(["1", "2"], P) == {"1"}


def test_bp_series_for_hns_filters_invalid(fake_db):
    fake_db.add("from opdscreen", [{"hn": "1", "sbp": 130.0, "dbp": 80.0, "d": date(2026, 1, 1)},
                                    {"hn": "1", "sbp": 0.0, "dbp": 0.0, "d": date(2026, 2, 1)}])
    assert common.bp_latest_for_hns(["1"], P) == {"1": (130.0, 80.0)}
    assert common.bp_latest_for_hns([], P) == {}


def test_drug_hns_with_clinic_intersects_in_python_not_in_sql(fake_db):
    """opitemrece ใหญ่มาก: hn IN (subquery ทะเบียน) ช้า ~15 วิ → ดึงตามรหัสยาก่อนแล้วตัดกับทะเบียนใน Python"""
    fake_db.add("select distinct r.hn", [{"hn": "1"}, {"hn": "2"}])
    fake_db.add("group by m.hn", [{"hn": "1"}])
    assert common.drug_hns(["1000345"], "001", P) == {"1"}
    drug_sql = next(b for _s, _a, b in fake_db.calls if "opitemrece" in b)
    assert "clinicmember" not in drug_sql


def test_latest_lab_reads_annotated_egfr_results(fake_db):
    """eGFR ก่อน ธ.ค. 2568 เก็บเป็น '90.58 [Stage 1]' — ต้องอ่านได้ ไม่ทิ้งผลทั้งปี"""
    fake_db.add("from lab_head", [{"hn": "1", "result": "90.58 [Stage 1]", "d": date(2025, 10, 5)},
                                   {"hn": "1", "result": "55.2", "d": date(2026, 2, 5)}])
    s = common.lab_series_by_hn(2135, None, date(2025, 10, 1), date(2026, 9, 30))
    assert s == {"1": [(date(2025, 10, 5), 90.58), (date(2026, 2, 5), 55.2)]}
