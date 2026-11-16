"""ข้อบกพร่องที่ผู้ตรวจอิสระพบ (Important 1–5) — แต่ละ test ต้องล้มก่อนแก้ แล้วผ่านหลังแก้"""
import time
from datetime import date

import pytest

import check
import hdc
import pages
import periods
from app import app
from queries import common, copd, cvd, overview

TODAY = date(2026, 11, 11)


# --- 1. ช่วงที่ยังไม่จบ / ปีงบอนาคต ------------------------------------------------

def test_future_fiscal_year_is_rejected():
    assert periods.parse({"fy": "2571"}, TODAY).fy == 2570
    assert periods.parse({"fy": "2570"}, TODAY).fy == 2570


def test_is_partial():
    assert periods.is_partial(periods.make(2570), TODAY) is True
    assert periods.is_partial(periods.make(2570, "q1"), TODAY) is True          # ไตรมาส 1 ปีงบ 70 จบ 31 ธ.ค.
    assert periods.is_partial(periods.make(2570, "m10"), TODAY) is False         # ต.ค. 69 จบแล้ว
    assert periods.is_partial(periods.make(2569), TODAY) is False


def _partial_builder(p, src="hosxp", opts=None):
    return {"title": "ทดสอบ", "table": {"title": "t", "columns": ["a", "b"], "rows": [["x", {"text": "ต่ำกว่าเป้า", "chip": "bad"}]]},
            "notes": [{"tone": "warn", "text": "ต่ำกว่าเป้า 60%"}, {"tone": "info", "text": "ข้อมูลทั่วไป"}],
            "extra": [{"type": "table", "title": "e", "columns": ["a"], "rows": [[{"text": "ผ่าน", "chip": "ok"}]]}]}


@pytest.fixture
def patched_registry(monkeypatch):
    monkeypatch.setitem(pages.REGISTRY, "ht", _partial_builder)
    monkeypatch.setattr(pages, "today", lambda: TODAY)


def test_partial_period_neutralizes_target_verdicts(patched_registry):
    d = pages.get("ht", periods.make(2570))
    chip = d["table"]["rows"][0][1]
    assert chip["chip"] == "warn" and "ยังไม่ครบช่วง" in chip["text"]
    assert d["extra"][0]["rows"][0][0]["chip"] == "warn"                          # ผ่าน/ไม่ผ่านถูกปรับทั้งหมด
    assert all("ต่ำกว่าเป้า" not in n["text"] for n in d["notes"])                # ไม่แสดงข้อสังเกตที่เทียบเป้า
    assert any(n["text"] == "ข้อมูลทั่วไป" for n in d["notes"])                   # ข้อสังเกตอื่นยังอยู่
    assert "ข้อมูลถึง" in d["partial_notice"] and "11 พ.ย. 2569" in d["partial_notice"]


def test_complete_period_keeps_verdicts(patched_registry):
    d = pages.get("ht", periods.make(2569))
    assert d["table"]["rows"][0][1]["chip"] == "bad"
    assert any(n["tone"] == "warn" for n in d["notes"]) and "partial_notice" not in d


def test_partial_notice_is_rendered(patched_registry):
    html = app.test_client().get("/ht?fy=2570").get_data(as_text=True)
    assert "ข้อมูลถึง" in html and "ยังไม่ครบช่วง" in html


def test_cvd_secondary_prevention_uses_fiscal_year_to_date_not_selected_month(fake_db):
    """เลือกเดือนเดียว: ยา/ความดัน ของกลุ่ม 3 ปีต้องดูทั้งปีงบ ไม่เช่นนั้น statin% ต่ำเทียมเพราะวัดแค่ 30 วัน"""
    fake_db.add("ovstdiag", [{"hn": "1"}])
    cvd.build(periods.make(2569, "m11"))
    drug_calls = [a for _s, a, b in fake_db.calls if "opitemrece" in b]
    assert drug_calls and all(a["start"] == date(2025, 10, 1) and a["end"] == date(2026, 9, 30) for a in drug_calls)


# --- 2. ขาดนัด: COPD นับ HN ไม่ซ้ำข้ามสองทะเบียน ----------------------------------

