"""HDC: ดึงวันละครั้งแบบเบื้องหลัง · หน้าเว็บอ่านจากแคชเท่านั้น · ไม่มีข้อมูลปีงบที่เลือก/ดึงไม่ได้ → ใช้ข้อมูลล่าสุดที่เคยดึงไว้"""
import json
from datetime import datetime, timedelta

import pytest

import hdc
import periods
from queries import hdc_views


@pytest.fixture
def cache_path(tmp_path, monkeypatch):
    p = tmp_path / "hdc_cache.json"
    monkeypatch.setattr(hdc, "CACHE_PATH", str(p))
    hdc._FAILED.clear()
    monkeypatch.setattr(hdc.time, "sleep", lambda s: None)
    yield p
    hdc._FAILED.clear()


def put(path, table, fy, hours_old=1, result=40.0):
    cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    when = (datetime.now() - timedelta(hours=hours_old)).isoformat(timespec="seconds")
    cache[f"{table}|{fy}"] = {"fetched_at": when, "totals": {"target": 100.0, "result": result},
                              "by_unit": {"07001": {"target": 100.0, "result": result}}}
    path.write_text(json.dumps(cache), encoding="utf-8")
    return when


def api(rows):
    return lambda body, tries=5, **kw: {"data": rows, "total": len(rows)}


def district_row(target=60, result=20):
    return {"hospcode": "07001", "areacode": "302501", "target": target, "result": result, "date_com": "202611120300",
            "age_group": None, "groupcode": None, "groupname": None, "yymm": None}


def no_api(*a, **k):
    pytest.fail("หน้าเว็บ/การอ่านแคชต้องไม่เรียก API")


# --- get(): อ่านแคชเท่านั้น -----------------------------------------------------------

def test_get_never_calls_the_api(cache_path, monkeypatch):
    monkeypatch.setattr(hdc, "_post", no_api)
    r = hdc.get("s_dm_control", 2570)
    assert r.error and r.totals == {}


def test_get_returns_cached_fresh_entry(cache_path, monkeypatch):
    put(cache_path, "s_dm_control", 2569, hours_old=2)
    monkeypatch.setattr(hdc, "_post", no_api)
    r = hdc.get("s_dm_control", 2569)
    assert r.totals["result"] == 40.0 and r.stale is False and r.fallback_fy is None and r.error is None


def test_get_marks_entry_stale_when_daily_sync_has_not_succeeded(cache_path):
    put(cache_path, "s_dm_control", 2569, hours_old=48)
    r = hdc.get("s_dm_control", 2569)
    assert r.stale is True and r.totals["result"] == 40.0 and r.error is None


def test_get_falls_back_to_latest_earlier_year(cache_path):
    put(cache_path, "s_dm_control", 2568, result=10.0)
    put(cache_path, "s_dm_control", 2569, result=40.0)
    r = hdc.get("s_dm_control", 2570)
    assert r.fallback_fy == 2569 and r.stale is True and r.totals["result"] == 40.0 and r.error is None


def test_get_prefers_the_requested_year_over_fallback(cache_path):
    put(cache_path, "s_dm_control", 2569, result=40.0)
    put(cache_path, "s_dm_control", 2570, result=7.0)
    r = hdc.get("s_dm_control", 2570)
    assert r.fallback_fy is None and r.totals["result"] == 7.0


def test_get_never_falls_back_to_a_later_year(cache_path):
    put(cache_path, "s_dm_control", 2570, result=7.0)
    assert hdc.get("s_dm_control", 2569).error


# --- sync(): ดึงวันละครั้ง --------------------------------------------------------------

def test_sync_fetches_missing_table_and_saves(cache_path, monkeypatch):
    monkeypatch.setattr(hdc, "_post", api([district_row()]))
    out = hdc.sync(2569, tables=["s_dm_control"])
    assert out["ok"] == ["s_dm_control"]
    assert json.loads(cache_path.read_text(encoding="utf-8"))["s_dm_control|2569"]["totals"]["target"] == 60.0


def test_sync_skips_tables_fetched_within_a_day(cache_path, monkeypatch):
    put(cache_path, "s_dm_control", 2569, hours_old=5)
    monkeypatch.setattr(hdc, "_post", no_api)
    out = hdc.sync(2569, tables=["s_dm_control"])
    assert out["fresh"] == ["s_dm_control"] and not out["ok"] and not out["failed"]