def test_copd_lost_to_followup_counts_unique_patients(fake_db):
    fake_db.add("group by m.hn", [{"hn": "1"}])
    fake_db.add("not exists (select 1 from ovst o where o.hn = m.hn", [{"hn": "1"}, {"hn": "2"}])   # ทั้งสองคลินิกคืนชุดเดียวกัน
    d = copd.build(periods.make(2569))
    assert next(k for k in d["kpis"] if "ขาดนัด" in k["label"])["value"] == "2"                    # ไม่ใช่ 4


# --- 3. ภาพรวม: query ล้มต้องไม่เงียบและไม่ถูกแคช ----------------------------------

def test_patient_sets_failure_is_not_silent(fake_db, monkeypatch):
    from queries import ckd

    def boom(p):
        raise RuntimeError("timeout")

    monkeypatch.setattr(ckd, "_core", boom)
    with pytest.raises(RuntimeError):
        overview._patient_sets(periods.make(2569))


def test_overview_unique_tile_shows_error_and_page_is_not_cached(fake_db, monkeypatch):
    calls = []

    def boom(p):
        calls.append(1)
        raise RuntimeError("timeout")

    monkeypatch.setattr(overview, "_patient_sets", boom)
    monkeypatch.setitem(pages.REGISTRY, "overview", overview.build)
    p = periods.make(2569)
    d = pages.get("overview", p)
    assert "error" in d["extra"][0]
    pages.get("overview", p)
    assert len(calls) == 2                                                             # ผลที่ล้มไม่ถูกแคช


def test_overview_card_of_failed_page_marks_incomplete(monkeypatch):
    def get(key, p, src="hosxp", opts=None):
        if key == "dm":
            return {"title": "dm", "page_error": "ดึงข้อมูลไม่ได้"}
        return {"title": key, "kpis": [{"label": "ผู้ป่วย", "value": "1", "sub": ""}, {"label": "x", "value": "2", "sub": ""}], "notes": []}

    monkeypatch.setattr(pages, "get", get)
    monkeypatch.setattr(overview, "_patient_sets", lambda p: {"ht": {"1"}})
    monkeypatch.setattr(overview, "_trend", lambda p: {"labels": [], "series": []})
    d = overview.build(periods.make(2569))
    assert d["incomplete"] is True and pages.has_error(d)


# --- 4. HDC: ไม่ค้างใน request และมี negative cache ---------------------------------

def _cache(tmp_path, monkeypatch, stale=True):
    import json
    from datetime import datetime, timedelta
    monkeypatch.setattr(hdc, "CACHE_PATH", str(tmp_path / "c.json"))
    hdc._FAILED.clear()
    when = (datetime.now() - timedelta(hours=48 if stale else 1)).isoformat(timespec="seconds")
    (tmp_path / "c.json").write_text(json.dumps({"s_ht_control|2569": {"fetched_at": when, "totals": {"bp": 10.0}, "by_unit": {}}}), encoding="utf-8")


def test_interactive_fetch_is_short_and_does_not_retry_long(tmp_path, monkeypatch):
    _cache(tmp_path, monkeypatch)
    seen = []

    def post(body, tries=5, timeout=60):
        seen.append((tries, timeout))
        raise RuntimeError("down")

    monkeypatch.setattr(hdc, "_post", post)
    r = hdc.fetch_table("s_ht_control", 2569)
    assert r.stale is True and seen and all(t <= 1 and to <= 15 for t, to in seen)


def test_patient_mode_keeps_long_retries_for_batch_warmup(tmp_path, monkeypatch):
    _cache(tmp_path, monkeypatch)
    seen = []
    monkeypatch.setattr(hdc, "_post", lambda body, tries=5, timeout=60: (seen.append((tries, timeout)), (_ for _ in ()).throw(RuntimeError("x")))[1])
    hdc.fetch_table("s_ht_control", 2569, patient=True)
    assert seen and seen[0][0] >= 3


def test_recent_failure_is_remembered_and_not_retried(tmp_path, monkeypatch):
    _cache(tmp_path, monkeypatch)
    n = []

    def post(body, tries=5, timeout=60):
        n.append(1)
        raise RuntimeError("down")

    monkeypatch.setattr(hdc, "_post", post)
    hdc.fetch_table("s_ht_control", 2569)
    first = len(n)
    r = hdc.fetch_table("s_ht_control", 2569)
    assert len(n) == first and r.stale is True                                       # รอบสองไม่เรียก API ซ้ำ