def test_sync_refetches_after_a_day(cache_path, monkeypatch):
    put(cache_path, "s_dm_control", 2569, hours_old=30, result=40.0)
    monkeypatch.setattr(hdc, "_post", api([district_row(target=80, result=33)]))
    assert hdc.sync(2569, tables=["s_dm_control"])["ok"] == ["s_dm_control"]
    assert hdc.get("s_dm_control", 2569).totals["result"] == 33.0


def test_sync_failure_keeps_old_cache(cache_path, monkeypatch):
    put(cache_path, "s_dm_control", 2569, hours_old=30, result=40.0)
    before = cache_path.read_text(encoding="utf-8")
    monkeypatch.setattr(hdc, "_post", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    out = hdc.sync(2569, tables=["s_dm_control"])
    assert out["failed"] == ["s_dm_control"]
    assert cache_path.read_text(encoding="utf-8") == before
    assert hdc.get("s_dm_control", 2569).totals["result"] == 40.0


def test_sync_year_not_published_yet_is_not_retried_all_day(cache_path, monkeypatch):
    n = []

    def post(body, tries=5, **kw):
        n.append(1)
        return {"data": [], "total": "0"}                # HDC ยังไม่ปล่อยข้อมูลปีงบนี้

    monkeypatch.setattr(hdc, "_post", post)
    out = hdc.sync(2570, tables=["s_dm_control"])
    assert out["empty"] == ["s_dm_control"] and not cache_path.exists()
    calls = len(n)
    out2 = hdc.sync(2570, tables=["s_dm_control"])
    assert len(n) == calls and out2["waiting"] == ["s_dm_control"]


def test_sync_network_error_is_retried_sooner_than_a_day(cache_path, monkeypatch):
    monkeypatch.setattr(hdc, "_post", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    hdc.sync(2570, tables=["s_dm_control"])
    key = "s_dm_control|2570"
    assert key in hdc._FAILED
    hdc._FAILED[key] -= hdc.RETRY_AFTER + 5              # ผ่านช่วงรอแล้ว
    n = []
    monkeypatch.setattr(hdc, "_post", lambda *a, **k: (n.append(1), {"data": [district_row()], "total": 1})[1])
    assert hdc.sync(2570, tables=["s_dm_control"])["ok"] == ["s_dm_control"] and n


def test_sync_continues_after_one_table_fails(cache_path, monkeypatch):
    def post(body, tries=5, **kw):
        if body["tableName"] == "s_dm_control":
            raise RuntimeError("x")
        return {"data": [district_row()], "total": 1}

    monkeypatch.setattr(hdc, "_post", post)
    out = hdc.sync(2569, tables=["s_dm_control", "s_ht_control"])
    assert out["failed"] == ["s_dm_control"] and out["ok"] == ["s_ht_control"]


def test_sync_uses_patient_mode_for_background(cache_path, monkeypatch):
    seen = []
    monkeypatch.setattr(hdc, "_post", lambda body, tries=5, timeout=60: (seen.append((tries, timeout)), {"data": [district_row()], "total": 1})[1])
    hdc.sync(2569, tables=["s_dm_control"])
    assert seen and seen[0][0] >= 3


# --- หน้าจอ: บอกให้ชัดว่าแสดงข้อมูลของปีงบอื่น --------------------------------------------

def test_views_warn_when_showing_an_earlier_year(cache_path):
    for t in ("s_ht_control", "s_ht_screen", "s_ht_incidence", "s_ht_pop_age"):
        put(cache_path, t, 2569)
    d = hdc_views.build_ht(periods.make(2570))
    texts = " ".join(n["text"] for n in d["notes"] if n["tone"] == "warn")
    assert "2570" in texts and "2569" in texts
    assert not any(isinstance(k["value"], str) and k["value"] == hdc_views.NA for k in d["kpis"])


def test_views_have_no_year_warning_when_year_is_present(cache_path):
    for t in ("s_ht_control", "s_ht_screen", "s_ht_incidence", "s_ht_pop_age"):
        put(cache_path, t, 2569)
    d = hdc_views.build_ht(periods.make(2569))
    assert not [n for n in d["notes"] if n["tone"] == "warn"]