def test_failure_memory_applies_without_cache_too(tmp_path, monkeypatch):
    monkeypatch.setattr(hdc, "CACHE_PATH", str(tmp_path / "none.json"))
    hdc._FAILED.clear()
    n = []

    def post(body, tries=5, timeout=60):
        n.append(1)
        raise RuntimeError("down")

    monkeypatch.setattr(hdc, "_post", post)
    r1, r2 = hdc.fetch_table("s_ht_control", 2570), hdc.fetch_table("s_ht_control", 2570)
    assert r1.error and r2.error and len(n) == 1


# --- 5. ผล lab: ค่าที่เป็นไปไม่ได้ / รูปแบบติดหน่วย / /check ต้องเตือน -----------------

@pytest.mark.parametrize("text,expected", [("0", None), ("0.0", None), (" 0 ", None), ("6.5%", 6.5), ("9.2H", 9.2), ("6.5 %", 6.5),
                                           ("1e5", None), ("2E-3", None), ("<0", None)])
def test_parse_result_rejects_zero_and_accepts_attached_units(text, expected):
    from classify import parse_result
    assert parse_result(text) == expected


def test_check_warns_when_most_lab_results_cannot_be_parsed(fake_db):
    fake_db.add("from lab_items", [{"lab_items_code": 271, "lab_items_name": "HbA1C"}])
    fake_db.add("count(distinct h.hn)", [{"n": 4}])
    fake_db.add("from lab_head h join lab_order o on o.lab_order_number = h.lab_order_number where", [
        {"hn": str(i), "result": "ผลเป็นข้อความ", "d": date(2026, 1, 1)} for i in range(4)])
    r = next(x for x in check.audit(periods.make(2569)) if "HbA1c" in x["item"])
    assert r["status"] == "warn" and "อ่านเป็นตัวเลขได้" in r["found"]


def test_check_lab_ok_when_results_parse(fake_db):
    fake_db.add("from lab_items", [{"lab_items_code": 271, "lab_items_name": "HbA1C"}])
    fake_db.add("count(distinct h.hn)", [{"n": 4}])
    fake_db.add("from lab_head h join lab_order o on o.lab_order_number = h.lab_order_number where", [
        {"hn": str(i), "result": "6.5", "d": date(2026, 1, 1)} for i in range(4)])
    r = next(x for x in check.audit(periods.make(2569)) if "HbA1c" in x["item"])
    assert r["status"] == "ok" and "100" in r["found"]


def test_unused_import_guard():
    assert common and time


# --- ผลข้างเคียงของการปฏิเสธศูนย์: Microalbumin/UACR ศูนย์เป็นผลจริง (พบจาก /check บนฐานจริง: อ่านได้ 38%) ----------

def test_parse_result_allow_zero_for_labs_where_zero_is_real():
    from classify import parse_result
    assert parse_result("0", allow_zero=True) == 0.0 and parse_result("0.0", allow_zero=True) == 0.0
    assert parse_result("0") is None


def test_latest_lab_allow_zero(fake_db):
    fake_db.add("from lab_head", [{"hn": "1", "result": "0", "d": date(2026, 1, 1)}])
    p = periods.make(2569)
    assert common.latest_lab_by_hn([318], None, p)[0]["value"] is None
    assert common.latest_lab_by_hn([318], None, p, allow_zero=True)[0]["value"] == 0.0
    assert common.lab_series_by_hn([318], None, p.start, p.end, allow_zero=True) == {"1": [(date(2026, 1, 1), 0.0)]}


def test_check_counts_zero_microalbumin_as_readable(fake_db):
    fake_db.add("from lab_items", [{"lab_items_code": 318, "lab_items_name": "Microalbumin"}])
    fake_db.add("count(distinct h.hn)", [{"n": 4}])
    fake_db.add("from lab_head h join lab_order o on o.lab_order_number = h.lab_order_number where", [
        {"hn": str(i), "result": "0", "d": date(2026, 1, 1)} for i in range(4)])
    r = next(x for x in check.audit(periods.make(2569)) if "UACR" in x["item"])
    assert r["status"] == "ok" and "100%" in r["found"]


def test_dm_screening_counts_zero_uacr_as_tested(fake_db):
    from queries import dm
    fake_db.add("from lab_head", [{"hn": "1", "result": "0", "d": date(2026, 1, 1)}])
    assert dm._tested_pct(["318"], "001", periods.make(2569), 10, allow_zero=True) == 10.0
    assert dm._tested_pct(["270"], "001", periods.make(2569), 10) == 0.0         # LDL ศูนย์ = ไม่ใช่ผลจริง
